import sys
sys.path.insert(0, 'D:\\job-agent')

from typing import Dict, Any, Optional
import logging

try:
    from twilio.rest import Client
    from twilio.base.exceptions import TwilioRestException
except ImportError:
    Client = None
    TwilioRestException = Exception

from utils.ollama_client import OllamaAI
from utils.helpers import load_profile, load_keywords, load_settings, sanitize_text, format_job_summary
from database.models import Job, Application, Notification, initialize_db

logger = logging.getLogger(__name__)

class SMSNotifier:
    """
    Sends SMS notifications to the user using Twilio.
    """

    def __init__(self):
        """
        Loads settings and initializes Twilio client if configured.
        """
        self.settings = load_settings()
        twilio_cfg = self.settings.get('twilio', {})
        
        # Extract Twilio credentials from nested or flat settings
        self.account_sid = twilio_cfg.get('account_sid') or self.settings.get('twilio_account_sid')
        self.auth_token = twilio_cfg.get('auth_token') or self.settings.get('twilio_auth_token')
        self.from_number = twilio_cfg.get('from_number') or self.settings.get('twilio_from_number')
        self.to_number = twilio_cfg.get('to_number') or self.settings.get('twilio_to_number')
        
        self.client = None
        if Client and self.account_sid and self.auth_token and not str(self.account_sid).startswith("AC_YOUR"):
            try:
                self.client = Client(self.account_sid, self.auth_token)
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client: {e}")
        else:
            logger.info("Twilio not configured with live credentials. SMS will be logged locally.")

    def send_notification(self, message: str) -> bool:
        """Alias for send_sms for unified notification calls."""
        return self.send_sms(message)

    def send_sms(self, message: str) -> bool:
        """
        Sends an SMS message to the user's phone number.
        """
        if not self.client or not self.to_number or not self.from_number:
            logger.info(f"[SMS Local Notification]: {message}")
            self._log_notification(message, notif_type='simulated')
            return True
            
        try:
            self.client.messages.create(
                body=message,
                from_=self.from_number,
                to=self.to_number
            )
            self._log_notification(message, notif_type='sms_sent')
            return True
        except Exception as e:
            logger.error(f"Error sending SMS: {e}")
            self._log_notification(f"Error: {e} | {message}", notif_type='error')
            return False

    def notify_new_match(self, job_title: str, company: str, score: int) -> bool:
        """
        Notifies the user of a new high-matching job.
        """
        msg = f"New match: {job_title} at {company} (Score: {score}%). Check dashboard."
        return self.send_sms(msg)

    def notify_application_ready(self, job_title: str, company: str) -> bool:
        """
        Notifies the user that an application is pre-filled and ready for manual review.
        """
        msg = f"Application ready for {job_title} at {company}. Review on dashboard."
        return self.send_sms(msg)

    def notify_applied(self, job_title: str, company: str) -> bool:
        """
        Notifies the user that an application was successfully submitted.
        """
        msg = f"✅ Applied: {job_title} at {company}"
        return self.send_sms(msg)

    def notify_error(self, message: str) -> bool:
        """
        Notifies the user of an error in the agent system.
        """
        msg = f"Job Agent Error: {message}"
        return self.send_sms(msg)

    def ask_user(self, question: str) -> bool:
        """
        Sends a question to the user via SMS.
        """
        msg = f"Job Agent Question: {question}"
        return self.send_sms(msg)

    def test_connection(self) -> bool:
        """
        Sends a test SMS to verify the Twilio configuration.
        """
        return self.send_sms("Job Agent connected! ✅")

    def _log_notification(self, message: str, notif_type: str, job=None) -> None:
        """
        Saves the notification to the Notification table in the database.
        """
        try:
            Notification.create(
                message=message,
                notification_type=notif_type,
                sent_via='sms' if self.client else 'dashboard',
                job=job
            )
        except Exception as e:
            logger.error(f"Error logging notification to database: {e}")
