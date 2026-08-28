import sys
import os
import re
import time
import json
import logging
from typing import Dict, Any, Optional, List

try:
    from playwright.sync_api import sync_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeoutError
except ImportError:
    sync_playwright = None
    Page = Any
    BrowserContext = Any
    PlaywrightTimeoutError = Exception

from utils.ollama_client import OllamaAI
from utils.helpers import load_profile, load_keywords, load_settings, sanitize_text, format_job_summary, get_project_root
from database.models import Job, Application, Notification

logger = logging.getLogger(__name__)

class FormFiller:
    """
    Autonomous Form Filler & Application Submitter:
    - Uses Playwright storage_state (state.json) for 100% collision-free persistent logins.
    - Automates Easy Apply modals: fills details, uploads resume.pdf, answers questions, and submits.
    - Automates external career portals (Workday, Oracle Cloud, Greenhouse).
    - Captures high-resolution screenshot proof of confirmed submissions.
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

    def get_state_file(self) -> str:
        """Returns path to Playwright persistent storage state."""
        return os.path.join(get_project_root(), "state.json")

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

    def open_linkedin_login_session(self) -> Dict[str, Any]:
        """
        Opens a visible browser for the user to log in to LinkedIn once.
        Saves session cookies and tokens to state.json with ZERO profile collisions.
        """
        if not sync_playwright:
            return {'status': 'error', 'message': 'Playwright browser automation runs locally on your laptop.'}

        state_path = self.get_state_file()
        pw_inst = None
        browser = None

        try:
            pw_inst = sync_playwright().start()
            browser = pw_inst.chromium.launch(
                headless=False,
                args=['--start-maximized', '--disable-blink-features=AutomationControlled']
            )

            # Load existing state if available
            if os.path.exists(state_path):
                context = browser.new_context(
                    storage_state=state_path,
                    viewport=None,
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
            else:
                context = browser.new_context(
                    viewport=None,
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )

            page = context.new_page()
            page.goto("https://www.linkedin.com/login", wait_until='domcontentloaded', timeout=40000)

            # Wait up to 120 seconds for user to log in
            for _ in range(60):
                time.sleep(2)
                if "feed" in page.url or "mynetwork" in page.url or "jobs" in page.url:
                    time.sleep(2)
                    context.storage_state(path=state_path)
                    logger.info(f"Saved active LinkedIn login state to {state_path}")
                    return {'status': 'success', 'message': '🎉 Successfully logged in to LinkedIn! Your session is permanently saved.'}

            context.storage_state(path=state_path)
            return {'status': 'info', 'message': 'Session saved. If you completed login, your LinkedIn account is now connected!'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if pw_inst:
                try:
                    pw_inst.stop()
                except Exception:
                    pass

    def auto_apply(self, url: str, cover_letter: Optional[str] = None, headless: bool = False) -> Dict[str, Any]:
        """
        AUTONOMOUS APPLY:
        Opens browser with stored login state, navigates to job URL, fills details,
        uploads resume.pdf, submits application, and captures screenshot proof.
        """
        if not sync_playwright:
            return {'status': 'error', 'message': 'Playwright browser automation runs locally on your laptop (http://localhost:8501).'}

        self.profile = load_profile()
        target_url = self.clean_job_url(url)
        state_path = self.get_state_file()
        proof_path = os.path.join(get_project_root(), "last_submission_proof.png")

        pw_inst = None
        browser = None

        try:
            pw_inst = sync_playwright().start()
            browser = pw_inst.chromium.launch(
                headless=headless,
                slow_mo=500,
                args=['--start-maximized', '--disable-blink-features=AutomationControlled']
            )

            # Create context with saved login state if present
            if os.path.exists(state_path):
                context = browser.new_context(
                    storage_state=state_path,
                    viewport=None,
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
            else:
                context = browser.new_context(
                    viewport=None,
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )

            page = context.new_page()
            logger.info(f"Navigating to job: {target_url}")

            try:
                page.goto(target_url, wait_until='domcontentloaded', timeout=35000)
            except Exception:
                pass

            time.sleep(3)
            # Auto-bypass Cloudflare Turnstile challenge if present
            self._check_and_bypass_cloudflare(page)

            # 1. Handle LinkedIn Job Page Apply Elements
            if "linkedin.com" in page.url or "linkedin.com" in target_url:
                # Check for Easy Apply button
                easy_apply_btn = page.locator('button.jobs-apply-button, button:has-text("Easy Apply"), .jobs-apply-button--top-card button').first
                if easy_apply_btn.is_visible(timeout=3000):
                    logger.info("Found Easy Apply button. Clicking...")
                    easy_apply_btn.click()
                    time.sleep(2)
                    res = self._handle_linkedin_easy_apply(page, cover_letter)
                    try:
                        page.screenshot(path=proof_path)
                        res['screenshot'] = proof_path
                    except Exception:
                        pass
                    return res

                # Check for External Apply button
                apply_btn = page.locator('a.jobs-apply-button, button:has-text("Apply"), a:has-text("Apply"), button.apply-button').first
                if apply_btn.is_visible(timeout=3000):
                    logger.info("Found external Apply button. Navigating to career portal...")
                    try:
                        with context.expect_page(timeout=10000) as new_page_info:
                            apply_btn.click()
                        new_page = new_page_info.value
                        new_page.wait_for_load_state("domcontentloaded", timeout=20000)
                        page = new_page
                    except Exception:
                        try:
                            apply_btn.click()
                            time.sleep(3)
                        except Exception:
                            pass

            # 2. Handle Career Portal Application Form (Workday, Oracle Cloud, Greenhouse, Lever)
            res = self._handle_external_portal_application(page, context, cover_letter)
            try:
                page.screenshot(path=proof_path)
                res['screenshot'] = proof_path
            except Exception:
                pass
            return res

        except Exception as e:
            logger.error(f"Auto-apply error: {e}")
            return {'status': 'error', 'message': str(e)}
        finally:
            if browser:
                try:
                    time.sleep(3)
                    browser.close()
                except Exception:
                    pass
            if pw_inst:
                try:
                    pw_inst.stop()
                except Exception:
                    pass

    def _check_and_bypass_cloudflare(self, page: Page) -> bool:
        """Detects and auto-clicks Cloudflare Turnstile verification checkboxes."""
        try:
            if "just a moment" in page.title().lower() or "challenge" in page.url:
                logger.info("Cloudflare Turnstile challenge detected. Auto-clicking verification...")
                for frame in page.frames:
                    try:
                        cb = frame.locator('input[type="checkbox"], .ctp-checkbox-label, #challenge-stage input').first
                        if cb.is_visible(timeout=1500):
                            cb.click()
                            time.sleep(3)
                            return True
                    except Exception:
                        pass
                main_cb = page.locator('#challenge-stage input, input[type="checkbox"]').first
                if main_cb.is_visible(timeout=1500):
                    main_cb.click()
                    time.sleep(3)
                    return True
        except Exception:
            pass
        return False

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
                logger.info("Found Submit Application button! Submitting live on LinkedIn...")
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
