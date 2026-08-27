import yaml
import os
import re

def load_yaml(filepath: str) -> dict:
    """
    Loads a YAML file and returns its contents as a dictionary.
    """
    if not os.path.exists(filepath):
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}

def save_yaml(filepath: str, data: dict) -> None:
    """
    Saves a dictionary to a YAML file.
    """
    with open(filepath, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, default_flow_style=False)

def get_project_root() -> str:
    """
    Returns the absolute path to the project root directory.
    """
    return r"D:\job-agent"

def load_profile() -> dict:
    """
    Loads the user profile configuration.
    """
    return load_yaml(os.path.join(get_project_root(), "config", "profile.yaml"))

def load_keywords() -> dict:
    """
    Loads the job search keywords configuration.
    """
    return load_yaml(os.path.join(get_project_root(), "config", "keywords.yaml"))

def load_settings() -> dict:
    """
    Loads the agent settings configuration.
    """
    return load_yaml(os.path.join(get_project_root(), "config", "settings.yaml"))

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
    # Remove HTML tags
    clean_text = re.sub(r'<[^>]+>', ' ', text)
    # Remove extra whitespace
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
    dirs = [
        "config",
        "database",
        "utils",
        "logs"
    ]
    for d in dirs:
        os.makedirs(os.path.join(root, d), exist_ok=True)
