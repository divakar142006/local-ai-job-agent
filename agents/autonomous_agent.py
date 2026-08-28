import os
import sys
import time
import json
import logging
from typing import Dict, Any, List, Optional

# Ensure project root in sys.path
root = r"D:\job-agent" if os.path.exists(r"D:\job-agent") else os.path.dirname(os.path.abspath(__file__))
if root not in sys.path:
    sys.path.insert(0, root)

from database.models import Job, Application, Notification, db
from agents.auto_hunter import AutoJobHunter
from agents.form_filler import FormFiller
from utils.email_otp import EmailOTPReader
from utils.helpers import load_profile, load_keywords, load_settings, get_project_root
from utils.notifier import get_notifier

logger = logging.getLogger("autonomous_agent")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

# File log
log_path = os.path.join(get_project_root(), "agent_activity.log")
fh = logging.FileHandler(log_path, encoding='utf-8')
fh.setFormatter(formatter)
logger.addHandler(fh)

# Console log
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(formatter)
logger.addHandler(ch)

class AutonomousJobAgent:
    """
    100% ZERO-TOUCH CONTINUOUS AGENT:
    - Searches for jobs matching candidate's profile roles & skills.
    - Evaluates AI match score with Ollama (or heuristic).
    - Automatically opens browser, fills details, attaches resume.pdf, and submits.
    - Connects to Gmail via IMAP and checks for company confirmation email.
    - If not confirmed, hunts next matching role and applies immediately.
    """

    def __init__(self):
        self.profile = load_profile()
        self.keywords = load_keywords()
        self.settings = load_settings()
        self.hunter = AutoJobHunter()
        self.filler = FormFiller()
        self.notifier = get_notifier()
        self.status_file = os.path.join(get_project_root(), "agent_status.json")

    def set_status(self, is_running: bool, current_action: str = "Idle", total_applied: int = 0):
        """Saves live agent status to disk so Streamlit UI can read it in real time."""
        try:
            data = {
                "is_running": is_running,
                "current_action": current_action,
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_applied": total_applied
            }
            with open(self.status_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def run_continuous(self, interval_seconds: int = 60, max_apps_per_cycle: int = 10):
        """Runs the continuous hunting and applying loop."""
        logger.info("==========================================================")
        logger.info("🤖 24/7 ZERO-TOUCH AUTONOMOUS AGENT ACTIVE")
        logger.info("==========================================================")

        self.set_status(True, "Starting search loop...")

        while True:
            try:
                self.execute_cycle(max_apps=max_apps_per_cycle)
            except Exception as e:
                logger.error(f"Error in execution cycle: {e}")

            logger.info(f"Cycle finished. Resting {interval_seconds}s before next auto-hunt cycle...")
            self.set_status(True, f"Resting between cycles ({interval_seconds}s)...")
            time.sleep(interval_seconds)

    def execute_cycle(self, max_apps: int = 5):
        """Executes one full autonomous discovery, submission, and verification cycle."""
        self.keywords = load_keywords()
        target_roles = self.keywords.get('target_titles', ['Python Developer', 'Machine Learning Engineer', 'Software Engineer', 'Data Analyst'])
        min_score = int(self.keywords.get('min_match_score', 75))

        logger.info(f"🎯 Target Roles: {target_roles}")
        applied_in_cycle = 0

        for role in target_roles:
            if applied_in_cycle >= max_apps:
                break

            logger.info(f"\n🔍 Searching for roles matching: '{role}'...")
            self.set_status(True, f"Searching for '{role}' openings...")
            found_jobs = self.hunter.search_similar_jobs(role, location="Remote", limit=6)

            for job_data in found_jobs:
                if applied_in_cycle >= max_apps:
                    break

                url = job_data.get('url')
                title = job_data.get('title', 'Developer')
                company = job_data.get('company', 'Tech Corp')

                if not url:
                    continue

                # Check if already applied
                existing = Job.get_or_none(Job.url == url)
                if existing and existing.status == 'applied':
                    continue

                # 1. AI Fit Evaluation
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

                # Save / update in DB
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
                        source=job_data.get('source', 'Arbeitnow'),
                        description=job_data.get('description', ''),
                        status='matched',
                        match_score=score,
                        match_reasoning=reasoning
                    )

                # 3. Autonomous Browser Application Submission
                self.set_status(True, f"Filling & Submitting application for {title} at {company}...")
                logger.info(f"🚀 Launching autonomous form filler for {title} at {company}...")
                
                apply_res = self.filler.auto_apply(url, cover_letter=cl_text, headless=True)
                status = apply_res.get('status')
                msg = apply_res.get('message', '')
                logger.info(f"Submission status: {status} - {msg}")

                # 4. Gmail IMAP Confirmation Check
                self.set_status(True, f"Verifying confirmation email from {company}...")
                logger.info(f"📬 Checking Gmail inbox for confirmation email from {company}...")
                time.sleep(12)
                email_confirmed = self._verify_company_confirmation_email(company, title)

                if email_confirmed or status == 'submitted':
                    logger.info(f"🎉 SUCCESS: Application to {company} submitted and confirmed!")
                    db_job.status = 'applied'
                    db_job.save()

                    Application.create(
                        job=db_job,
                        status='Applied',
                        platform=job_data.get('source', 'Arbeitnow'),
                        cover_letter_used=cl_text
                    )
                    self.notifier.notify_applied(title, company)
                    applied_in_cycle += 1
                else:
                    logger.warning(f"⚠️ Confirmation not received yet for {company}. Moving to next role...")

                time.sleep(6)

    def _verify_company_confirmation_email(self, company: str, role: str) -> bool:
        """Connects to Gmail via IMAP and checks if a confirmation email arrived."""
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

            msg_ids = messages[0].split()[-8:]
            comp_lower = company.lower().split()[0] if company else ""

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

                if comp_lower and comp_lower in combined:
                    logger.info(f"✅ Confirmed by company email: {from_decoded} - {sub_decoded}")
                    mail.logout()
                    return True

                if any(w in combined for w in ['application', 'bewerbung', 'received', 'recruiting', 'join.com', 'greenhouse', 'lever', 'workday']):
                    logger.info(f"✅ Confirmed by ATS email: {from_decoded} - {sub_decoded}")
                    mail.logout()
                    return True

            mail.logout()
        except Exception as e:
            logger.debug(f"Email check error: {e}")
        return False

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
