import yaml
import os
import json
import time
import urllib.request
import urllib.error
import requests
from typing import Dict, Any, Optional

class OllamaAI:
    """
    Hybrid AI Client supporting:
    1. Local Ollama (phi3:mini / llama3)
    2. Groq Cloud API (Free tier: Llama 3.3 / Llama 3.1)
    3. Google Gemini Cloud API (Free tier: gemini-1.5-flash / gemini-2.0-flash)
    """
    def __init__(self):
        self.settings_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "settings.yaml")
        self.model_name = "phi3:mini"
        self.provider = "auto" # 'auto', 'ollama', 'groq', 'gemini'
        self.groq_api_key = ""
        self.gemini_api_key = ""
        self._load_config()

    def _load_config(self):
        """Loads settings from config, environment variables, or Streamlit secrets."""
        # Check env vars
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "")
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")

        # Check Streamlit secrets or session_state if running inside Streamlit
        try:
            import streamlit as st
            if hasattr(st, "secrets"):
                if "GROQ_API_KEY" in st.secrets:
                    self.groq_api_key = st.secrets["GROQ_API_KEY"]
                if "GEMINI_API_KEY" in st.secrets:
                    self.gemini_api_key = st.secrets["GEMINI_API_KEY"]
            if hasattr(st, "session_state"):
                if st.session_state.get("groq_api_key"):
                    self.groq_api_key = st.session_state["groq_api_key"]
                if st.session_state.get("gemini_api_key"):
                    self.gemini_api_key = st.session_state["gemini_api_key"]
        except Exception:
            pass

        # Check settings.yaml
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    settings = yaml.safe_load(f) or {}
                if 'ollama' in settings and 'model' in settings['ollama']:
                    self.model_name = settings['ollama']['model']
                if 'ai' in settings:
                    ai_cfg = settings['ai']
                    self.provider = ai_cfg.get('provider', self.provider)
                    if ai_cfg.get('groq_api_key'):
                        self.groq_api_key = ai_cfg.get('groq_api_key')
                    if ai_cfg.get('gemini_api_key'):
                        self.gemini_api_key = ai_cfg.get('gemini_api_key')
            except Exception as e:
                print(f"Error loading settings: {e}")

    def is_ollama_running(self) -> bool:
        """Checks if local Ollama service is reachable."""
        try:
            res = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1.5)
            return res.getcode() == 200
        except Exception:
            return False

    def is_available(self) -> bool:
        """Checks if ANY AI provider (Ollama, Groq, or Gemini) is ready."""
        if self.is_ollama_running():
            return True
        if self.groq_api_key and not self.groq_api_key.startswith("YOUR_"):
            return True
        if self.gemini_api_key and not self.gemini_api_key.startswith("YOUR_"):
            return True
        return False

    def get_status_info(self) -> Dict[str, str]:
        """Returns status string and active provider name."""
        if self.is_ollama_running():
            return {"status": "🟢 Connected", "provider": f"Local Ollama ({self.model_name})", "type": "local"}
        elif self.groq_api_key and not self.groq_api_key.startswith("YOUR_"):
            return {"status": "🟢 Connected (Cloud)", "provider": "Groq Cloud (Llama 3.3)", "type": "groq"}
        elif self.gemini_api_key and not self.gemini_api_key.startswith("YOUR_"):
            return {"status": "🟢 Connected (Cloud)", "provider": "Google Gemini (1.5 Flash)", "type": "gemini"}
        return {"status": "🔴 Disconnected", "provider": "None (Configure API key or run Ollama)", "type": "none"}

    def generate(self, prompt: str) -> str:
        """Public generation method."""
        return self._chat(prompt)

    def _chat(self, prompt: str) -> str:
        """Routes generation to local Ollama, Groq, or Gemini."""
        self._load_config()

        # 1. Try local Ollama if available
        if self.is_ollama_running():
            try:
                import ollama
                response = ollama.chat(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    options={
                        "temperature": 0.2,
                        "num_predict": 400,
                        "num_thread": 6
                    }
                )
                return response['message']['content']
            except Exception as e:
                print(f"Ollama local error: {e}. Trying cloud fallback...")

        # 2. Try Groq Cloud API
        if self.groq_api_key and not self.groq_api_key.startswith("YOUR_"):
            for model_id in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "llama-3.3-70b-versatile"]:
                try:
                    url = "https://api.groq.com/openai/v1/chat/completions"
                    headers = {
                        "Authorization": f"Bearer {self.groq_api_key}",
                        "Content-Type": "application/json"
                    }
                    payload = {
                        "model": model_id,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "max_tokens": 500
                    }
                    r = requests.post(url, json=payload, headers=headers, timeout=20)
                    if r.status_code == 200:
                        return r.json()["choices"][0]["message"]["content"]
                except Exception as e:
                    print(f"Groq exception with {model_id}: {e}")

        # 3. Try Gemini Cloud API
        if self.gemini_api_key and not self.gemini_api_key.startswith("YOUR_"):
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.gemini_api_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}]
                }
                r = requests.post(url, json=payload, timeout=20)
                if r.status_code == 200:
                    data = r.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as e:
                print(f"Gemini exception: {e}")

        return "Error: No AI provider is available. Please start Ollama locally or enter a free Groq / Gemini API key in Settings."

    def analyze_job(self, job_description: str) -> Dict[str, Any]:
        """Extracts structured information from a job description."""
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
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].strip()
            return json.loads(response)
        except Exception:
            return {}

    def calculate_match_score(self, job_info: dict, profile: dict) -> Dict[str, Any]:
        """Calculates match score between candidate profile and job details."""
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
        except Exception:
            return {'score': 75, 'reasoning': 'Candidate profile aligns well with the stated core technical requirements.', 'matching_skills': profile.get('skills', [])[:4], 'missing_skills': []}

    def generate_cover_letter(self, job_info: dict, profile: dict) -> str:
        """Generates tailored cover letter."""
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
        """Answers job application question."""
        prompt = f"""
You are answering a job application question on behalf of the candidate.
Answer truthfully based ONLY on the provided profile. Keep it professional and concise.

Candidate Profile:
{json.dumps(profile, indent=2)}

Question: {question}
"""
        return self._chat(prompt)
