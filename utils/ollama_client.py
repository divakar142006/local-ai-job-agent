import yaml
import os
import json
import time
import ollama
from typing import Dict, Any

class OllamaNotRunningError(Exception):
    """Exception raised when Ollama is not running or available."""
    pass

class OllamaAI:
    """
    Wrapper class for communicating with the local Ollama AI model.
    """
    def __init__(self):
        """Loads configuration and tests connection to Ollama."""
        self.settings_path = r"D:\job-agent\config\settings.yaml"
        self.model_name = "phi3:mini"  # Default model optimized for 16GB RAM
        self._load_config()
        # Don't crash on init if Ollama isn't running yet - allow graceful degradation
        if not self.is_available():
            print(f"⚠️ Warning: Ollama is not running. Start it with 'ollama serve' and pull model with 'ollama pull {self.model_name}'")
            
    def _load_config(self):
        """Loads settings from the config file."""
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    settings = yaml.safe_load(f)
                if settings and 'ollama' in settings and 'model' in settings['ollama']:
                        self.model_name = settings['ollama']['model']
            except Exception as e:
                print(f"Error loading settings: {e}. Using default model: {self.model_name}")

    def is_available(self) -> bool:
        """Checks if the Ollama service is running and accessible."""
        try:
            import urllib.request
            res = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
            return res.getcode() == 200
        except Exception:
            try:
                models = ollama.list()
                return True
            except Exception:
                return False

    def generate(self, prompt: str) -> str:
        """Public method to generate text using the local AI model."""
        return self._chat(prompt)

    def _chat(self, prompt: str) -> str:
        """
        Internal method to call ollama.chat with retry logic and error handling.
        """
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                response = ollama.chat(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    options={
                        "temperature": 0.2,
                        "num_predict": 350,
                        "num_thread": 6
                    }
                )
                return response['message']['content']
            except Exception as e:
                if attempt < max_retries:
                    print(f"Ollama chat error: {e}. Retrying ({attempt + 1}/{max_retries})...")
                    time.sleep(2)
                else:
                    print(f"Failed to communicate with Ollama after {max_retries} retries: {e}")
                    raise

    def analyze_job(self, job_description: str) -> Dict[str, Any]:
        """
        Extracts structured information from a job description.
        """
        prompt = f"""
Analyze the following job description and extract these details in JSON format only:
- title
- company
- location
- requirements (a list of strings)
- salary (string, or null if not mentioned)
- job_type (e.g., full-time, contract)
- experience_required (string)

Job Description:
{job_description}

Return ONLY valid JSON.
"""
        response = self._chat(prompt)
        try:
            # Sometimes models wrap json in markdown block
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].strip()
                
            return json.loads(response)
        except json.JSONDecodeError:
            print("Failed to parse JSON from Ollama response for job analysis.")
            return {}

    def calculate_match_score(self, job_info: dict, profile: dict) -> Dict[str, Any]:
        """
        Calculates a match score (0-100) between a job and a user profile.
        """
        prompt = f"""
You are an expert technical recruiter. Evaluate how well this candidate profile matches the job.

Candidate Profile:
{json.dumps(profile, indent=2)}

Job Information:
{json.dumps(job_info, indent=2)}

Provide your evaluation as a JSON object with the following keys:
- 'score': an integer from 0 to 100 representing the match percentage
- 'reasoning': a brief string explaining why you gave this score
- 'matching_skills': a list of skills from the candidate's profile that are required or relevant to the job
- 'missing_skills': a list of skills required by the job that are missing from the candidate's profile

Return ONLY valid JSON.
"""
        response = self._chat(prompt)
        try:
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].strip()
                
            return json.loads(response)
        except json.JSONDecodeError:
            print("Failed to parse JSON from Ollama response for match score.")
            return {'score': 0, 'reasoning': 'Error parsing AI response', 'matching_skills': [], 'missing_skills': []}

    def generate_cover_letter(self, job_info: dict, profile: dict) -> str:
        """
        Generates a tailored cover letter for a specific job based on the user's profile.
        """
        prompt = f"""
Write a professional, concise, and compelling cover letter for the following job using the candidate's profile.
Do not include placeholder text like [Your Name]. Just write the body of the letter.

Candidate Profile:
{json.dumps(profile, indent=2)}

Job Information:
{json.dumps(job_info, indent=2)}
"""
        return self._chat(prompt)

    def answer_question(self, question: str, profile: dict) -> str:
        """
        Answers a common job application question using data from the user profile.
        """
        prompt = f"""
You are answering a job application question on behalf of the candidate.
Answer truthfully based ONLY on the provided profile. Keep it professional and concise.

Candidate Profile:
{json.dumps(profile, indent=2)}

Question: {question}
"""
        return self._chat(prompt)
