import sys
sys.path.insert(0, 'D:\\job-agent')

from typing import Dict, Any, List
import logging

from utils.ollama_client import OllamaAI
from utils.helpers import load_profile, load_keywords, load_settings, sanitize_text, format_job_summary
from database.models import Job, Application, Notification, initialize_db

logger = logging.getLogger(__name__)

class JobMatcher:
    """
    Evaluates jobs against user profile using keyword matching and AI-based scoring.
    """

    def __init__(self):
        """
        Loads OllamaAI, user profile, and keywords settings.
        """
        self.ai = OllamaAI()
        self.profile = load_profile()
        self.keywords = load_keywords()
        self.settings = load_settings()
        self.min_match_score = self.settings.get('min_match_score', 70)

    def match_job(self, job_data: Any) -> Dict[str, Any]:
        """
        Full matching pipeline: keyword filter followed by AI match score.
        Accepts a dictionary or raw description string.
        """
        if isinstance(job_data, str):
            job_data = {
                'title': 'Job Posting',
                'company': 'Unknown Company',
                'location': 'Unknown',
                'description': job_data
            }
        elif not isinstance(job_data, dict):
            job_data = {'title': 'Job', 'description': str(job_data)}

        # Refresh profile & keywords dynamically
        self.profile = load_profile()
        self.keywords = load_keywords()

        filter_result = self.keyword_filter(job_data)
        if not filter_result['passed']:
            return {
                'score': 0,
                'reasoning': f"Filtered out: {', '.join(filter_result['reasons'])}",
                'matching_skills': [],
                'missing_skills': [],
                'recommendation': 'Skip'
            }
            
        # Proceed to AI match if it passes the basic filters
        ai_result = self.ai_match(job_data)
        return ai_result

    def keyword_filter(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Quick pre-filter using keywords configuration.
        Checks exclusions and target titles.
        """
        title = str(job_data.get('title', '')).lower()
        description = str(job_data.get('description', '')).lower()
        
        target_titles = [t.lower() for t in self.keywords.get('target_titles', []) if t]
        exclude_keywords = [k.lower() for k in self.keywords.get('exclude_keywords', []) if k]
        
        reasons = []
        passed = True
        
        # Check exclusions first
        for ex in exclude_keywords:
            if ex in title or ex in description:
                passed = False
                reasons.append(f"Contains excluded keyword: '{ex}'")
                
        # Check target titles with flexible token matching
        if target_titles and title not in ['', 'unknown title', 'pasted job', 'job posting', 'job']:
            has_match = False
            for tt in target_titles:
                tokens = tt.split()
                if all(tok in title for tok in tokens) or all(tok in description for tok in tokens):
                    has_match = True
                    break
            if not has_match:
                # Core engineering indicator fallback
                core_tech = ['python', 'developer', 'engineer', 'analyst', 'software', 'data', 'programmer']
                if any(c in title for c in core_tech):
                    has_match = True
                    
            if not has_match:
                passed = False
                reasons.append("Title/description does not match target titles")
                
        return {
            'passed': passed,
            'reasons': reasons
        }

    def ai_match(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Uses the Ollama AI client to calculate a detailed match score.
        """
        try:
            # Assuming OllamaAI has a calculate_match_score method
            return self.ai.calculate_match_score(job_data, self.profile)
        except Exception as e:
            logger.error(f"Error calculating AI match score: {e}")
            return {
                'score': 0,
                'reasoning': f"AI processing error: {e}",
                'matching_skills': [],
                'missing_skills': [],
                'recommendation': 'Error'
            }

    def should_notify(self, score: int) -> bool:
        """
        Checks if the job score meets the minimum threshold to notify the user.
        """
        return score >= self.min_match_score

    def rank_jobs(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Sorts a list of job dicts (which must include a 'score' key) by match score descending.
        """
        return sorted(jobs, key=lambda j: j.get('score', 0), reverse=True)
