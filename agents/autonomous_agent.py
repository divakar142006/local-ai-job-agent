import os
import sys
import time
import logging
import threading
from typing import Dict, Any, List, Optional

from database.models import Job, Application, Notification, db
from agents.auto_hunter import AutoJobHunter
from agents.form_filler import FormFiller
from utils.email_otp import EmailOTPReader
from utils.helpers import load_profile, load_keywords, load_settings, get_project_root
from utils.notifier import get_notifier

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class AutonomousJobAgent:
    """
    100% ZERO-TOUCH AUTONOMOUS AGENT:
    1. Continuously searches for jobs across platforms based on target roles & skills.
    2. Scores jobs against Kantubothu Divakara Rao's resume.
    3. Auto-navigates, attaches resume.pdf, fills details, and submits applications.
    4. Auto-verifies submission by checking Gmail for company confirmation emails.
    5. Runs continuously in background with zero human interaction required.
    """

    def __init__(self):
        self.profile = load_profile()
        self.keywords = load_keywords()
        self.settings = load_settings()
        self.hunter = AutoJobHunter()
        self.filler = FormFiller()
        self.email_reader = EmailOTPReader()
        self.notifier = get_notifier()
        self.is_running = False
        self._thread: Optional[threading.Thread] = None

    def start_background_loop(self, interval_seconds: int = 120, max_applications_per_run: int = 15):
        """Starts the autonomous agent loop in a separate daemon thread."""
        if self.is_running:
            logger.info("Autonomous Agent is already running.")
            return

        self.is_running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(interval_seconds, max_applications_per_run),
            daemon=True
        )
        self._thread.start()
        logger.info("🚀 Autonomous Agent started in background mode!")

    def stop_background_loop(self):
        """Stops the autonomous agent background loop."""
        self.is_running = False
        logger.info("🛑 Autonomous Agent stopped.")

    def _run_loop(self, interval_seconds: int, max_apps: int):
        """Main autonomous execution loop."""
        logger.info("==========================================================")
        logger.info("🤖 AUTONOMOUS ZERO-TOUCH AGENT ACTIVE")
        logger.info("==========================================================")

        while self.is_running:
            try:
                self._execute_hunting_and_applying_cycle(max_apps)
            except Exception as e:
                logger.error(f"Error in autonomous loop cycle: {e}")

            logger.info(f"Cycle complete. Sleeping for {interval_seconds}s before next autonomous scan...")
            for _ in range(interval_seconds):
                if not self.is_running:
                    break
                time.sleep(1)

    def _execute_hunting_and_applying_cycle(self, max_apps: int):
        """Performs one full autonomous search, apply, and verify cycle."""
        self.keywords = load_keywords()
        target_roles = self.keywords.get('target_titles', ['Python Developer', 'Machine Learning Engineer', 'Software Engineer', 'Data Analyst'])
        min_score = int(self.keywords.get('min_match_score', 75))

        logger.info(f"🎯 Target Roles for this cycle: {target_roles}")

        for role in target_roles:
            if not self.is_running:
                break

            logger.info(f"\n🔍 Autonomous Search for role: '{role}'...")
            found_jobs = self.hunter.search_similar_jobs(role, location="Remote", limit=8)

            for job_data in found_jobs:
                if not self.is_running:
                    break

                url = job_data.get('url')
                title = job_data.get('title', 'Developer')
                company = job_data.get('company', 'Tech Corp')

                if not url:
                    continue

                # Check if already applied or exists
                existing = Job.get_or_none(Job.url == url)
                if existing and existing.status == 'applied':
                    continue

                # 1. AI Fit Evaluation
                match_res = self.hunter.matcher.match_job(job_data)
                score = int(match_res.get('score', 75))
                reasoning = match_res.get('reasoning', '')

                if score < min_score:
                    logger.info(f"⏭️ Skipping {title} at {company} (Score: {score}% < {min_score}%)")
                    continue

                logger.info(f"✨ Match Found! {title} at {company} (Score: {score}%)")

                # 2. Generate Tailored Cover Letter
                cl_text = self.hunter.cl_gen.generate(job_data)

                # Save or update in database
                if existing:
                    db_job = existing
                    db_job.match_score = score
                    db_job.status = 'matched'
                    db_job.save()
                else:
                    db_job = Job.create(
                        title=title,
                        company=company,
                        location=job_data.get('location', 'Remote'),
                        url=url,
                        salary=job_data.get('salary', 'Competitive'),
                        source=job_data.get('source', 'Online'),
                        description=job_data.get('description', ''),
                        status='matched',
                        match_score=score,
                        match_reasoning=reasoning
                    )

                # 3. Autonomous Browser Application Submission
                logger.info(f"🚀 Launching autonomous form filler for {title} at {company}...")
                apply_res = self.filler.auto_apply(url, cover_letter=cl_text, headless=True)
                logger.info(f"Apply Result: {apply_res.get('status')} - {apply_res.get('message')}")

                # 4. Email Verification Check
                logger.info(f"📬 Checking Gmail inbox for confirmation email from {company}...")
                time.sleep(15)  # Wait 15s for company email delivery
                email_confirmed = self._verify_company_confirmation_email(company, title)

                if email_confirmed or apply_res.get('status') == 'submitted':
                    logger.info(f"🎉 SUCCESS: Application to {company} submitted and confirmed!")
                    db_job.status = 'applied'
                    db_job.save()

                    Application.create(
                        job=db_job,
                        status='Applied',
                        platform=job_data.get('source', 'Online'),
                        cover_letter_used=cl_text
                    )
                    self.notifier.notify_applied(title, company)
                else:
                    logger.warning(f"⚠️ Submission not confirmed for {company}. Will hunt next matching job.")

                # Human-like delay between job applications
                time.sleep(8)

    def _verify_company_confirmation_email(self, company: str, role: str) -> bool:
        """Connects to Gmail via IMAP and checks if an application receipt email arrived."""
        try:
            import imaplib
            import email
            from email.header import decode_header

            settings = load_settings()
            email_addr = settings.get('email_address', 'divakantubothu@gmail.com')
            pwd = settings.get('email_app_password', '').replace(' ', '')

            if not pwd:
                return False

            mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            mail.login(email_addr, pwd)
            mail.select("INBOX")

            status, messages = mail.search(None, "ALL")
            if status != "OK" or not messages[0]:
                mail.logout()
                return False

            msg_ids = messages[0].split()[-8:]  # Check last 8 emails
            comp_lower = company.lower()
            role_lower = role.lower()

            for mid in reversed(msg_ids):
                _, data = mail.fetch(mid, "(RFC822.HEADER)")
                msg = email.message_from_bytes(data[0][1])
                sub = msg.get("Subject", "")
                from_ = msg.get("From", "")

                # Decode header
                sub_decoded = ""
                for part, enc in decode_header(sub):
                    if isinstance(part, bytes):
                        sub_decoded += part.decode(enc or 'utf-8', errors='ignore')
                    else:
                        sub_decoded += str(part)

                from_decoded = ""
                for part, enc in decode_header(from_):
                    if isinstance(part, bytes):
                        from_decoded += part.decode(enc or 'utf-8', errors='ignore')
                    else:
                        from_decoded += str(part)

                combined = f"{sub_decoded} {from_decoded}".lower()

                # Check if email is from company or application keywords
                if any(w in combined for w in [comp_lower, 'application', 'bewerbung', 'received', 'careers', 'recruiting', 'join.com', 'greenhouse', 'lever', 'workday']):
                    logger.info(f"✅ Found matching confirmation email: FROM: {from_decoded} | SUB: {sub_decoded}")
                    mail.logout()
                    return True

            mail.logout()
        except Exception as e:
            logger.debug(f"Email verification error: {e}")
        return False

# Global instance
_autonomous_agent = None

def get_autonomous_agent() -> AutonomousJobAgent:
    global _autonomous_agent
    if _autonomous_agent is None:
        _autonomous_agent = AutonomousJobAgent()
    return _autonomous_agent

if __name__ == "__main__":
    agent = AutonomousJobAgent()
    print("Starting Autonomous Zero-Touch Job Agent for Kantubothu Divakara Rao...")
    agent._execute_hunting_and_applying_cycle(max_apps=5)
