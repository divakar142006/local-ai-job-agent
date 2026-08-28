import sys
sys.path.insert(0, 'D:\\job-agent')

from typing import Dict, Any, Optional
import logging

from utils.ollama_client import OllamaAI
from utils.helpers import load_profile, load_keywords, load_settings, sanitize_text, format_job_summary
from database.models import Job, Application, Notification, initialize_db

logger = logging.getLogger(__name__)

class CoverLetterGenerator:
    """
    Generates tailored cover letters for job applications using AI.
    """

    def __init__(self):
        """
        Loads OllamaAI and user profile for cover letter generation.
        """
        self.ai = OllamaAI()
        self.profile = load_profile()

    def generate(self, job_data_or_title: Any, company: Optional[str] = None, description: Optional[str] = None) -> str:
        """
        Generates a tailored cover letter using AI based on the user's profile and job data.
        Accepts either a job dictionary or (title, company, description).
        """
        if isinstance(job_data_or_title, dict):
            job_data = job_data_or_title
        else:
            job_data = {
                'title': str(job_data_or_title or 'Position'),
                'company': str(company or 'Hiring Company'),
                'description': str(description or '')
            }
        template = self.get_default_template()
        return self.generate_with_template(job_data, template)

    def generate_with_template(self, job_data: Dict[str, Any], template: str) -> str:
        """
        Generates a cover letter using a user-provided template structure.
        """
        prompt = f"""
Using the candidate profile and job details below, write a tailored, professional cover letter.

Candidate Profile:
{self.profile}

Job Details:
Title: {job_data.get('title', 'Unknown')}
Company: {job_data.get('company', 'Unknown')}
Description: {job_data.get('description', '')}

Format Guideline:
{template}

Write ONLY the cover letter text ready to send.
"""
        try:
            self.profile = load_profile()
            letter = self.ai.generate(prompt).strip()
            if letter.startswith("Error:") or len(letter) < 20:
                name = self.profile.get('name', 'Candidate')
                skills = ", ".join(self.profile.get('skills', ['Python', 'Software Engineering']))
                return f"Dear Hiring Team at {job_data.get('company', 'the company')},\n\nI am writing to express my strong interest in the {job_data.get('title', 'position')} role. With my background and expertise in {skills}, I am confident in my ability to contribute effectively from day one.\n\nI look forward to discussing how my experience aligns with your team's goals.\n\nSincerely,\n{name}"
            return letter
        except Exception as e:
            logger.error(f"Error generating cover letter: {e}")
            return f"Dear Hiring Team at {job_data.get('company', 'the company')},\n\nI am writing to express my strong interest in the {job_data.get('title', 'position')} role. With my background and technical skills, I am confident in my ability to make an immediate impact."

    def get_default_template(self) -> str:
        """
        Returns a good default cover letter template structure.
        """
        return """
Dear Hiring Team,

[Paragraph 1: Introduction stating the role you are applying for and enthusiasm]
[Paragraph 2: Key matching technical skills and relevant projects/experience]
[Paragraph 3: Why you are excited to contribute to this specific company]
[Paragraph 4: Professional closing and call to action]

Sincerely,
[Candidate Name]
"""

    def save_cover_letter(self, job_id: int, cover_letter: str) -> None:
        """
        Saves the generated cover letter to the Application record in the database.
        """
        try:
            job = Job.get_by_id(job_id)
            app, created = Application.get_or_create(job=job)
            app.cover_letter = cover_letter
            app.save()
        except Exception as e:
            logger.error(f"Error saving cover letter to database: {e}")
