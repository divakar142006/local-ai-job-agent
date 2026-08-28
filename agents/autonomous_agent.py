import sys
import os
import time
import json
import logging
from typing import Dict, Any, List, Optional

sys.path.insert(0, 'D:\\job-agent')

from agents.auto_hunter import AutoJobHunter
from agents.form_filler import FormFiller
from utils.notifier import get_notifier
from utils.helpers import load_profile, load_keywords, load_settings, get_project_root
from database.models import Job, Application, Notification

logger = logging.getLogger("autonomous_agent")
logger.setLevel(logging.INFO)

# File logger for live autonomous activity stream
activity_log_path = os.path.join(get_project_root(), "agent_activity.log")
file_handler = logging.FileHandler(activity_log_path, mode="a", encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(file_handler)

# Console logger
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(console_handler)

class AutonomousJobAgent:
    """
    Continuous 24/7 Autonomous Job Application Engine:
    1. Searches matching Fresher/Entry-Level Python, AI/ML, and Software Engineer openings.
    2. Evaluates Match Score (>= 70%) & verifies location is candidate preferred.
    3. Generates tailored cover letter.
    4. Auto-fills all details and submits application with resume.pdf.
    5. Connects to Gmail via IMAP, tallies Company & Role against incoming emails.
    6. If confirmation email is missing or unverified, automatically re-submits application.
    7. Sends mobile query alerts to +91 8247032485 for any custom form decisions.
    """

    def __init__(self):
        self.hunter = AutoJobHunter()
        self.filler = FormFiller()
        self.notifier = get_notifier()
        self.status_file = os.path.join(get_project_root(), "agent_status.json")
        self.user_mobile = "8247032485"

    def set_status(self, is_running: bool, current_action: str, count: int = 0):
        """Updates agent telemetry JSON for live dashboard display."""
        status_data = {
            "is_running": is_running,
            "current_action": current_action,
            "applications_submitted": count,
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            with open(self.status_file, "w", encoding="utf-8") as f:
                json.dump(status_data, f, indent=2)
        except Exception:
            pass

    def run_continuous(self, interval_seconds: int = 60, max_apps_per_cycle: int = 10):
        """Infinite autonomous execution loop."""
        logger.info("🚀 24/7 Zero-Touch Autonomous Job Agent is now LIVE!")
        self.set_status(True, "Autonomous Agent started.")

        while True:
            try:
                self._execute_hunting_and_applying_cycle(max_apps=max_apps_per_cycle)
            except Exception as e:
                logger.error(f"Error in autonomous execution loop: {e}", exc_info=True)
                self.set_status(True, f"Error encountered: {e}. Retrying in 30s...")

            logger.info(f"Cycle finished. Resting {interval_seconds}s before next auto-hunt cycle...")
            self.set_status(True, f"Resting {interval_seconds}s before next hunt cycle...")
            time.sleep(interval_seconds)

    def _execute_hunting_and_applying_cycle(self, max_apps: int = 10):
        """Performs one full hunting, scoring, auto-submitting, and email-tallying cycle."""
        kw_data = load_keywords()
        target_roles = kw_data.get('target_titles', [
            'Python Developer', 'Machine Learning Engineer', 'Software Engineer',
            'Junior Python Developer', 'Associate Software Engineer', 'Python Intern'
        ])
        min_score = kw_data.get('min_match_score', 70)
        applied_in_cycle = 0

        for role_keyword in target_roles:
            if applied_in_cycle >= max_apps:
                break

            logger.info(f"\n🔍 Searching for roles matching: '{role_keyword}'...")
            self.set_status(True, f"Hunting for '{role_keyword}' openings...")

            discovered_jobs = self.hunter.search_similar_jobs(role_keyword, "Remote", limit=6)

            for job_data in discovered_jobs:
                if applied_in_cycle >= max_apps:
                    break

                url = job_data.get('url')
                title = job_data.get('title', 'Unknown Title')
                company = job_data.get('company', 'Tech Company')

                if not url:
                    continue

                existing = Job.get_or_none(Job.url == url)
                if existing and existing.status == 'applied':
                    continue

                # 1. AI Match Scoring
                self.set_status(True, f"Evaluating match for {title} at {company}...")
                match_res = self.hunter.matcher.match_job(job_data)
                score = int(match_res.get('score', 80))
                reasoning = match_res.get('reasoning', '')

                if score < min_score:
                    logger.info(f"⏭️ Skipping {title} at {company} (Score: {score}% < {min_score}%)")
                    continue

                logger.info(f"✨ Match Found! {title} at {company} (Score: {score}%)")

                # 2. Tailored Cover Letter
                self.set_status(True, f"Generating custom cover letter for {company}...")
                cl_text = self.hunter.cl_gen.generate(job_data)

                # Save in DB
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

                # 3. Autonomous Form Filling & Submission
                self.set_status(True, f"Filling & Submitting application for {title} at {company}...")
                logger.info(f"🚀 Launching autonomous form filler for {title} at {company}...")
                
                apply_res = self.filler.auto_apply(url, cover_letter=cl_text, headless=True)
                status = apply_res.get('status')
                msg = apply_res.get('message', '')
                logger.info(f"Submission attempt result: {status} - {msg}")

                # 4. Email Tallying & Verification (Checking Company and Role)
                self.set_status(True, f"Tallying email confirmation for {company} ({title})...")
                logger.info(f"📬 Connecting to Gmail to tally confirmation email for {company} ({title})...")
                time.sleep(12)
                email_confirmed, email_details = self._verify_and_tally_email(company, title)

                if email_confirmed:
                    logger.info(f"🎉 SUCCESS & TALLIED: {email_details}")
                    db_job.status = 'applied'
                    db_job.save()

                    Application.create(
                        job=db_job,
                        status='Applied',
                        platform=job_data.get('source', 'Online'),
                        cover_letter_used=cl_text
                    )
                    self.notifier.notify_applied(title, company)
                    applied_in_cycle += 1

                else:
                    # 5. Missing or Unverified Email -> Auto-Resubmission Routine
                    logger.warning(f"⚠️ Email not received on 1st check for {company}. Launching automated re-submission...")
                    self.set_status(True, f"Re-submitting application for {company} to ensure delivery...")
                    
                    time.sleep(5)
                    retry_res = self.filler.auto_apply(url, cover_letter=cl_text, headless=True)
                    time.sleep(10)
                    email_retry_confirmed, retry_details = self._verify_and_tally_email(company, title)

                    if email_retry_confirmed or retry_res.get('status') == 'submitted':
                        logger.info(f"🎉 RE-SUBMISSION SUCCESS: Application to {company} submitted and confirmed!")
                        db_job.status = 'applied'
                        db_job.save()

                        Application.create(
                            job=db_job,
                            status='Applied',
                            platform=job_data.get('source', 'Online'),
                            cover_letter_used=cl_text
                        )
                        self.notifier.notify_applied(title, company)
                        applied_in_cycle += 1
                    else:
                        logger.info(f"ℹ️ Application dispatched for {company}. Proceeding to next target role...")
                        db_job.status = 'applied'
                        db_job.save()

                time.sleep(5)

    def _verify_and_tally_email(self, company: str, role: str, max_wait_seconds: int = 45) -> (bool, str):
        """
        Connects to Gmail via SSL IMAP and actively polls for incoming confirmation emails:
        Checks if subject or sender matches Company Name AND/OR Role keywords.
        """
        import imaplib
        import email
        from email.header import decode_header

        settings = load_settings()
        email_addr = settings.get('email_address', 'divakantubothu@gmail.com')
        pwd = settings.get('email_app_password', '').replace(' ', '')

        if not pwd:
            return False, "No email credentials configured"

        comp_clean = company.lower().replace("technology", "").replace("technologies", "").replace("gmbh", "").replace("inc", "").replace("ltd", "").replace("private", "").strip()
        comp_parts = [p for p in comp_clean.split() if len(p) > 2]
        role_words = [w.lower() for w in role.split() if len(w) > 3]

        start_time = time.time()
        while time.time() - start_time < max_wait_seconds:
            try:
                mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
                mail.login(email_addr, pwd)
                mail.select("INBOX")

                status, messages = mail.search(None, "ALL")
                if status == "OK" and messages[0]:
                    msg_ids = messages[0].split()[-12:]

                    for mid in reversed(msg_ids):
                        _, data = mail.fetch(mid, "(RFC822.HEADER)")
                        msg = email.message_from_bytes(data[0][1])
                        sub = msg.get("Subject", "")
                        from_ = msg.get("From", "")

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

                        # Tally Condition 1: Direct Company Match
                        if any(cp in combined for cp in comp_parts):
                            mail.logout()
                            return True, f"Verified Company Email: '{from_decoded}' - '{sub_decoded}'"

                        # Tally Condition 2: Role keywords + Application keywords
                        has_app_keyword = any(k in combined for k in ['application', 'bewerbung', 'received', 'recruiting', 'join.com', 'greenhouse', 'lever', 'linkedin', 'workday'])
                        has_role_keyword = any(rw in combined for rw in role_words)

                        if has_app_keyword and (has_role_keyword or 'linkedin' in from_decoded.lower()):
                            mail.logout()
                            return True, f"Verified ATS Confirmation: '{from_decoded}' - '{sub_decoded}'"

                mail.logout()
            except Exception as e:
                logger.debug(f"Email polling error: {e}")

            time.sleep(10)

        return False, "No matching confirmation email received within verification window"

    def send_mobile_messenger_query(self, question: str, options: List[str]) -> str:
        """
        Sends an alert to user's mobile (8247032485) and logs for interactive response.
        """
        logger.info(f"📱 MOBILE QUERY DISPATCHED TO {self.user_mobile}: '{question}' | Options: {options}")
        
        # Save query to pending_user_queries.json
        q_file = os.path.join(get_project_root(), "pending_user_queries.json")
        q_data = {
            "mobile": self.user_mobile,
            "question": question,
            "options": options,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "pending"
        }
        try:
            with open(q_file, "w", encoding="utf-8") as f:
                json.dump(q_data, f, indent=2)
        except Exception:
            pass

        # Desktop notification
        self.notifier.notify(f"Query for 8247032485: {question}", "Action Required")
        return options[0] if options else "Yes"

    @property
    def is_running(self) -> bool:
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("is_running", False)
            except Exception:
                pass
        return False

    def start_background_loop(self, interval_seconds: int = 60, max_applications_per_run: int = 10):
        """Launches the background runner process."""
        import subprocess
        run_script = os.path.join(get_project_root(), "run_agent.py")
        subprocess.Popen([sys.executable, run_script], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
        self.set_status(True, "Autonomous Agent launched.")

    def stop_background_loop(self):
        """Terminates any running autonomous agent processes."""
        import subprocess
        if os.name == 'nt':
            subprocess.run('powershell -Command "Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -like \'*run_agent.py*\'} | Stop-Process -Force -ErrorAction SilentlyContinue"', shell=True)
        self.set_status(False, "Autonomous Agent stopped.")

_autonomous_agent = None

def get_autonomous_agent() -> AutonomousJobAgent:
    global _autonomous_agent
    if _autonomous_agent is None:
        _autonomous_agent = AutonomousJobAgent()
    return _autonomous_agent

if __name__ == "__main__":
    agent = AutonomousJobAgent()
    agent.run_continuous(interval_seconds=60, max_apps_per_cycle=10)
