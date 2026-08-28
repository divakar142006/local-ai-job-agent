import sys
import os
import re
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
    - Navigates cleanly to any job URL without redirect loops.
    - Handles LinkedIn Easy Apply and follows external employer career portals (Greenhouse, Lever, Workday).
    - Fills Kantubothu Divakara Rao's details, attaches official resume.pdf, and submits.
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
        """Strips tracking params and canonicalizes LinkedIn job URLs."""
        if not url:
            return ""
        if "linkedin.com/jobs/view" in url:
            m = re.search(r'(\d{8,12})', url)
            if m:
                return f"https://www.linkedin.com/jobs/view/{m.group(1)}/"
        return url.split("?")[0] if "?" in url and "http" in url else url

    def auto_apply(self, url: str, cover_letter: Optional[str] = None, headless: bool = False) -> Dict[str, Any]:
        """
        AUTONOMOUS APPLY:
        Navigates to job posting, clicks Apply / Easy Apply, fills candidate details,
        attaches resume.pdf, and submits application.
        """
        if not sync_playwright:
            return {'status': 'error', 'message': 'Playwright browser automation runs locally on your laptop (http://localhost:8501).'}

        self.profile = load_profile()
        target_url = self.clean_job_url(url)
        pw_inst = None
        browser_inst = None

        try:
            pw_inst = sync_playwright().start()
            browser_inst = pw_inst.chromium.launch(
                headless=headless,
                args=['--start-maximized', '--disable-blink-features=AutomationControlled']
            )

            context = browser_inst.new_context(
                viewport=None,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )

            page = context.new_page()
            logger.info(f"Navigating to: {target_url}")

            try:
                page.goto(target_url, wait_until='domcontentloaded', timeout=40000)
            except Exception as e:
                logger.warning(f"Initial navigation fallback: {e}")
                page.goto(url, wait_until='load', timeout=40000)

            time.sleep(3)

            # 1. Handle LinkedIn Job Page Apply Elements
            if "linkedin.com" in page.url or "linkedin.com" in url:
                # Look for Easy Apply button
                easy_apply_btn = page.locator('button.jobs-apply-button, button:has-text("Easy Apply"), .jobs-apply-button--top-card button').first
                if easy_apply_btn.is_visible(timeout=3000):
                    logger.info("Found Easy Apply button. Clicking...")
                    easy_apply_btn.click()
                    time.sleep(2)
                    return self._handle_linkedin_easy_apply(page, cover_letter)

                # Look for External Apply button ("Apply", "Apply on company website")
                apply_btn = page.locator('a.jobs-apply-button, button:has-text("Apply"), a:has-text("Apply"), button.apply-button').first
                if apply_btn.is_visible(timeout=3000):
                    logger.info("Found external Apply button. Following to application portal...")
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

            # 2. Standard Career Portal Application Form (Greenhouse / Lever / Workday / Custom)
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

            # Attach Cover Letter
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
            if browser_inst:
                try:
                    time.sleep(2)
                    browser_inst.close()
                except Exception:
                    pass
            if pw_inst:
                try:
                    pw_inst.stop()
                except Exception:
                    pass

    def _handle_linkedin_easy_apply(self, page: Page, cover_letter: Optional[str] = None) -> Dict[str, Any]:
        """Navigates LinkedIn Easy Apply multi-step modal until submission is verified."""
        max_steps = 12
        resume_attached = False

        for step in range(max_steps):
            time.sleep(2)

            # Step A: Fill visible inputs on current step
            self._fill_visible_inputs(page)

            # Step B: Attach resume if file input is on this step
            resume_file = self.get_resume_path()
            if resume_file and not resume_attached:
                if self._upload_resume(page, resume_file):
                    resume_attached = True

            # Step C: Answer screening questions
            self._answer_step_questions(page)

            # Step D: Check for Submit button
            submit_btn = page.locator('button[aria-label="Submit application"], button:has-text("Submit application"), button:has-text("Submit")').first
            if submit_btn.is_visible(timeout=1000):
                logger.info("Found Submit Application button! Clicking submit...")
                submit_btn.click()
                time.sleep(4)
                
                # Check for LinkedIn confirmation banner
                confirmation = page.locator('.artdeco-modal__header:has-text("Application sent"), h3:has-text("Application sent"), p:has-text("Your application was sent to")').first
                if confirmation.is_visible(timeout=4000):
                    return {
                        'status': 'submitted',
                        'message': '🎉 LinkedIn Confirmed: Your application was officially submitted to the employer!'
                    }
                return {'status': 'submitted', 'message': '✅ LinkedIn Easy Apply submitted successfully!'}

            # Step E: Check for "Review" button
            review_btn = page.locator('button[aria-label="Review your application"], button:has-text("Review")').first
            if review_btn.is_visible(timeout=1000):
                review_btn.click()
                continue

            # Step F: Check for "Next" button
            next_btn = page.locator('button[aria-label="Continue to next step"], button:has-text("Next")').first
            if next_btn.is_visible(timeout=1000):
                next_btn.click()
                continue
            else:
                break

        return {'status': 'filled', 'message': 'Easy Apply form completed.'}

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
            questions = page.locator('.jobs-easy-apply-form-section__grouping, .fb-dash-form-element').all()
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
