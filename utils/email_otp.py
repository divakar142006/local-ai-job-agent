import imaplib
import email
from email.header import decode_header
import re
import time
import logging
from typing import Optional, Dict, Any

from utils.helpers import load_settings, load_profile

logger = logging.getLogger(__name__)

class EmailOTPReader:
    """
    Automated Email OTP & Verification Code Retriever:
    Connects to Gmail via IMAP and extracts the latest verification code
    sent by employer career portals (Oracle Cloud, Workday, Taleo, etc.).
    """

    def __init__(self):
        self.settings = load_settings()
        self.profile = load_profile()

    def get_credentials(self) -> Dict[str, str]:
        email_addr = self.settings.get('email_address') or self.profile.get('email', 'divakantubothu@gmail.com')
        app_password = self.settings.get('email_app_password') or ''
        return {
            'email': email_addr.strip(),
            'password': app_password.replace(" ", "").strip()
        }

    def test_connection(self) -> Dict[str, Any]:
        """Tests IMAP connection to Gmail."""
        creds = self.get_credentials()
        if not creds['password']:
            return {'status': 'error', 'message': 'Please enter your 16-letter Gmail App Password in Settings.'}

        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            mail.login(creds['email'], creds['password'])
            mail.logout()
            return {'status': 'success', 'message': f"✅ Successfully connected to {creds['email']} inbox!"}
        except Exception as e:
            return {'status': 'error', 'message': f"IMAP connection failed: {str(e)}"}

    def fetch_latest_otp(self, sender_hint: Optional[str] = None, timeout_seconds: int = 30) -> Optional[str]:
        """
        Polls inbox for recent emails arriving in the last 5 minutes and extracts OTP codes.
        """
        creds = self.get_credentials()
        if not creds['password']:
            logger.warning("No Gmail App Password configured in Settings.")
            return None

        start_time = time.time()
        logger.info(f"Waiting for OTP email to arrive in {creds['email']} (timeout: {timeout_seconds}s)...")

        while time.time() - start_time < timeout_seconds:
            try:
                mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
                mail.login(creds['email'], creds['password'])
                mail.select("INBOX")

                # Search latest emails
                status, messages = mail.search(None, "ALL")
                if status != "OK" or not messages[0]:
                    mail.logout()
                    time.sleep(3)
                    continue

                msg_ids = messages[0].split()
                # Check top 5 most recent emails
                recent_ids = msg_ids[-5:]
                recent_ids.reverse()

                for msg_id in recent_ids:
                    status, msg_data = mail.fetch(msg_id, "(RFC822)")
                    if status != "OK":
                        continue

                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            
                            # Extract subject and body
                            subject = ""
                            raw_subject = msg.get("Subject", "")
                            if raw_subject:
                                decoded = decode_header(raw_subject)[0]
                                if isinstance(decoded[0], bytes):
                                    subject = decoded[0].decode(decoded[1] or 'utf-8', errors='ignore')
                                else:
                                    subject = str(decoded[0])

                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    ctype = part.get_content_type()
                                    if ctype == "text/plain":
                                        payload = part.get_payload(decode=True)
                                        if payload:
                                            body += payload.decode('utf-8', errors='ignore')
                            else:
                                payload = msg.get_payload(decode=True)
                                if payload:
                                    body = payload.decode('utf-8', errors='ignore')

                            full_text = f"{subject} {body}"
                            
                            # Check if email is a verification/OTP email
                            keywords = ["verification", "verify", "otp", "code", "security code", "passcode", "one-time", "jpmorgan", "oracle", "workday"]
                            if any(k in full_text.lower() for k in keywords):
                                # Regex patterns for OTP codes (e.g. 123456, 123-456, or "is 849201")
                                otp_patterns = [
                                    r'(?:code|otp|passcode|pin|is)\s*(?:is|:)?\s*([0-9]{4,8})',
                                    r'\b([0-9]{6})\b',
                                    r'\b([0-9]{4})\b',
                                    r'\b([0-9]{8})\b'
                                ]
                                for pat in otp_patterns:
                                    match = re.search(pat, full_text, re.IGNORECASE)
                                    if match:
                                        otp = match.group(1).replace("-", "").strip()
                                        logger.info(f"🎉 Found OTP Code: {otp} from email subject: {subject}")
                                        mail.logout()
                                        return otp

                mail.logout()
            except Exception as e:
                logger.debug(f"IMAP poll error: {e}")

            time.sleep(3)

        return None
