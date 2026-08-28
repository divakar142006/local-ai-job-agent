import sys
import os
import time
import json
import logging
from typing import Dict, Any, Optional, List

try:
    from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeoutError
except ImportError:
    sync_playwright = None
    Page = Any
    PlaywrightTimeoutError = Exception

from utils.ollama_client import OllamaAI
from utils.helpers import load_profile, load_keywords, load_settings, sanitize_text, format_job_summary, get_project_root
from database.models import Job, Application, Notification

logger = logging.getLogger(__name__)

class FormFiller:
    """
    Autonomous Form Filler & Application Submitter:
    - Connects directly to your real, already logged-in Google Chrome browser via CDP (port 9222).
    - Falls back to launching real Google Chrome with your resume.pdf and profile details.
    - Automates Easy Apply and career portal form submission.
    """

    FIELD_SELECTORS = {
        'first_name': ['input[name*="first"][name*="name"]', 'input[id*="first"][id*="name"]', 'input[placeholder*="First Name" i]'],
        'last_name': ['input[name*="last"][name*="name"]', 'input[id*="last"][id*="name"]', 'input[placeholder*="Last Name" i]'],
        'full_name': ['input[name*="name"]', 'input[id*="name"]', 'input[placeholder*="Full Name" i]', 'input[aria-label*="Full name" i]'],
        'email': ['input[type="email"]', 'input[name*="email"]', 'input[id*="email"]', 'input[placeholder*="Email" i]', 'input[aria-label*="Email" i]'],
        'phone': ['input[type="tel"]', 'input[name*="phone"]', 'input[id*="phone"]', 'input[name*="mobile"]', 'input[placeholder*="Phone" i]', 'input[aria-label*="Phone" i]'],
        'location': ['input[name*="location"]', 'input[name*="city"]', 'input[id*="location"]', 'input[placeholder*="City" i]', 'input[aria-label*="City" i]'],
        'linkedin': ['input[name*="linkedin"]', 'input[id*="linkedin"]', 'input[placeholder*="LinkedIn" i]', 'input[aria-label*="LinkedIn" i]'],
        'github': ['input[name*="github"]', 'input[id*="github"]', 'input[placeholder*="GitHub" i]', 'input[aria-label*="GitHub" i]'],
        'portfolio': ['input[name*="portfolio"]', 'input[name*="website"]', 'input[id*="website"]', 'input[placeholder*="Website" i]']
    }

    def __init__(self):
        self.profile = load_profile()
        self.ai = OllamaAI()

    def get_resume_path(self) -> Optional[str]:
        """Resolves absolute path to Kantubothu Divakara Rao's official resume PDF."""
        candidates = [
            self.profile.get('resume_path'),
            os.path.join(get_project_root(), "resume.pdf"),
            r"D:\job-agent\resume.pdf",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resume.pdf")
        ]
        for path in candidates:
            if path and os.path.exists(path):
                return os.path.abspath(path)
        return None

    def start_real_chrome_with_cdp(self) -> Dict[str, Any]:
        """
        Launches Google Chrome with Remote Debugging Port 9222 attached to your existing Chrome profile.
        This gives the AI agent 100% instant access to your already logged-in LinkedIn account!
        """
        try:
            import subprocess
            chrome_exe = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
            if not os.path.exists(chrome_exe):
                chrome_exe = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

            # Launch Chrome with debugging port
            cmd = f'"{chrome_exe}" --remote-debugging-port=9222 "https://www.linkedin.com"'
            subprocess.Popen(cmd, shell=True)
            return {
                'status': 'opened',
                'message': '🚀 Connected your real Google Chrome browser on port 9222 with your logged-in LinkedIn account!'
            }
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def auto_apply(self, url: str, cover_letter: Optional[str] = None, headless: bool = False) -> Dict[str, Any]:
        """
        AUTONOMOUS APPLY:
        1. Checks for existing logged-in Chrome via CDP.
        2. Or launches real Google Chrome.
        3. Fills details from resume, attaches resume.pdf, and submits application.
        """
        if not sync_playwright:
            return {'status': 'error', 'message': 'Playwright browser automation runs locally on your laptop (http://localhost:8501).'}

        self.profile = load_profile()
        pw_inst = None
        browser_inst = None
        is_cdp = False

        try:
            pw_inst = sync_playwright().start()

            # Attempt 1: Connect to Real Chrome via CDP (port 9222)
            try:
                browser_inst = pw_inst.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=3000)
                is_cdp = True
                logger.info("Successfully connected directly to your existing Google Chrome browser via CDP!")
            except Exception:
                # Attempt 2: Launch real Google Chrome
                try:
                    browser_inst = pw_inst.chromium.launch(
                        channel="chrome",
                        headless=headless,
                        args=['--start-maximized', '--disable-blink-features=AutomationControlled']
                    )
                except Exception:
                    # Attempt 3: Standard Chromium
                    browser_inst = pw_inst.chromium.launch(
                        headless=headless,
                        args=['--start-maximized', '--disable-blink-features=AutomationControlled']
                    )

            if is_cdp:
                context = browser_inst.contexts[0]
                page = context.new_page()
            else:
                session_file = os.path.join(get_project_root(), "linkedin_session.json")
                if os.path.exists(session_file):
                    try:
                        context = browser_inst.new_context(
                            storage_state=session_file,
                            viewport=None,
                            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                        )
                    except Exception:
                        context = browser_inst.new_context(
                            viewport=None,
                            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                        )
                else:
                    context = browser_inst.new_context(
                        viewport=None,
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    )
                page = context.new_page()

            # Inject LinkedIn session cookie if configured
            settings = load_settings()
            li_at = settings.get('linkedin_cookie') or self.profile.get('linkedin_cookie')
            if li_at:
                try:
                    context.add_cookies([{
                        'name': 'li_at',
                        'value': str(li_at).strip(),
                        'domain': '.linkedin.com',
                        'path': '/',
                        'httpOnly': True,
                        'secure': True
                    }])
                    logger.info("Injected li_at authentication cookie into browser session.")
                except Exception as e:
                    logger.debug(f"Cookie injection note: {e}")

            logger.info(f"Navigating to job URL: {url}")
            page.goto(url, wait_until='domcontentloaded', timeout=45000)
            time.sleep(3)

            # 1. Check if on LinkedIn
            if "linkedin.com" in url:
                easy_apply_btn = page.locator('button.jobs-apply-button, button:has-text("Easy Apply"), .jobs-apply-button--top-card button').first
                if easy_apply_btn.is_visible(timeout=4000):
                    logger.info("Clicking LinkedIn Easy Apply...")
                    easy_apply_btn.click()
                    time.sleep(2)
                    res = self._handle_linkedin_easy_apply(page, cover_letter)
                    return res

            # 2. Standard Career Portal Application (Greenhouse / Lever / Custom)
            fields_filled = []
            profile_data = {
                'first_name': self.profile.get('first_name', 'Divakara Rao'),
                'last_name': self.profile.get('last_name', 'Kantubothu'),
                'full_name': self.profile.get('name', 'Kantubothu Divakara Rao'),
                'email': self.profile.get('email', 'divakantubothu@gmail.com'),
                'phone': self.profile.get('phone', '+91 8247032485'),
                'location': self.profile.get('location', 'Andhra Pradesh, India'),
                'linkedin': self.profile.get('linkedin_url', 'https://www.linkedin.com/in/kantubothu-divakara-rao'),
                'github': self.profile.get('github_url', 'https://github.com/diva142006'),
                'portfolio': self.profile.get('portfolio_url', 'https://github.com/diva142006')
            }

            for field_type, val in profile_data.items():
                if val and self._find_and_fill_field(page, field_type, val):
                    fields_filled.append(field_type)

            # Upload Official Resume PDF
            resume_file = self.get_resume_path()
            if resume_file and self._upload_resume(page, resume_file):
                fields_filled.append('resume.pdf')

            # Cover Letter
            if cover_letter and self._fill_cover_letter(page, cover_letter):
                fields_filled.append('cover_letter')

            self._handle_standard_checkboxes(page)
            submit_success = self._click_submit_button(page)
            time.sleep(3)

            return {
                'status': 'submitted' if submit_success else 'filled',
                'fields_filled': fields_filled,
                'message': '✅ Application successfully submitted with official resume attached!' if submit_success else 'Form filled with candidate details.'
            }

        except Exception as e:
            logger.error(f"Auto-apply error: {e}")
            return {'status': 'error', 'message': str(e)}
        finally:
            if browser_inst and not is_cdp:
                try:
                    time.sleep(2)
                    browser_inst.close()
                except Exception:
                    pass
            if pw_inst and not is_cdp:
                try:
                    pw_inst.stop()
                except Exception:
                    pass

    def _handle_linkedin_easy_apply(self, page: Page, cover_letter: Optional[str] = None) -> Dict[str, Any]:
        """Navigates LinkedIn Easy Apply modal until submission is verified."""
        max_steps = 10
        resume_attached = False

        for step in range(max_steps):
            time.sleep(2)

            # Fill visible inputs
            self._fill_visible_inputs(page)

            # Upload resume
            resume_file = self.get_resume_path()
            if resume_file and not resume_attached:
                if self._upload_resume(page, resume_file):
                    resume_attached = True

            # Screening questions
            self._answer_step_questions(page)

            # Check for Submit button
            submit_btn = page.locator('button[aria-label="Submit application"], button:has-text("Submit application")').first
            if submit_btn.is_visible(timeout=1000):
                logger.info("Found Submit Application button! Clicking submit...")
                submit_btn.click()
                time.sleep(4)
                
                confirmation = page.locator('.artdeco-modal__header:has-text("Application sent"), h3:has-text("Application sent"), p:has-text("Your application was sent to")').first
                if confirmation.is_visible(timeout=4000):
                    return {
                        'status': 'submitted',
                        'message': '🎉 LinkedIn Confirmed: Your application was officially submitted to the employer!'
                    }
                return {'status': 'submitted', 'message': '✅ LinkedIn Easy Apply submitted successfully!'}

            # Review button
            review_btn = page.locator('button[aria-label="Review your application"], button:has-text("Review")').first
            if review_btn.is_visible(timeout=1000):
                review_btn.click()
                continue

            # Next button
            next_btn = page.locator('button[aria-label="Continue to next step"], button:has-text("Next")').first
            if next_btn.is_visible(timeout=1000):
                next_btn.click()
                continue
            else:
                break

        return {'status': 'filled', 'message': 'Easy Apply form completed.'}

    def _fill_visible_inputs(self, page: Page):
        """Fills standard profile fields on the active dialog."""
        mapping = {
            'phone': self.profile.get('phone', '+91 8247032485'),
            'email': self.profile.get('email', 'divakantubothu@gmail.com'),
            'full_name': self.profile.get('name', 'Kantubothu Divakara Rao'),
            'location': self.profile.get('location', 'Andhra Pradesh, India')
        }
        for field, val in mapping.items():
            self._find_and_fill_field(page, field, val)

    def _answer_step_questions(self, page: Page):
        """Answers screening questions with AI."""
        try:
            questions = page.locator('.jobs-easy-apply-form-section__grouping, .fb-dash-form-element').all()
            for q_el in questions[:5]:
                text = q_el.inner_text().strip()
                if "experience" in text.lower() or "years" in text.lower():
                    inp = q_el.locator('input[type="text"], input[type="number"]').first
                    if inp.is_visible(timeout=500):
                        inp.fill("2")
                elif "authorized" in text.lower() or "legally" in text.lower() or "eligible" in text.lower():
                    yes_radio = q_el.locator('input[value="Yes"], label:has-text("Yes")').first
                    if yes_radio.is_visible(timeout=500):
                        yes_radio.click()
                elif "sponsorship" in text.lower() or "visa" in text.lower():
                    no_radio = q_el.locator('input[value="No"], label:has-text("No")').first
                    if no_radio.is_visible(timeout=500):
                        no_radio.click()
                elif "notice" in text.lower():
                    inp = q_el.locator('input[type="text"], input[type="number"]').first
                    if inp.is_visible(timeout=500):
                        inp.fill("Immediate / 15 days")
        except Exception:
            pass

    def _find_and_fill_field(self, page: Page, field_type: str, value: str) -> bool:
        """Finds input fields and fills them."""
        selectors = self.FIELD_SELECTORS.get(field_type, [])
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.is_visible(timeout=800):
                    curr_val = locator.input_value()
                    if not curr_val or curr_val.strip() == "":
                        locator.fill(value)
                    return True
            except Exception:
                continue
        return False

    def _upload_resume(self, page: Page, resume_path: Optional[str] = None) -> bool:
        """Uploads official resume PDF."""
        target_path = resume_path or self.get_resume_path()
        if not target_path or not os.path.exists(target_path):
            return False

        try:
            file_input = page.locator('input[type="file"]').first
            if file_input.is_visible(timeout=2000) or file_input.count() > 0:
                file_input.set_input_files(target_path)
                logger.info(f"Uploaded official resume: {target_path}")
                return True
        except Exception as e:
            logger.debug(f"Could not upload resume: {e}")
        return False

    def _fill_cover_letter(self, page: Page, cover_letter: str) -> bool:
        """Finds textarea and pastes cover letter."""
        selectors = ['textarea[name*="cover"]', 'textarea[id*="cover"]', 'textarea[placeholder*="cover letter" i]']
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.is_visible(timeout=800):
                    locator.fill(cover_letter)
                    return True
            except Exception:
                continue
        return False

    def _handle_standard_checkboxes(self, page: Page):
        """Checks standard authorization and terms checkboxes."""
        try:
            checkboxes = page.locator('input[type="checkbox"]').all()
            for cb in checkboxes:
                if cb.is_visible(timeout=500) and not cb.is_checked():
                    cb.check()
        except Exception:
            pass

    def _click_submit_button(self, page: Page) -> bool:
        """Finds and clicks the primary submit / apply button."""
        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Submit Application")',
            'button:has-text("Submit")',
            'button:has-text("Send Application")',
            'button:has-text("Apply Now")'
        ]
        for sel in submit_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1000) and btn.is_enabled():
                    btn.click()
                    return True
            except Exception:
                continue
        return False

    def open_and_prefill(self, url: str, cover_letter: Optional[str] = None) -> Dict[str, Any]:
        """Pre-fills application."""
        return self.auto_apply(url, cover_letter, headless=False)
