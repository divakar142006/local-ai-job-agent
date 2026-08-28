import yaml
import os
import re

def get_project_root() -> str:
    """
    Returns the absolute path to the project root directory across any OS (Windows / Linux / Cloud).
    """
    if os.path.exists(r"D:\job-agent"):
        return r"D:\job-agent"
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_yaml(filepath: str) -> dict:
    """
    Loads a YAML file and returns its contents as a dictionary.
    """
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error loading YAML {filepath}: {e}")
        return {}

def save_yaml(filepath: str, data: dict) -> None:
    """
    Saves a dictionary to a YAML file, ensuring parent directories exist.
    """
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False)
    except Exception as e:
        print(f"Error saving YAML {filepath}: {e}")

def load_profile() -> dict:
    """
    Loads the user profile configuration from disk, session_state, or secrets.
    """
    data = load_yaml(os.path.join(get_project_root(), "config", "profile.yaml"))
    
    # Check Streamlit session_state for dynamic user edits
    try:
        import streamlit as st
        if hasattr(st, "session_state") and "user_profile" in st.session_state:
            data.update(st.session_state["user_profile"])
        if hasattr(st, "secrets") and "profile" in st.secrets:
            data.update(st.secrets["profile"])
    except Exception:
        pass
    return data

def load_keywords() -> dict:
    """
    Loads the job search keywords configuration.
    """
    data = load_yaml(os.path.join(get_project_root(), "config", "keywords.yaml"))
    try:
        import streamlit as st
        if hasattr(st, "session_state") and "user_keywords" in st.session_state:
            data.update(st.session_state["user_keywords"])
    except Exception:
        pass
    return data

def load_settings() -> dict:
    """
    Loads the agent settings configuration.
    """
    data = load_yaml(os.path.join(get_project_root(), "config", "settings.yaml"))
    try:
        import streamlit as st
        if hasattr(st, "session_state") and "user_settings" in st.session_state:
            data.update(st.session_state["user_settings"])
        if hasattr(st, "secrets"):
            if "GROQ_API_KEY" in st.secrets:
                data.setdefault("ai", {})["groq_api_key"] = st.secrets["GROQ_API_KEY"]
            if "GEMINI_API_KEY" in st.secrets:
                data.setdefault("ai", {})["gemini_api_key"] = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    return data

def format_job_summary(job: dict) -> str:
    """
    Formats a dictionary of job information into a readable text summary.
    """
    title = job.get('title', 'Unknown Title')
    company = job.get('company', 'Unknown Company')
    location = job.get('location', 'Unknown Location')
    salary = job.get('salary', 'Not specified')
    
    return f"{title} at {company}\nLocation: {location}\nSalary: {salary}"

def sanitize_text(text: str) -> str:
    """
    Cleans HTML tags and extra whitespace from a string.
    """
    if not text:
        return ""
    clean_text = re.sub(r'<[^>]+>', ' ', text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text

def truncate_text(text: str, max_length: int = 500) -> str:
    """
    Truncates text to a maximum length, appending '...' if it exceeds the limit.
    """
    if not text or len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

def ensure_directories() -> None:
    """
    Creates all necessary project directories if they don't already exist.
    """
    root = get_project_root()
    dirs = ["config", "database", "utils", "logs"]
    for d in dirs:
        os.makedirs(os.path.join(root, d), exist_ok=True)
