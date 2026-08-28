import sys
import os
import time
import json
import logging
import urllib.parse
import requests
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Generator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.ollama_client import OllamaAI
from utils.helpers import load_profile, load_keywords, load_settings, get_project_root
from database.models import Job, Application, Notification
from agents.matcher import JobMatcher
from agents.cover_letter import CoverLetterGenerator
from agents.form_filler import FormFiller
from agents.notifier import SMSNotifier

logger = logging.getLogger(__name__)

class AutoJobHunter:
    """
    Autonomous Job Search & Auto-Apply Engine:
    1. Analyzes a given job description to extract target titles & key skills.
    2. Searches online job platforms (LinkedIn, Remotive, web feeds) for matching openings.
    3. AI evaluates fit & scores each job (0-100%).
    4. Auto-generates tailored cover letters.
    5. Pre-fills & submits applications via Playwright.
    6. Sends SMS confirmation to user's phone.
    """
    def __init__(self):
        self.ai = OllamaAI()
        self.matcher = JobMatcher()
        self.cl_gen = CoverLetterGenerator()
        self.notifier = SMSNotifier()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        })

    def extract_search_terms(self, job_description: str) -> Dict[str, Any]:
        """Uses AI to extract search keywords and location from raw job description."""
        prompt = f"""
Given this job description, extract:
1. The most accurate job title to search for (e.g., 'Python Developer', 'Data Engineer')
2. Top 5 required skills (list of strings)
3. Target location (string, default to 'Remote' if not specified)

Job Description:
{job_description[:1500]}

Return ONLY valid JSON with keys: 'title', 'skills', 'location'.
"""
        try:
            res = self.ai._chat(prompt)
            if "```json" in res:
                res = res.split("```json")[1].split("```")[0].strip()
            elif "```" in res:
                res = res.split("```")[1].strip()
            return json.loads(res)
        except Exception:
            return {"title": "Software Developer", "skills": ["Python"], "location": "Remote"}

    def search_linkedin(self, keyword: str, location: str = "Remote", limit: int = 10) -> List[Dict[str, Any]]:
        """Searches LinkedIn public job listings."""
        jobs = []
        kw_encoded = urllib.parse.quote(keyword)
        loc_encoded = urllib.parse.quote(location)
        # f_AL=true filters exclusively for Easy Apply jobs that submit automatically on LinkedIn
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={kw_encoded}&location={loc_encoded}&f_AL=true&start=0"
        
        try:
            r = self.session.get(url, timeout=12)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                cards = soup.find_all('li')
                if not cards:
                    # Fallback to broader search if Easy Apply filter has low volume
                    fallback_url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={kw_encoded}&location={loc_encoded}&start=0"
                    r_fb = self.session.get(fallback_url, timeout=12)
                    if r_fb.status_code == 200:
                        soup = BeautifulSoup(r_fb.text, 'html.parser')
                        cards = soup.find_all('li')
                for card in cards[:limit]:
                    try:
                        title_el = card.find('h3', class_='base-search-card__title')
                        comp_el = card.find('h4', class_='base-search-card__subtitle')
                        loc_el = card.find('span', class_='job-search-card__location')
                        link_el = card.find('a', class_='base-card__full-link')
                        
                        title = title_el.get_text(strip=True) if title_el else "Software Developer"
                        company = comp_el.get_text(strip=True) if comp_el else "Technology Company"
                        loc = loc_el.get_text(strip=True) if loc_el else location
                        link = link_el['href'].split('?')[0] if link_el and 'href' in link_el.attrs else ""
                        
                        if link:
                            jobs.append({
                                'title': title,
                                'company': company,
                                'location': loc,
                                'url': link,
                                'source': 'LinkedIn',
                                'description': f"{title} role at {company} in {loc}. Seeking skilled candidates with relevant technical background."
                            })
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"LinkedIn search error: {e}")
        return jobs

    def search_remote_jobs(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Searches public remote developer job feeds (Remotive / Arbeitnow)."""
        jobs = []
        try:
            url = f"https://remotive.com/api/remote-jobs?search={urllib.parse.quote(keyword)}&limit={limit}"
            r = self.session.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json().get('jobs', [])
                for item in data[:limit]:
                    desc = BeautifulSoup(item.get('description', ''), 'html.parser').get_text(separator=' ', strip=True)
                    jobs.append({
                        'title': item.get('title', 'Developer'),
                        'company': item.get('company_name', 'Tech Corp'),
                        'location': item.get('candidate_required_location', 'Remote'),
                        'url': item.get('url', ''),
                        'salary': item.get('salary', 'Competitive'),
                        'source': 'Remotive',
                        'description': desc[:1500]
                    })
        except Exception as e:
            logger.error(f"Remotive search error: {e}")
        return jobs

    def search_arbeitnow_jobs(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Searches Arbeitnow developer job feed (instant, rate-limit free)."""
        jobs = []
        try:
            url = f"https://www.arbeitnow.com/api/job-board-api"
            r = self.session.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json().get('data', [])
                kw_lower = keyword.lower()
                for item in data:
                    title = item.get('title', '')
                    desc = BeautifulSoup(item.get('description', ''), 'html.parser').get_text(separator=' ', strip=True)
                    if any(w in (title + " " + desc).lower() for w in kw_lower.split()):
                        jobs.append({
                            'title': title,
                            'company': item.get('company_name', 'Tech Company'),
                            'location': item.get('location', 'Remote'),
                            'url': item.get('url', ''),
                            'salary': 'Competitive',
                            'source': 'Arbeitnow',
                            'description': desc[:1500]
                        })
                        if len(jobs) >= limit:
                            break
        except Exception as e:
            logger.error(f"Arbeitnow search error: {e}")
        return jobs

    def search_similar_jobs(self, query_title: str, location: str = "Remote", limit: int = 10) -> List[Dict[str, Any]]:
        """Searches across multiple platforms (Remotive, Arbeitnow, LinkedIn) with zero rate-limit blocks."""
        results = []
        
        # 1. Search Remotive Feed (instant API)
        rem_jobs = self.search_remote_jobs(query_title, limit=limit)
        results.extend(rem_jobs)

        # 2. Search Arbeitnow Feed (instant API)
        if len(results) < limit:
            arb_jobs = self.search_arbeitnow_jobs(query_title, limit=limit - len(results))
            results.extend(arb_jobs)

        # 3. Search LinkedIn as supplemental feed
        if len(results) < limit:
            li_jobs = self.search_linkedin(query_title, location, limit=limit - len(results))
            results.extend(li_jobs)
            
        return results[:limit]

    def auto_hunt_and_apply(
        self,
        job_description: str,
        max_jobs: int = 5,
        min_score: int = 50,
        auto_launch_browser: bool = False
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Main generator pipeline:
        Yields status dictionaries as each job is discovered, scored, and applied.
        """
        # Step 1: AI Search Term Extraction
        yield {"step": "analyzing", "message": "🔍 Analyzing job description to extract target role and skills..."}
        terms = self.extract_search_terms(job_description)
        title = terms.get("title", "Software Developer")
        location = terms.get("location", "Remote")
        yield {"step": "extracted", "message": f"🎯 Target Role: **{title}** | Location: **{location}**"}

        # Step 2: Online Job Search
        yield {"step": "searching", "message": f"🌐 Searching LinkedIn & remote feeds for '{title}' openings..."}
        found_jobs = self.search_similar_jobs(title, location, limit=max_jobs * 2)
        
        if not found_jobs:
            # Fallback search with broader term
            found_jobs = self.search_similar_jobs("Python Developer", "Remote", limit=max_jobs)
            
        yield {"step": "found", "message": f"📋 Found **{len(found_jobs)}** matching job postings. Evaluating AI match fit...", "jobs_count": len(found_jobs)}

        # Step 3: Match, Generate Cover Letter, and Apply
        applied_count = 0
        filler = None
        if auto_launch_browser:
            try:
                filler = FormFiller()
            except Exception:
                pass

        for idx, job_data in enumerate(found_jobs):
            if applied_count >= max_jobs:
                break
                
            yield {"step": "evaluating", "job": job_data, "message": f"🤖 Evaluating ({idx+1}/{len(found_jobs)}): {job_data['title']} at {job_data['company']}..."}
            
            # AI Fit Evaluation
            match_res = self.matcher.match_job(job_data)
            score = int(match_res.get('score', 75))
            reasoning = match_res.get('reasoning', '')
            job_data['match_score'] = score
            job_data['match_reasoning'] = reasoning

            if score >= min_score:
                # Generate custom cover letter
                yield {"step": "writing_letter", "job": job_data, "message": f"✍️ Generating tailored cover letter for {job_data['company']}..."}
                cl_text = self.cl_gen.generate(job_data)
                
                # Save Job to Database
                try:
                    db_job = Job.create(
                        title=job_data['title'],
                        company=job_data['company'],
                        location=job_data.get('location', 'Remote'),
                        url=job_data.get('url', ''),
                        description=job_data.get('description', ''),
                        status='applied' if auto_launch_browser else 'matched',
                        match_score=score,
                        match_reasoning=reasoning,
                        source=job_data.get('source', 'Auto-Hunter')
                    )
                    Application.create(
                        job=db_job,
                        cover_letter=cl_text,
                        status='submitted' if auto_launch_browser else 'ready'
                    )
                except Exception as e:
                    logger.error(f"Error saving job to database: {e}")

                # Auto-fill & submit application in browser if requested
                if auto_launch_browser and filler and job_data.get('url'):
                    try:
                        yield {"step": "applying", "job": job_data, "message": f"🌐 Submitting application automatically for {job_data['title']} at {job_data['company']} with resume.pdf..."}
                        res = filler.auto_apply(job_data['url'], cover_letter=cl_text, headless=False)
                        if res.get('status') == 'submitted':
                            yield {"step": "submitted", "job": job_data, "message": f"🚀 Application submitted to {job_data['company']}!"}
                    except Exception as e:
                        logger.error(f"Auto-apply error: {e}")

                # Send Notification
                try:
                    self.notifier.notify_applied(job_data['title'], job_data['company'])
                except Exception:
                    pass

                applied_count += 1
                yield {
                    "step": "job_completed",
                    "job": job_data,
                    "score": score,
                    "cover_letter": cl_text,
                    "applied_count": applied_count,
                    "message": f"✅ Processed ({applied_count}/{max_jobs}): **{job_data['title']}** at **{job_data['company']}** (Match: {score}%)"
                }
            else:
                yield {
                    "step": "skipped",
                    "job": job_data,
                    "score": score,
                    "message": f"⏭️ Skipped {job_data['title']} at {job_data['company']} (Score {score}% below threshold {min_score}%)"
                }

        yield {
            "step": "finished",
            "applied_count": applied_count,
            "message": f"🎉 Auto-Hunt Completed! Successfully processed **{applied_count}** matching jobs."
        }
