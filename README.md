# Local AI Job Application Agent

A fully local AI-powered job application agent that helps you track jobs, evaluate match scores, generate cover letters, and auto-fill applications, all while keeping your data private using local models.

## Features
- **Job Scraping**: Extracts job descriptions and details from URLs.
- **AI Matching**: Evaluates how well a job fits your profile and skills using a local LLM (Ollama).
- **Cover Letter Generation**: Automatically writes customized cover letters based on your profile and the job description.
- **Auto-Fill Applications**: Opens a browser and pre-fills job application forms using Playwright.
- **SMS Notifications**: Sends you updates when applications are submitted (via Twilio).
- **Interactive Dashboard**: A beautiful Streamlit interface to manage your job pipeline.
- **100% Local Processing**: No data is sent to external AI APIs (except optional SMS via Twilio).

## Prerequisites
- Python 3.11+
- Windows 10/11
- 16GB RAM recommended
- Internet connection (for scraping job pages and SMS)

## Setup Guide

### Step 1: Install Python
- Download and install Python from [python.org](https://www.python.org/downloads/).
- **Important:** During installation, ensure you check the box that says **"Add Python to PATH"**.

### Step 2: Install Ollama
- Download and install Ollama from [ollama.com](https://ollama.com/).
- Open a terminal or command prompt and pull the default model:
  ```bash
  ollama pull phi3:mini
  ```
- Verify the installation by running:
  ```bash
  ollama list
  ```
  You should see `phi3:mini` in the list.

### Step 3: Install Project Dependencies
Open your terminal and run the following commands:
```bash
cd D:\job-agent
pip install -r requirements.txt
playwright install chromium
```

### Step 4: Configure Your Profile
You need to provide your details so the AI can match jobs and write cover letters.
- Edit `config/profile.yaml` with your name, experience, education, and skills.
- Edit `config/keywords.yaml` to set your deal-breakers and preferred technologies.
*Note: You can also edit these directly from the "Settings" page in the dashboard!*

### Step 5: Set Up Twilio (Optional)
If you want SMS notifications when applications are marked as applied:
1. Create a free account at [twilio.com](https://www.twilio.com/).
2. Get your Account SID, Auth Token, and a Twilio phone number.
3. Open the Dashboard -> Settings -> Twilio SMS and enter your credentials, or edit `config/settings.yaml` manually.

### Step 6: Run the Agent
Start the Streamlit dashboard by running:
```bash
cd D:\job-agent
streamlit run app.py
```
This will automatically open your default web browser to `http://localhost:8501`.

## Usage Guide
### 📋 Page 1: Add Job
- Paste a URL to a job posting, or paste the job description directly into the text area.
- Click **Analyze Job**. The AI will read the job, compare it to your profile, score it, and generate a cover letter.
- Review the results. If it looks good, click **Save Job** to add it to your pipeline.

### 📊 Page 2: Job Pipeline
- View all your saved jobs organized by status (New, Matched, Applied, Rejected).
- Expand a job card to view the match reasoning and edit the generated cover letter.
- Use the quick action buttons to **Generate Cover Letter**, **Mark Applied**, or **Reject** a job.

### 🚀 Page 3: Apply
- Select a job from your pipeline to apply to.
- Review or regenerate the cover letter.
- Click **Open & Pre-fill Application**. A new browser window will open, and Playwright will attempt to fill in standard fields based on your profile.
- **Review the form manually** in the opened browser window and click submit yourself.
- Return to the dashboard and click **Mark as Applied** to move the job to the 'Applied' status and trigger an SMS notification.

### ⚙️ Page 4: Settings
- Update your personal information, experience, and skills in real-time.
- Adjust your job search keywords.
- Manage your Twilio credentials.
- Test your AI connection to ensure Ollama is running properly.

## Troubleshooting

- **Ollama not connecting**: Ensure the Ollama app is running in the background. The icon should be in your system tray. Try running `ollama run phi3:mini` in the terminal to verify it works outside the app.
- **Playwright browser not installing**: Ensure you ran `playwright install chromium` as an administrator if required. 
- **Twilio SMS not sending**: Check your Twilio dashboard to ensure your trial account has credit and your "To Number" is verified.
- **Port 8501 already in use**: Streamlit will usually pick the next available port (like 8502), but you can force a port with `streamlit run app.py --server.port 8505`.

## Project Structure
```text
D:\job-agent\
├── agents/             # Logic for scraping, matching, and filling forms
├── config/             # YAML files for profile, keywords, and settings
├── database/           # SQLite database models
├── utils/              # Helper scripts and Ollama client
├── app.py              # Main Streamlit dashboard application
├── requirements.txt    # Python package dependencies
└── README.md           # This file!
```
