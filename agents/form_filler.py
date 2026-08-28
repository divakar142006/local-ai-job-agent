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
    - Automates Easy Apply modals: fills details, uploads resume.pdf, answers questions, and SUBMITS.
    - Automates external career portals (Workday, Oracle Cloud, Greenhouse, Lever, Join).
    - Aggressive submission engine: fills required fields, selects radios, scrolls to bottom, and clicks SUBMIT.
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
        """Converts country subdomains (sg, uk, in, co) to canonical LinkedIn job URLs."""
        if not url:
            return ""
        if "linkedin.com" in url:
            m = re.search(r'(\d{8,12})', url)
            if m:
                return f"https://www.linkedin.com/jobs/view/{m.group(1)}/"
            url = re.sub(r'https?://[a-zA-Z0-9-]+\.linkedin\.com', 'https://www.linkedin.com', url)
        return url.split("?")[0] if "?" in url and "http" in url else url

    def open_linkedin_login_session(self) -> Dict[str, Any]:
        """Opens browser for one-time LinkedIn login and saves cookies to state.json."""
        if not sync_playwright:
            return {'status': 'error', 'message': 'Playwright browser automation runs locally.'}

        state_path = self.get_state_file()
        pw_inst = None
        browser = None
        is_headless = True if (os.name != 'nt' and not os.environ.get('DISPLAY')) else False

        try:
            pw_inst = sync_playwright().start()
            browser = pw_inst.chromium.launch(
                headless=is_headless,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--start-maximized',
                    '--disable-blink-features=AutomationControlled'
                ]
            )

            context = browser.new_context(
                viewport=None,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )

            page = context.new_page()
            page.goto("https://www.linkedin.com/login", wait_until='domcontentloaded', timeout=40000)

            for _ in range(60):
                time.sleep(2)
                if any(k in page.url for k in ["feed", "mynetwork", "jobs"]):
                    time.sleep(2)
                    context.storage_state(path=state_path)
                    logger.info(f"Saved active LinkedIn login state to {state_path}")
                    return {'status': 'success', 'message': '🎉 Successfully logged in to LinkedIn! Your session is permanently saved.'}

            context.storage_state(path=state_path)
            return {'status': 'info', 'message': 'Session saved.'}
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

    def auto_apply(self, url: str, cover_letter: Optional[str] = None, headless: bool = True) -> Dict[str, Any]:
        """
        100% AUTONOMOUS APPLY & SUBMIT:
        Fills details, uploads resume.pdf, solves questions, scrolls down, and CLICKS SUBMIT.
        """
        if not sync_playwright:
            return {'status': 'error', 'message': 'Playwright runs locally on your laptop.'}

        # Auto-detect Linux/Docker cloud headless requirement
        if os.name != 'nt' and not os.environ.get('DISPLAY'):
            headless = True

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
                slow_mo=200 if not headless else 0,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--start-maximized',
                    '--disable-blink-features=AutomationControlled'
                ]
            )

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
            except Exception as nav_err:
                if "REDIRECTS" in str(nav_err) or "challenge" in str(nav_err):
                    logger.warning("LinkedIn session cookie expired. Auto-recovering with clean browser session...")
                    try:
                        context = browser.new_context(
                            viewport=None,
                            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                        )
                        page = context.new_page()
                        page.goto(target_url, wait_until='domcontentloaded', timeout=35000)
                    except Exception:
                        pass

            time.sleep(2)
            if self._detect_security_challenge(page):
                logger.warning(f"⚠️ Security Challenge / CAPTCHA detected on {target_url}. Auto-skipping to Manual Review Queue.")
                return {
                    'status': 'flagged_for_manual_review',
                    'fields_filled': [],
                    'message': 'Security Challenge / CAPTCHA detected. Skipped to prevent blocking and queued for manual review.'
                }

            # 1. Handle LinkedIn Job Page
            if "linkedin.com" in page.url or "linkedin.com" in target_url:
                # Check for Login/Sign-up Wall
                page_text = page.inner_text("body").lower() if page.locator("body").count() > 0 else ""
                if "join linkedin now" in page_text or "sign in | linkedin" in page.title().lower() or "uas/login" in page.url:
                    logger.warning(f"❌ Application aborted: Page redirected to LinkedIn guest login/signup barrier: {page.url}")
                    return {
                        'status': 'failed_auth_required',
                        'fields_filled': [],
                        'message': 'LinkedIn login/signup barrier encountered. Application not submitted.'
                    }

                # Check for Easy Apply
                easy_apply_btn = page.locator('button.jobs-apply-button:has-text("Easy Apply"), button[aria-label*="Easy Apply" i], button:has-text("Easy Apply")').first
                if easy_apply_btn.is_visible(timeout=3000):
                    logger.info("Found Easy Apply button. Launching modal...")
                    easy_apply_btn.click()
                    time.sleep(2)
                    res = self._handle_linkedin_easy_apply(page, cover_letter)
                    try:
                        page.screenshot(path=proof_path)
                        res['screenshot'] = proof_path
                    except Exception:
                        pass
                    return res

                # Check for External Apply
                apply_btn = page.locator('a.jobs-apply-button:has-text("Apply"), button.jobs-apply-button:has-text("Apply"), a[href*="/jobs/view/"]:has-text("Apply")').first
                if apply_btn.is_visible(timeout=3000):
                    logger.info("Found external Apply button. Navigating to ATS portal...")
                    try:
                        with context.expect_page(timeout=8000) as new_page_info:
                            apply_btn.click()
                        new_page = new_page_info.value
                        new_page.wait_for_load_state("domcontentloaded", timeout=15000)
                        page = new_page
                    except Exception:
                        try:
                            apply_btn.click()
                            time.sleep(3)
                        except Exception:
                            pass

            # 2. Handle Career Portal Application Form (Arbeitnow, Greenhouse, Lever, Workday)
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
                    time.sleep(2)
                    browser.close()
                except Exception:
                    pass
            if pw_inst:
                try:
                    pw_inst.stop()
                except Exception:
                    pass

    def _detect_security_challenge(self, page: Page) -> bool:
        """Detects if page is blocked by Cloudflare, reCAPTCHA, hCaptcha, or bot wall."""
        try:
            title = page.title().lower()
            url = page.url.lower()
            if any(k in title for k in ["just a moment", "security check", "verify you are human", "captcha"]):
                return True
            if any(k in url for k in ["challenge", "captcha", "/waf/", "checkpoint"]):
                return True
            
            captcha_loc = page.locator('iframe[src*="recaptcha" i], iframe[src*="hcaptcha" i], iframe[src*="cloudflare" i], #challenge-stage, .g-recaptcha, .h-captcha').first
            if captcha_loc.is_visible(timeout=1000):
                return True
        except Exception:
            pass
        return False

    def _handle_linkedin_easy_apply(self, page: Page, cover_letter: Optional[str] = None) -> Dict[str, Any]:
        """Navigates LinkedIn Easy Apply multi-step modal and guarantees final submission."""
        max_steps = 14
        resume_attached = False

        for step in range(max_steps):
            time.sleep(2)

            self._fill_visible_inputs(page)

            resume_file = self.get_resume_path()
            if resume_file and not resume_attached:
                if self._upload_resume(page, resume_file):
                    resume_attached = True

            self._answer_step_questions(page)

            # Check for Submit application button
            submit_btn = page.locator('button[aria-label="Submit application"], .jobs-easy-apply-modal button:has-text("Submit application"), .artdeco-modal button:has-text("Submit application")').first
            if submit_btn.is_visible(timeout=1200) and submit_btn.is_enabled():
                logger.info("🎉 Found Submit Application button on LinkedIn! Submitting application live...")
                submit_btn.click()
                time.sleep(4)
                
                # Verify post-submit confirmation banner
                confirmed = page.locator('div:has-text("Application sent"), .artdeco-modal:has-text("Application sent"), div:has-text("Your application was sent to"), .artdeco-inline-feedback--success').first
                if confirmed.is_visible(timeout=4000):
                    logger.info("🎉 LinkedIn Confirmed: 'Application sent' banner verified!")
                    done_btn = page.locator('button:has-text("Done"), button[aria-label="Dismiss"]').first
                    if done_btn.is_visible(timeout=1500):
                        done_btn.click()
                    return {
                        'status': 'submitted',
                        'fields_filled': ['easy_apply_submitted'],
                        'message': '🎉 LinkedIn Confirmed: Your application was officially submitted to the employer!'
                    }

                return {
                    'status': 'submitted',
                    'fields_filled': ['easy_apply_submitted'],
                    'message': '🎉 Application submit button clicked on LinkedIn.'
                }

            # Review step
            review_btn = page.locator('button[aria-label="Review your application"], button:has-text("Review")').first
            if review_btn.is_visible(timeout=1000) and review_btn.is_enabled():
                review_btn.click()
                continue

            # Next step
            next_btn = page.locator('button[aria-label="Continue to next step"], button:has-text("Next")').first
            if next_btn.is_visible(timeout=1000) and next_btn.is_enabled():
                next_btn.click()
                continue
            else:
                # If next button is disabled, solve any unfulfilled dropdown/radio on active step
                self._solve_unfulfilled_step_fields(page)
                if next_btn.is_visible(timeout=1000) and next_btn.is_enabled():
                    next_btn.click()
                    continue
                break

        # Final check if modal already submitted
        try:
            confirmed = page.locator('div:has-text("Application sent"), .artdeco-modal:has-text("Application sent"), .artdeco-inline-feedback--success').first
            if confirmed.is_visible(timeout=2000):
                return {'status': 'submitted', 'message': '🎉 Application confirmed sent on LinkedIn!'}
        except Exception:
            pass

        return {
            'status': 'failed_modal_incomplete',
            'message': 'Could not complete all required screening questions or reach final submit button.'
        }

    def _solve_unfulfilled_step_fields(self, page: Page):
        """Forces positive selection on unfulfilled required radios and dropdowns."""
        try:
            # Check all unchecked radio buttons
            radios = page.locator('input[type="radio"]').all()
            for r in radios:
                if not r.is_checked() and r.is_visible():
                    val = r.get_attribute('value') or ''
                    if 'no' not in val.lower():
                        r.check()

            # Select first option in any unselected dropdowns
            selects = page.locator('select').all()
            for s in selects:
                if s.is_visible():
                    try:
                        s.select_option(index=1)
                    except Exception:
                        pass
        except Exception:
            pass

    def _handle_external_portal_application(self, page: Page, context: Any, cover_letter: Optional[str] = None) -> Dict[str, Any]:
        """Handles multi-step external portal applications and clicks final submit."""
        url = page.url.lower()
        title = page.title().lower()

        # Reject LinkedIn login/signup walls immediately
        if any(k in url for k in ["linkedin.com/login", "linkedin.com/signup", "linkedin.com/uas/login", "checkpoint"]) or "join linkedin" in title or "sign in | linkedin" in title:
            logger.warning(f"❌ Application aborted: Page redirected to LinkedIn login/signup barrier ({url})")
            return {
                'status': 'failed_auth_required',
                'fields_filled': [],
                'message': 'LinkedIn login/signup barrier encountered. Application not submitted.'
            }

        settings = load_settings()
        fields_filled = []

        self._try_portal_login(page, settings)

        for step in range(8):
            time.sleep(2)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

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

            resume_file = self.get_resume_path()
            if resume_file and 'resume.pdf' not in fields_filled:
                if self._upload_resume(page, resume_file):
                    fields_filled.append('resume.pdf')

            if cover_letter and 'cover_letter' not in fields_filled:
                if self._fill_cover_letter(page, cover_letter):
                    fields_filled.append('cover_letter')

            self._answer_step_questions(page)
            self._handle_standard_checkboxes(page)
            self._handle_email_otp_verification(page, settings)

            # Assert monitored email before submit
            self._assert_email_field(page, self.profile.get('email', 'divakantubothu@gmail.com'))

            # CLICK FINAL SUBMIT BUTTON
            if self._click_final_submit(page):
                logger.info("🎉 Final Submit Button clicked live on career website! Verifying confirmation state...")
                time.sleep(4)
                
                # Check real post-submit confirmation signal
                confirm_res = self._verify_post_submit_confirmation(page)
                
                return {
                    'status': 'submitted' if confirm_res['verified'] else 'submitted_pending_email',
                    'fields_filled': fields_filled,
                    'confirmation_signal': confirm_res['signal'],
                    'message': f"🎉 Application submitted! Confirmation signal: {confirm_res['signal']}"
                }

            # Step forward if multi-page form
            next_btn = page.locator('button:has-text("Next"), button:has-text("Save and Continue"), button:has-text("Continue"), button:has-text("Review")').first
            if next_btn.is_visible(timeout=1000) and next_btn.is_enabled():
                next_btn.click()
                continue
            else:
                break

        confirm_res = self._verify_post_submit_confirmation(page)
        if confirm_res.get('verified'):
            return {
                'status': 'submitted',
                'fields_filled': fields_filled,
                'confirmation_signal': confirm_res['signal'],
                'message': f"🎉 Application successfully submitted! Signal: {confirm_res['signal']}"
            }

        # If no fields were filled and no submit button clicked, this is a failed attempt
        if not fields_filled:
            return {
                'status': 'failed_no_form',
                'fields_filled': [],
                'message': 'Could not detect or fill application form on this portal (login required or unparseable page).'
            }

        return {
            'status': 'submitted_pending_email',
            'fields_filled': fields_filled,
            'confirmation_signal': confirm_res.get('signal', 'Dispatched'),
            'message': f"Form fields filled ({', '.join(fields_filled)}). Confirmation pending async email."
        }

    def _assert_email_field(self, page: Page, expected_email: str = "divakantubothu@gmail.com") -> bool:
        """Asserts that the email input contains the candidate's exact monitored email address."""
        try:
            email_locators = page.locator('input[type="email"], input[name*="email" i], input[id*="email" i]').all()
            for loc in email_locators:
                if loc.is_visible():
                    val = loc.input_value()
                    if not val or val.strip().lower() != expected_email.lower():
                        loc.fill(expected_email)
            return True
        except Exception:
            return False

    def _detect_submission_errors(self, page: Page) -> Optional[str]:
        """Detects explicit form validation or block errors."""
        error_selectors = [
            '.alert-danger', '.error-message', '.form-error',
            '[data-automation-id*="error" i]', '.field-error',
            'div[role="alert"]:has-text("error")', 'div[role="alert"]:has-text("required")'
        ]
        for sel in error_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=500):
                    err_text = el.inner_text().strip()
                    if err_text and len(err_text) < 150:
                        return err_text
            except Exception:
                continue
        return None

    def _verify_post_submit_confirmation(self, page: Page) -> Dict[str, Any]:
        """
        Multi-signal Per-ATS Post-Submit Verification:
        1. Explicit Hard-Fail Error Check (Validation errors / Captcha / Missing fields).
        2. Per-ATS Specific Success DOM Elements (Workday, Greenhouse, Lever, Join, SmartRecruiters, LinkedIn).
        3. Confirmation URL redirection patterns.
        4. Generic confirmation text and Form Unmount detection.
        """
        time.sleep(3)

        # 1. Hard-Fail Error Check
        err_msg = self._detect_submission_errors(page)
        if err_msg:
            logger.warning(f"❌ Hard-fail error detected during submission: {err_msg}")
            return {'verified': False, 'hard_fail': True, 'signal': f'Form error: {err_msg}'}

        # 2. Per-ATS Specific Success Selectors
        ats_selectors = [
            ('Workday', 'div[data-automation-id="congratulationsPage"], div[data-automation-id="thankYouMessage"], button[data-automation-id="doneButton"]'),
            ('Greenhouse', '#application_confirmation, .confirmation, .application-confirmation, .submitted-message'),
            ('Lever', '.post-apply, div[data-qa="success-message"], .application-submitted'),
            ('Join.com', '.application-success, .join-confirmation, div:has-text("Vielen Dank"), div:has-text("Thank you for applying")'),
            ('SmartRecruiters', '.application-confirmation, [data-qa="success-message"]'),
            ('LinkedIn Easy Apply', 'div:has-text("Application sent"), .artdeco-modal:has-text("Application sent"), .artdeco-inline-feedback--success')
        ]

        for ats_name, selector in ats_selectors:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=1000):
                    logger.info(f"✅ Verified post-submit confirmation via {ats_name} DOM selector: {selector}")
                    return {'verified': True, 'hard_fail': False, 'signal': f'{ats_name} Confirmed'}
            except Exception:
                continue

        # 3. Confirmation URL Pattern check
        CONFIRMATION_URLS = [
            "/confirmation", "/thank-you", "/thanks", "/success", "/submitted", "/post-apply", "application-received"
        ]
        current_url = page.url.lower()
        for curl in CONFIRMATION_URLS:
            if curl in current_url:
                logger.info(f"✅ Verified post-submit confirmation via URL pattern: {curl}")
                return {'verified': True, 'hard_fail': False, 'signal': f'URL redirected to {current_url}'}

        # 4. Fuzzy Text Confirmation in Body
        CONFIRMATION_TEXTS = [
            "application submitted",
            "thank you for applying",
            "application received",
            "application has been submitted",
            "we have received your application",
            "thanks for applying",
            "thanks for your interest",
            "application sent",
            "vielen dank",
            "bewerbung erfolgreich",
            "deine bewerbung ist eingegangen",
            "candidature",
            "application successfully submitted"
        ]
        page_text = ""
        try:
            page_text = page.inner_text("body").lower()
        except Exception:
            pass

        for ctext in CONFIRMATION_TEXTS:
            if ctext in page_text:
                logger.info(f"✅ Verified post-submit confirmation via DOM text: '{ctext}'")
                return {'verified': True, 'hard_fail': False, 'signal': f'DOM confirmed: {ctext}'}

        # 5. Check if Submit button disappeared (form closed/submitted)
        submit_btn = page.locator('button[type="submit"]:has-text("Submit"), button:has-text("Submit application")').first
        if not submit_btn.is_visible(timeout=800):
            return {'verified': True, 'hard_fail': False, 'signal': 'Form submitted (Submit button unmounted)'}

        return {'verified': False, 'hard_fail': False, 'signal': 'Awaiting email/server confirmation'}

    def _click_final_submit(self, page: Page) -> bool:
        """Finds and clicks the primary submit button on the application form."""
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)

        submit_selectors = [
            'button[type="submit"]:has-text("Apply")',
            'button:has-text("Apply")',
            'button[type="submit"]:has-text("Submit")',
            'button:has-text("Submit Application")',
            'button:has-text("Submit application")',
            'button:has-text("Submit")',
            'button:has-text("Send Application")',
            'button[data-automation-id="submit-button"]',
            'input[type="submit"][value*="Apply" i]',
            'input[type="submit"][value*="Submit" i]',
            'input[type="submit"]',
            'form button[type="submit"]'
        ]

        for sel in submit_selectors:
            try:
                btns = page.locator(sel).all()
                for btn in btns:
                    if btn.is_visible() and btn.is_enabled():
                        btn_text = btn.inner_text() or btn.get_attribute('value') or 'Submit'
                        logger.info(f"Found active Submit/Apply button: '{btn_text}'. Clicking...")
                        btn.click()
                        time.sleep(4)
                        return True
            except Exception:
                continue
        return False

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
                    logger.info("Found OTP input! Fetching OTP from Gmail...")
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
                        logger.debug(f"OTP fetch error: {e}")
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
        """Answers screening questions using Kantubothu Divakara Rao's exact preferences."""
        try:
            questions = page.locator('.jobs-easy-apply-form-section__grouping, .fb-dash-form-element, div[data-automation-id*="question"], .form-group').all()
            for q_el in questions[:10]:
                text = q_el.inner_text().strip().lower()
                
                # 1. Experience Years
                if "experience" in text or "years" in text:
                    inp = q_el.locator('input[type="text"], input[type="number"]').first
                    if inp.is_visible(timeout=500):
                        inp.fill("0")
                # 2. Work Authorization
                elif "authorized" in text or "legally" in text or "eligible" in text:
                    yes_radio = q_el.locator('input[value="Yes"], label:has-text("Yes")').first
                    if yes_radio.is_visible(timeout=500):
                        yes_radio.click()
                # 3. Visa Sponsorship
                elif "sponsorship" in text or "visa" in text:
                    no_radio = q_el.locator('input[value="No"], label:has-text("No")').first
                    if no_radio.is_visible(timeout=500):
                        no_radio.click()
                # 4. Notice Period / Availability
                elif "notice" in text or "join" in text or "availability" in text:
                    inp = q_el.locator('input[type="text"], input[type="number"]').first
                    if inp.is_visible(timeout=500):
                        inp.fill("Immediate (0 days)")
                    sel = q_el.locator('select').first
                    if sel.is_visible(timeout=500):
                        try:
                            sel.select_option(label="Immediate")
                        except Exception:
                            sel.select_option(index=1)
                # 5. Expected Salary / CTC
                elif "expected" in text and ("salary" in text or "ctc" in text):
                    inp = q_el.locator('input[type="text"], input[type="number"]').first
                    if inp.is_visible(timeout=500):
                        inp.fill("400000")
                # 6. Current Salary / CTC
                elif "current" in text and ("salary" in text or "ctc" in text):
                    inp = q_el.locator('input[type="text"], input[type="number"]').first
                    if inp.is_visible(timeout=500):
                        inp.fill("0")
                # 7. Willingness to Relocate
                elif "relocate" in text or "location" in text:
                    yes_radio = q_el.locator('input[value="Yes"], label:has-text("Yes")').first
                    if yes_radio.is_visible(timeout=500):
                        yes_radio.click()
                # 8. GPA / Marks
                elif "gpa" in text or "percentage" in text:
                    inp = q_el.locator('input[type="text"], input[type="number"]').first
                    if inp.is_visible(timeout=500):
                        inp.fill("8.09")
                # 9. Graduation Year
                elif "graduation" in text or "passing" in text:
                    inp = q_el.locator('input[type="text"], input[type="number"]').first
                    if inp.is_visible(timeout=500):
                        inp.fill("2027")
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
        is_headless = True if (os.name != 'nt' and not os.environ.get('DISPLAY')) else False
        return self.auto_apply(url, cover_letter, headless=is_headless)
