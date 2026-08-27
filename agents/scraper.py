import sys
sys.path.insert(0, 'D:\\job-agent')

import requests
from bs4 import BeautifulSoup
from typing import Dict, Any
import logging

from utils.ollama_client import OllamaAI
from utils.helpers import load_profile, load_keywords, load_settings, sanitize_text, format_job_summary
from database.models import Job, Application, Notification, initialize_db

logger = logging.getLogger(__name__)

class JobScraper:
    """
    Scraper module to extract job information from URLs or raw text.
    """

    def __init__(self):
        """
        Initializes the requests session with a proper fake user-agent header to avoid blocking.
        """
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        })

    def scrape_url(self, url: str) -> Dict[str, Any]:
        """
        Scrapes a public job page. Determines the right strategy based on the URL.
        
        Args:
            url (str): The URL of the job posting.
            
        Returns:
            dict: Parsed job data containing title, company, location, description, requirements, salary, url.
        """
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error fetching URL {url}: {e}")
            return self._empty_job_dict(url)
            
        if 'linkedin.com' in url:
            return self._scrape_linkedin_public(response.text, url)
        elif 'naukri.com' in url:
            return self._scrape_naukri(response.text, url)
        else:
            return self._scrape_generic(response.text, url)

    def _scrape_linkedin_public(self, html: str, url: str) -> Dict[str, Any]:
        """
        Handles public LinkedIn job pages, extracting from meta tags and structured data.
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        title = soup.find('h1', class_='top-card-layout__title')
        title_text = title.get_text(strip=True) if title else 'Unknown Title'
        
        company = soup.find('a', class_='topcard__org-name-link')
        company_text = company.get_text(strip=True) if company else 'Unknown Company'
        
        location = soup.find('span', class_='topcard__flavor--bullet')
        location_text = location.get_text(strip=True) if location else 'Unknown Location'
        
        description = soup.find('div', class_='description__text')
        description_text = description.get_text(separator='\n', strip=True) if description else ''
        
        return {
            'title': title_text,
            'company': company_text,
            'location': location_text,
            'description': description_text,
            'requirements': '',  # To be extracted by AI later if needed
            'salary': '',
            'url': url
        }

    def _scrape_naukri(self, html: str, url: str) -> Dict[str, Any]:
        """
        Handles Naukri job pages, extracting from common CSS classes.
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        title = soup.find('h1', class_='jd-header-title')
        title_text = title.get_text(strip=True) if title else 'Unknown Title'
        
        company = soup.find('div', class_='jd-header-comp-name')
        company_text = company.get_text(strip=True) if company else 'Unknown Company'
        
        location = soup.find('span', class_='location')
        location_text = location.get_text(strip=True) if location else 'Unknown Location'
        
        description = soup.find('section', class_='job-desc')
        description_text = description.get_text(separator='\n', strip=True) if description else ''
        
        salary = soup.find('span', class_='salary')
        salary_text = salary.get_text(strip=True) if salary else ''
        
        return {
            'title': title_text,
            'company': company_text,
            'location': location_text,
            'description': description_text,
            'requirements': '',
            'salary': salary_text,
            'url': url
        }

    def _scrape_generic(self, html: str, url: str) -> Dict[str, Any]:
        """
        Generic scraper that extracts the main text content.
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Heuristic approach for generic pages
        title = soup.title.get_text(strip=True) if soup.title else 'Unknown Title'
        
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer"]):
            script.extract()
            
        description_text = soup.get_text(separator='\n', strip=True)
        
        return {
            'title': title,
            'company': 'Unknown Company', # Needs advanced extraction
            'location': 'Unknown Location',
            'description': description_text,
            'requirements': '',
            'salary': '',
            'url': url
        }

    def scrape_text(self, raw_text: str) -> Dict[str, Any]:
        """
        Wraps raw job description text into the standard dictionary format.
        """
        return {
            'title': 'Pasted Job',
            'company': 'Unknown',
            'location': 'Unknown',
            'description': sanitize_text(raw_text),
            'requirements': '',
            'salary': '',
            'url': 'manual-entry'
        }

    def _empty_job_dict(self, url: str) -> Dict[str, Any]:
        return {
            'title': 'Error',
            'company': 'Error',
            'location': 'Error',
            'description': '',
            'requirements': '',
            'salary': '',
            'url': url
        }
