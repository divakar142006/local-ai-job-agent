import sys
sys.path.insert(0, 'D:\\job-agent')

from typing import Dict, Any, Optional
import time
import logging

try:
    from playwright.sync_api import sync_playwright, Page
except ImportError:
    sync_playwright = None
    Page = Any

from utils.ollama_client import OllamaAI
from utils.helpers import load_profile, load_keywords, load_settings, sanitize_text, format_job_summary
from database.models import Job, Application, Notification, initialize_db

logger = logging.getLogger(__name__)

class FormFiller:
    """
    Automates the process of pre-filling job application forms.
    IMPORTANT: Leaves the browser visible and never auto-submits.
    """

    # Mapping dict of common field names/ids/labels for each field type
    FIELD_SELECTORS = {
        'first_name': ['input[name*="first"][name*="name"]', 'input[id*="first"][id*="name"]', 'input[placeholder*="First Name" i]'],
        'last_name': ['input[name*="last"][name*="name"]', 'input[id*="last"][id*="name"]', 'input[placeholder*="Last Name" i]'],
        'full_name': ['input[name*="name"]', 'input[id*="name"]', 'input[placeholder*="Full Name" i]'],
        'email': ['input[type="email"]', 'input[name*="email"]', 'input[id*="email"]', 'input[placeholder*="Email" i]'],
        'phone': ['input[type="tel"]', 'input[name*="phone"]', 'input[id*="phone"]', 'input[placeholder*="Phone" i]'],
        'location': ['input[name*="location"]', 'input[name*="city"]', 'input[id*="location"]', 'input[placeholder*="City" i]'],
        'linkedin': ['input[name*="linkedin"]', 'input[id*="linkedin"]', 'input[placeholder*="LinkedIn" i]'],
        'portfolio': ['input[name*="portfolio"]', 'input[name*="website"]', 'input[id*="website"]', 'input[placeholder*="Website" i]']
    }

    def __init__(self):
        """
        Loads user profile and prepares for Playwright initialization (lazy loading).
        """
        self.profile = load_profile()
        self.playwright = None
        self.browser = None
        self.context = None

    def open_and_prefill(self, url: str, cover_letter: Optional[str] = None) -> Dict[str, Any]:
        """
        Opens URL in a VISIBLE browser window and tries to pre-fill common fields.
        
        Args:
            url (str): The application form URL.
            cover_letter (str, optional): The generated cover letter.
            
        Returns:
            dict: Status of the pre-fill operation, fields filled, and a message.
        """
        if not sync_playwright:
            return {'status': 'error', 'fields_filled': [], 'message': 'Playwright not installed.'}

        try:
            self.playwright = sync_playwright().start()
            # IMPORTANT: headless=False so user can review and manually submit
            self.browser = self.playwright.chromium.launch(headless=False)
            self.context = self.browser.new_context()
            page = self.context.new_page()
            
            page.goto(url, wait_until='networkidle', timeout=60000)
            
            fields_filled = []
            
            # Basic mapping from profile
            profile_data = {
                'first_name': self.profile.get('first_name', ''),
                'last_name': self.profile.get('last_name', ''),
                'full_name': f"{self.profile.get('first_name', '')} {self.profile.get('last_name', '')}".strip(),
                'email': self.profile.get('email', ''),
                'phone': self.profile.get('phone', ''),
                'location': self.profile.get('location', ''),
                'linkedin': self.profile.get('linkedin_url', ''),
                'portfolio': self.profile.get('portfolio_url', '')
            }

            for field_type, value in profile_data.items():
                if value and self._find_and_fill_field(page, field_type, value):
                    fields_filled.append(field_type)

            resume_path = self.profile.get('resume_path')
            if resume_path:
                if self._upload_resume(page, resume_path):
                    fields_filled.append('resume')

            if cover_letter:
                if self._fill_cover_letter(page, cover_letter):
                    fields_filled.append('cover_letter')
                    
            return {
                'status': 'opened',
                'fields_filled': fields_filled,
                'message': 'Form opened and pre-filled successfully. Please review and submit manually.'
            }
            
        except Exception as e:
            logger.error(f"Error in form filler: {e}")
            return {
                'status': 'error',
                'fields_filled': [],
                'message': str(e)
            }

    def _find_and_fill_field(self, page: Page, field_type: str, value: str) -> bool:
        """
        Finds input fields by common attributes and fills them.
        """
        selectors = self.FIELD_SELECTORS.get(field_type, [])
        for selector in selectors:
            try:
                # Find the first visible element matching the selector
                locator = page.locator(selector).first
                if locator.is_visible(timeout=1000):
                    locator.fill(value)
                    return True
            except Exception:
                continue
        return False

    def _upload_resume(self, page: Page, resume_path: str) -> bool:
        """
        Finds file upload input and uploads resume.
        """
        try:
            file_input = page.locator('input[type="file"]').first
            if file_input.is_visible(timeout=1000):
                file_input.set_input_files(resume_path)
                return True
        except Exception as e:
            logger.debug(f"Could not upload resume: {e}")
        return False

    def _fill_cover_letter(self, page: Page, cover_letter: str) -> bool:
        """
        Finds textarea and pastes cover letter.
        """
        selectors = ['textarea[name*="cover"]', 'textarea[id*="cover"]', 'textarea[placeholder*="cover letter" i]']
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.is_visible(timeout=1000):
                    locator.fill(cover_letter)
                    return True
            except Exception:
                continue
        return False

    def close(self):
        """
        Closes the browser instance.
        """
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
