import logging
from typing import Optional
from database.models import Notification

logger = logging.getLogger(__name__)

class AppNotifier:
    """Handles in-app notification logging and desktop notification alerts."""

    def __init__(self):
        pass

    def notify_applied(self, job_title: str, company: str):
        """Logs and triggers an application success notification."""
        msg = f"Successfully submitted application for {job_title} at {company}!"
        logger.info(f"🔔 NOTIFICATION: {msg}")
        try:
            Notification.create(
                title=f"Application Submitted: {company}",
                message=msg,
                type="success"
            )
        except Exception as e:
            logger.debug(f"Could not persist notification to DB: {e}")

        # Desktop alert
        try:
            from plyer import notification
            notification.notify(
                title="Job Applied!",
                message=f"Submitted to {job_title} at {company}",
                app_name="AI Job Agent",
                timeout=5
            )
        except Exception:
            pass

    def notify_match(self, job_title: str, company: str, score: int):
        """Logs a high match score job alert."""
        msg = f"Found new high-match job ({score}%): {job_title} at {company}"
        logger.info(f"🔔 MATCH NOTIFICATION: {msg}")
        try:
            Notification.create(
                title=f"New High Match ({score}%): {company}",
                message=msg,
                type="info"
            )
        except Exception:
            pass

_notifier = None

def get_notifier() -> AppNotifier:
    global _notifier
    if _notifier is None:
        _notifier = AppNotifier()
    return _notifier
