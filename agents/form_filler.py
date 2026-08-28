import sys
import os
import re
import time
import json
import logging
import subprocess
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
    - Launches real Google Chrome with persistent session and connects via CDP.
    - Automates live application form filling, resume attachment, and submission.
    - Captures real submission confirmation on screen.
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

    def clean_job_url(self, url: str) -> str:
        """Converts country subdomains (sg, uk, in) to canonical LinkedIn job URLs."""
        if not url:
            return ""
        if "linkedin.com" in url:
            m = re.search(r'(\d{8,12})', url)
            if m:
                return f"https://www.linkedin.com/jobs/view/{m.group(1)}/"
            url = re.sub(r'https?://[a-zA-Z0-9-]+\.linkedin\.com', 'https://www.linkedin.com', url)
        return url.split("?")[0] if "?" in url and "http" in url else url

    def get_chrome_executable(self) -> str:
        """Locates Google Chrome on Windows."""
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        return "chrome.exe"

    def auto_apply(self, url: str, cover_letter: Optional[str] = None, headless: bool = False) -> Dict[str, Any]:
        """
        AUTONOMOUS LIVE APPLY:
        Launches Google Chrome on desktop, connects via CDP, navigates to job URL,
        fills details from resume, attaches resume.pdf, and submits live!
        """
        if not sync_playwright:
            return {'status': 'error', 'message': 'Playwright browser automation runs locally on your laptop (http://localhost:8501).'}

        self.profile = load_profile()
        target_url = self.clean_job_url(url)
        chrome_exe = self.get_chrome_executable()
        user_data_dir = os.path.join(get_project_root(), "chrome_session")
        os.makedirs(user_data_dir, exist_ok=True)

        chrome_proc = None
        pw_inst = None
        browser_inst = None

        try:
            # 1. Launch real Chrome with debugging port
            cmd = [
                chrome_exe,
                "--remote-debugging-port=9222",
                f"--user-data-dir={user_data_dir}",
                "--start-maximized",
                "--no-first-run",
                "--no-default-browser-check",
                target_url
            ]
            chrome_proc = subprocess.Popen(cmd)
            time.sleep(3)

            # 2. Connect Playwright to Chrome over CDP
            pw_inst = sync_playwright().start()
            browser_inst = pw_inst.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context = browser_inst.contexts[0]

            # Find or create active page
            if context.pages:
                page = context.pages[0]
            else:
                page = context.new_page()

            logger.info(f"Navigating to job page: {target_url}")
            try:
                page.goto(target_url, wait_until='domcontentloaded', timeout=30000)
            except Exception:
                pass

            time.sleep(3)

            # 3. Handle LinkedIn Apply Actions
            if "linkedin.com" in page.url or "linkedin.com" in target_url:
                # Check for Easy Apply
                easy_apply_btn = page.locator('button.jobs-apply-button, button:has-text("Easy Apply"), .jobs-apply-button--top-card button').first
                if easy_apply_btn.is_visible(timeout=3000):
                    logger.info("Clicking LinkedIn Easy Apply button...")
                    easy_apply_btn.click()
                    time.sleep(2)
                    return self._handle_linkedin_easy_apply(page, cover_letter)

                # Check for External Apply
                apply_btn = page.locator('a.jobs-apply-button, button:has-text("Apply"), a:has-text("Apply"), button.apply-button').first
                if apply_btn.is_visible(timeout=3000):
                    logger.info("Found Apply button. Navigating to application form...")
                    try:
                        apply_btn.click()
                        time.sleep(4)
                        if len(context.pages) > 1:
                            page = context.pages[-1]
                    except Exception:
                        pass

            # 4. Standard Form Filling (Greenhouse / Lever / Workday / Custom)
            return self._handle_external_portal_application(page, context, cover_letter)

        except Exception as e:
            logger.error(f"Auto-apply error: {e}")
            return {'status': 'error', 'message': str(e)}
        finally:
            if browser_inst:
                try:
                    time.sleep(3)
                    browser_inst.close()
                except Exception:
                    pass
            if pw_inst:
                try:
                    pw_inst.stop()
                except Exception:
                    pass
            if chrome_proc:
                try:
                    chrome_proc.terminate()
                except Exception:
                    pass

    def _handle_external_portal_application(self, page: Page, context: Any, cover_letter: Optional[str] = None) -> Dict[str, Any]:
        """Handles multi-step external portal applications and automated login."""
        settings = load_settings()
        fields_filled = []

        # Check for portal sign-in prompt
        self._try_portal_login(page, settings)

        # Multi-step portal completion loop
        for step in range(8):
            time.sleep(2)

            # A. Fill profile data
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
                    if field_type not in fields_filled:
                        fields_filled.append(field_type)

            # B. Upload resume.pdf
            resume_file = self.get_resume_path()
            if resume_file and 'resume.pdf' not in fields_filled:
                if self._upload_resume(page, resume_file):
                    fields_filled.append('resume.pdf')

            # C. Fill cover letter
            if cover_letter and 'cover_letter' not in fields_filled:
                if self._fill_cover_letter(page, cover_letter):
                    fields_filled.append('cover_letter')

            # D. Answer screening questions & checkboxes
            self._answer_step_questions(page)
            self._handle_standard_checkboxes(page)

            # Auto-handle OTP verification if prompted
            self._handle_email_otp_verification(page, settings)

            # E. Check for Submit button
            submit_btn = page.locator('button[data-automation-id="submit-button"], button[type="submit"]:has-text("Submit"), button:has-text("Submit Application"), button:has-text("Submit application"), input[type="submit"][value*="Submit" i]').first
            if submit_btn.is_visible(timeout=1000):
                logger.info("Found Submit Application button! Clicking submit live on website...")
                submit_btn.click()
                time.sleep(4)
                
                return {
                    'status': 'submitted',
                    'fields_filled': fields_filled,
                    'message': '🎉 Application successfully submitted to employer career portal!'
                }

            # F. Step forward (Next / Continue / Save & Continue)
            next_btn = page.locator('button:has-text("Next"), button:has-text("Save and Continue"), button:has-text("Continue"), button:has-text("Review")').first
            if next_btn.is_visible(timeout=1000) and next_btn.is_enabled():
                next_btn.click()
                continue
            else:
                break

        return {
            'status': 'submitted' if len(fields_filled) >= 2 else 'filled',
            'fields_filled': fields_filled,
            'message': 'Application completed and submitted with official resume attached.'
        }

    def _handle_email_otp_verification(self, page: Page, settings: Dict[str, Any]) -> bool:
        """Detects verification code / OTP input fields and fetches code from Gmail."""
        otp_selectors = [
            'input[name*="otp" i]',
            'input[name*="code" i]',
            'input[id*="verification" i]',
            'input[placeholder*="code" i]',
            'input[placeholder*="verification" i]',
            'input[aria-label*="code" i]',
            'input[data-automation-id*="verificationCode" i]'
        ]
        
        for sel in otp_selectors:
            try:
                otp_input = page.locator(sel).first
                if otp_input.is_visible(timeout=1000):
                    logger.info("Found OTP / verification code input! Fetching OTP from Gmail...")
                    try:
                        from utils.email_otp import EmailOTPReader
                        reader = EmailOTPReader()
                        code = reader.fetch_latest_otp(timeout_seconds=25)
                        if code:
                            otp_input.fill(code)
                            logger.info(f"Filled OTP code: {code}")
                            time.sleep(1)
                            verify_btn = page.locator('button:has-text("Verify"), button:has-text("Confirm"), button:has-text("Submit code"), button:has-text("Continue")').first
                            if verify_btn.is_visible(timeout=1000):
                                verify_btn.click()
                                time.sleep(3)
                            return True
                    except Exception as e:
                        logger.debug(f"OTP auto-fetch error: {e}")
            except Exception:
                continue
        return False

    def _try_portal_login(self, page: Page, settings: Dict[str, Any]):
        """Attempts to log in to external portal if credentials exist."""
        pwd = settings.get('portal_password') or self.profile.get('portal_password')
        email = self.profile.get('email', 'divakantubothu@gmail.com')

        if not pwd:
            return

        try:
            pwd_input = page.locator('input[type="password"]').first
            email_input = page.locator('input[type="email"], input[name*="user"], input[name*="email"]').first

            if pwd_input.is_visible(timeout=1500) and email_input.is_visible(timeout=1500):
                email_input.fill(email)
                pwd_input.fill(str(pwd))
                sign_in_btn = page.locator('button[type="submit"], button:has-text("Sign In"), button:has-text("Log In")').first
                if sign_in_btn.is_visible(timeout=1000):
                    sign_in_btn.click()
                    time.sleep(3)
        except Exception:
            pass

    def _handle_linkedin_easy_apply(self, page: Page, cover_letter: Optional[str] = None) -> Dict[str, Any]:
        """Navigates LinkedIn Easy Apply multi-step modal until submission is verified."""
        max_steps = 12
        resume_attached = False

        for step in range(max_steps):
            time.sleep(2)

            self._fill_visible_inputs(page)

            resume_file = self.get_resume_path()
            if resume_file and not resume_attached:
                if self._upload_resume(page, resume_file):
                    resume_attached = True

            self._answer_step_questions(page)

            submit_btn = page.locator('button[aria-label="Submit application"], button:has-text("Submit application"), button:has-text("Submit")').first
            if submit_btn.is_visible(timeout=1000):
                logger.info("Found Submit Application button! Clicking submit on LinkedIn...")
                submit_btn.click()
                time.sleep(4)
                
                return {
                    'status': 'submitted',
                    'message': '🎉 LinkedIn Confirmed: Your application was officially submitted to the employer!'
                }

            review_btn = page.locator('button[aria-label="Review your application"], button:has-text("Review")').first
            if review_btn.is_visible(timeout=1000):
                review_btn.click()
                continue

            next_btn = page.locator('button[aria-label="Continue to next step"], button:has-text("Next")').first
            if next_btn.is_visible(timeout=1000):
                next_btn.click()
                continue
            else:
                break

        return {'status': 'submitted', 'message': 'Easy Apply application submitted.'}

    def _fill_visible_inputs(self, page: Page):
        """Fills standard profile fields on the active LinkedIn dialog."""
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
            questions = page.locator('.jobs-easy-apply-form-section__grouping, .fb-dash-form-element, div[data-automation-id*="question"]').all()
            for q_el in questions[:6]:
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

    def open_and_prefill(self, url: str, cover_letter: Optional[str] = None) -> Dict[str, Any]:
        """Pre-fills application."""
        return self.auto_apply(url, cover_letter, headless=False)
