import sys
import os
import time
import json
import streamlit as st

# Setup path for local imports
sys.path.insert(0, 'D:\\job-agent')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.models import Job, Application, Notification, initialize_db
from agents.scraper import JobScraper
from agents.matcher import JobMatcher
from agents.cover_letter import CoverLetterGenerator
from agents.form_filler import FormFiller
from agents.notifier import SMSNotifier
from agents.auto_hunter import AutoJobHunter
from utils.helpers import load_profile, load_keywords, load_settings, save_yaml, get_project_root
from utils.ollama_client import OllamaAI

# UI Setup
st.set_page_config(page_title="AI Job Application Agent", page_icon="🤖", layout="wide")

# Initialize Database
try:
    initialize_db()
except Exception as e:
    st.warning(f"Database note: {e}")

# Caching and Initialization
@st.cache_resource
def get_ollama_client():
    return OllamaAI()

@st.cache_resource
def get_scraper():
    return JobScraper()

@st.cache_resource
def get_matcher():
    return JobMatcher()

@st.cache_resource
def get_cover_letter_generator():
    return CoverLetterGenerator()

@st.cache_resource
def get_form_filler():
    return FormFiller()

@st.cache_resource
def get_notifier():
    return SMSNotifier()

@st.cache_resource
def get_auto_hunter():
    return AutoJobHunter()

# Check AI Connection Live
ollama_ai = get_ollama_client()
ai_info = ollama_ai.get_status_info()
st.session_state.ai_status = ai_info["status"]
st.session_state.ai_provider = ai_info["provider"]

# Sidebar Navigation
st.sidebar.title("🤖 AI Job Application Agent")
page = st.sidebar.radio(
    "Navigation",
    ["📋 Add Job", "🎯 Auto Search & Apply", "📊 Job Pipeline", "🚀 Apply", "⚙️ Settings"]
)

st.sidebar.divider()
col_st1, col_st2 = st.sidebar.columns([3, 1])
with col_st1:
    st.markdown(f"**AI Engine:** {st.session_state.ai_status}")
with col_st2:
    if st.button("🔄", help="Refresh AI Connection"):
        st.cache_resource.clear()
        st.rerun()

st.sidebar.caption(f"Provider: `{st.session_state.ai_provider}`")

# Sidebar Stats
try:
    jobs = Job.select()
    total_jobs = jobs.count()
    applied_jobs = jobs.where(Job.status == "applied").count()
    matched_jobs = jobs.where((Job.status == "matched") | (Job.status == "applied")).count()
    match_rate = int((matched_jobs / total_jobs * 100)) if total_jobs > 0 else 0
except Exception:
    total_jobs = applied_jobs = match_rate = 0

st.sidebar.metric("Total Jobs", total_jobs)
st.sidebar.metric("Applications", applied_jobs)
st.sidebar.metric("Match Rate", f"{match_rate}%")

# Helper to get cover letter for a job
def get_job_cover_letter(job_instance):
    try:
        app = job_instance.applications.first()
        return app.cover_letter if app else ""
    except Exception:
        return ""

# Helper to set cover letter for a job
def set_job_cover_letter(job_instance, cl_text):
    try:
        app, created = Application.get_or_create(job=job_instance)
        app.cover_letter = cl_text
        app.save()
    except Exception as e:
        st.error(f"Error saving cover letter: {e}")

# =====================================================================
# PAGE 1: ADD JOB
# =====================================================================
if page == "📋 Add Job":
    st.header("📋 Add & Analyze Single Job")
    st.write("Paste a specific job URL or description text. The AI will evaluate your fit and draft a customized cover letter.")

    col_url, col_desc = st.columns([1, 1])
    with col_url:
        job_url = st.text_input("Job URL (LinkedIn, Naukri, or Company Career Page)")
    with col_desc:
        job_desc = st.text_area("Or Paste Job Description Text", height=120)

    if st.button("🚀 Analyze Job with AI", type="primary"):
        if not job_url and not job_desc.strip():
            st.error("Please provide either a Job URL or paste the job description text.")
        else:
            with st.spinner("Scraping and analyzing with AI model..."):
                try:
                    scraper = get_scraper()
                    matcher = get_matcher()
                    cl_gen = get_cover_letter_generator()
                    ollama = get_ollama_client()

                    # 1. Scrape / Parse
                    if job_url:
                        scraped_data = scraper.scrape_url(job_url)
                        if not scraped_data.get('description'):
                            scraped_data['description'] = job_desc or ""
                    else:
                        scraped_data = scraper.scrape_text(job_desc)

                    # 2. Extract structured details with AI if title is unknown
                    if ollama.is_available() and scraped_data.get('title') in ['Unknown Title', 'Pasted Job', 'Error', '']:
                        extracted = ollama.analyze_job(scraped_data.get('description', ''))
                        if extracted and isinstance(extracted, dict):
                            scraped_data['title'] = extracted.get('title') or scraped_data.get('title')
                            scraped_data['company'] = extracted.get('company') or scraped_data.get('company')
                            scraped_data['location'] = extracted.get('location') or scraped_data.get('location')
                            if extracted.get('salary'):
                                scraped_data['salary'] = extracted.get('salary')

                    # 3. Match against Candidate Profile
                    match_result = matcher.match_job(scraped_data)
                    match_score = int(match_result.get('score', 0))
                    reasoning = match_result.get('reasoning', '')
                    matching_skills = match_result.get('matching_skills', [])
                    missing_skills = match_result.get('missing_skills', [])

                    # 4. Generate Tailored Cover Letter
                    cover_letter = cl_gen.generate(scraped_data)

                    st.session_state.current_analysis = {
                        "url": job_url or scraped_data.get('url', ''),
                        "title": scraped_data.get('title', 'Software Developer'),
                        "company": scraped_data.get('company', 'Hiring Company'),
                        "location": scraped_data.get('location', 'Remote / Hybrid'),
                        "description": scraped_data.get('description', ''),
                        "salary": scraped_data.get('salary', 'Not specified'),
                        "score": match_score,
                        "reasoning": reasoning,
                        "matching_skills": matching_skills,
                        "missing_skills": missing_skills,
                        "cover_letter": cover_letter
                    }
                    st.success("Analysis complete!")
                except Exception as e:
                    st.error(f"Error during analysis: {e}")

    # Display Analysis Results
    if "current_analysis" in st.session_state:
        data = st.session_state.current_analysis
        st.divider()
        st.subheader("🎯 Analysis Results")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Job Title", data["title"])
        col2.metric("Company", data["company"])
        col3.metric("Location", data["location"])

        score = data["score"]
        if score >= 70:
            score_color = "green"
            score_badge = "🟢 High Match"
        elif score >= 40:
            score_color = "orange"
            score_badge = "🟠 Medium Match"
        else:
            score_color = "red"
            score_badge = "🔴 Low Match"

        col4.markdown(f"### Score: <span style='color:{score_color}'>{score}%</span><br><small>{score_badge}</small>", unsafe_allow_html=True)

        col_skills1, col_skills2 = st.columns(2)
        with col_skills1:
            st.success(f"**Matching Skills:** {', '.join(data['matching_skills']) if data['matching_skills'] else 'Profile matched general criteria'}")
        with col_skills2:
            st.warning(f"**Missing / Desired Skills:** {', '.join(data['missing_skills']) if data['missing_skills'] else 'None detected'}")

        with st.expander("🤖 AI Match Reasoning", expanded=True):
            st.write(data["reasoning"])

        with st.expander("✍️ Generated Tailored Cover Letter", expanded=True):
            data["cover_letter"] = st.text_area("Review and Edit Cover Letter", value=data["cover_letter"], height=250)

        col_btn1, col_btn2 = st.columns([1, 4])
        with col_btn1:
            if st.button("💾 Save to Pipeline", type="primary"):
                try:
                    new_job = Job.create(
                        title=data["title"],
                        company=data["company"],
                        location=data["location"],
                        url=data["url"],
                        description=data["description"],
                        salary=data["salary"],
                        status="matched" if score >= 40 else "new",
                        match_score=score,
                        match_reasoning=data["reasoning"]
                    )
                    Application.create(
                        job=new_job,
                        cover_letter=data["cover_letter"],
                        status="ready" if score >= 40 else "draft"
                    )
                    st.success("✅ Job saved to your pipeline!")
                    st.toast("Job saved to pipeline!")
                    del st.session_state.current_analysis
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to save job: {e}")

# =====================================================================
# PAGE 2: AUTO SEARCH & APPLY (AUTONOMOUS AGENT)
# =====================================================================
elif page == "🎯 Auto Search & Apply":
    st.header("🎯 Autonomous Job Search & Auto-Apply")
    st.write("Give the AI agent a target job description or role. It will **search online job openings**, **evaluate matching scores**, **write custom cover letters**, and **automatically add them to your application pipeline**.")

    col_inp1, col_inp2 = st.columns([2, 1])
    with col_inp1:
        hunt_input = st.text_area(
            "Paste Job Description or Target Role",
            placeholder="e.g. Looking for a Python Developer with experience in Django, FastAPI, PostgreSQL, and building REST APIs...",
            height=140
        )
    with col_inp2:
        max_jobs = st.slider("Number of Similar Jobs to Hunt", min_value=1, max_value=15, value=5)
        min_score = st.slider("Minimum Match Fit Score (%)", min_value=30, max_value=90, value=50)
        auto_launch = st.checkbox("Auto-open browser for pre-filling (local laptop only)", value=False)

    if st.button("⚡ Start Autonomous Hunt & Apply", type="primary"):
        if not hunt_input.strip():
            st.error("Please enter a job description or job title to search for.")
        else:
            hunter = get_auto_hunter()
            progress_container = st.container()
            results_container = st.container()
            
            with progress_container:
                st.subheader("🤖 Agent Live Activity Feed")
                status_box = st.empty()
                progress_bar = st.progress(0)

                discovered_jobs = []
                step_idx = 0

                for update in hunter.auto_hunt_and_apply(
                    job_description=hunt_input,
                    max_jobs=max_jobs,
                    min_score=min_score,
                    auto_launch_browser=auto_launch
                ):
                    step_type = update.get("step")
                    message = update.get("message", "")
                    status_box.info(message)

                    if step_type == "job_completed":
                        discovered_jobs.append(update)
                        progress_val = min(len(discovered_jobs) / max_jobs, 1.0)
                        progress_bar.progress(progress_val)
                    elif step_type == "finished":
                        progress_bar.progress(1.0)
                        status_box.success(message)

            if discovered_jobs:
                with results_container:
                    st.divider()
                    st.subheader(f"🎉 Successfully Processed ({len(discovered_jobs)}) Matching Jobs")
                    
                    for item in discovered_jobs:
                        job = item["job"]
                        score = item["score"]
                        cl = item["cover_letter"]
                        badge = "🟢" if score >= 70 else "🟠"
                        
                        with st.expander(f"{badge} {job['title']} at {job['company']} — Match: {score}%"):
                            col_a, col_b = st.columns([2, 1])
                            with col_a:
                                st.write(f"**Location:** {job.get('location', 'Remote')}")
                                if job.get('url'):
                                    st.markdown(f"**Job Link:** [{job['url']}]({job['url']})")
                                st.write(f"**AI Match Reasoning:** {job.get('match_reasoning', 'Strong candidate alignment')}")
                            with col_b:
                                st.metric("Match Score", f"{score}%")
                                
                            st.write("**Tailored Cover Letter:**")
                            st.text_area("Cover Letter", value=cl, height=150, key=f"hunt_cl_{job['title']}_{job['company']}")

# =====================================================================
# PAGE 3: JOB PIPELINE
# =====================================================================
elif page == "📊 Job Pipeline":
    st.header("📊 Job Application Pipeline")

    tabs = st.tabs(["All Jobs", "Matched", "New", "Applied", "Rejected"])
    sort_by = st.radio("Sort by", ["Highest score first", "Newest first"], horizontal=True)

    def display_jobs(query, tab_prefix="all"):
        job_list = list(query)
        if not job_list:
            st.info("No jobs found in this category.")
            return

        for job in job_list:
            score = job.match_score if job.match_score is not None else 0
            if score >= 70:
                badge = "🟢"
            elif score >= 40:
                badge = "🟠"
            else:
                badge = "🔴"

            created_str = job.created_at.strftime('%Y-%m-%d') if hasattr(job.created_at, 'strftime') else str(job.created_at)[:10]

            with st.expander(f"{badge} {job.title} at {job.company} — Match: {score}% | Status: [{job.status.upper()}] — Added: {created_str}"):
                col_left, col_right = st.columns([3, 1])

                with col_left:
                    st.write(f"**Location:** {job.location or 'Not specified'}")
                    if job.url:
                        st.markdown(f"**Application Link:** [{job.url}]({job.url})")
                    if job.match_reasoning:
                        st.write(f"**Match Analysis:** {job.match_reasoning}")

                    with st.expander("Full Job Description"):
                        st.write(job.description)

                    current_cl = get_job_cover_letter(job)
                    if current_cl:
                        with st.expander("Tailored Cover Letter"):
                            new_cl = st.text_area("Cover Letter", value=current_cl, height=180, key=f"cl_view_{tab_prefix}_{job.id}")
                            if new_cl != current_cl:
                                set_job_cover_letter(job, new_cl)

                with col_right:
                    st.write("**Quick Actions:**")

                    if st.button("✍️ Regenerate Cover Letter", key=f"gen_{tab_prefix}_{job.id}"):
                        with st.spinner("Generating with AI..."):
                            cl_gen = get_cover_letter_generator()
                            new_letter = cl_gen.generate({
                                'title': job.title,
                                'company': job.company,
                                'description': job.description
                            })
                            set_job_cover_letter(job, new_letter)
                            st.success("Cover letter updated!")
                            st.rerun()

                    if st.button("✅ Mark as Applied", key=f"app_{tab_prefix}_{job.id}"):
                        job.status = "applied"
                        job.save()
                        notifier = get_notifier()
                        notifier.notify_applied(job.title, job.company)
                        st.success("Marked as applied!")
                        st.rerun()

                    if st.button("❌ Mark as Rejected", key=f"rej_{tab_prefix}_{job.id}"):
                        job.status = "rejected"
                        job.save()
                        st.info("Marked as rejected.")
                        st.rerun()

    base_query = Job.select()
    if sort_by == "Highest score first":
        base_query = base_query.order_by(Job.match_score.desc())
    else:
        base_query = base_query.order_by(Job.created_at.desc())

    with tabs[0]:
        display_jobs(base_query, "all")
    with tabs[1]:
        display_jobs(base_query.where((Job.status == "matched") | (Job.status == "new")).where(Job.match_score >= 40), "matched")
    with tabs[2]:
        display_jobs(base_query.where(Job.status == "new"), "new")
    with tabs[3]:
        display_jobs(base_query.where(Job.status == "applied"), "applied")
    with tabs[4]:
        display_jobs(base_query.where(Job.status == "rejected"), "rejected")

# =====================================================================
# PAGE 4: APPLY
# =====================================================================
elif page == "🚀 Apply":
    st.header("🚀 Semi-Automated Application")
    st.write("Select a job to pre-fill your information in a visible browser window. You can review the filled form and click submit.")

    eligible_jobs = list(Job.select().where(Job.status != 'applied').order_by(Job.match_score.desc()))
    if not eligible_jobs:
        st.info("No active jobs ready for application. Add some jobs on the 'Add Job' page first!")
    else:
        job_options = {f"{j.title} at {j.company} (Score: {j.match_score}%)": j for j in eligible_jobs}
        selected_label = st.selectbox("Select Target Job", list(job_options.keys()))
        selected_job = job_options[selected_label]

        col_j1, col_j2 = st.columns([2, 1])
        with col_j1:
            st.subheader(f"{selected_job.title} at {selected_job.company}")
            st.write(f"**Location:** {selected_job.location or 'Not specified'}")
            st.write(f"**URL:** {selected_job.url or 'Manual Entry'}")
        with col_j2:
            st.metric("Match Score", f"{selected_job.match_score}%")

        current_cl = get_job_cover_letter(selected_job)
        cl_text = st.text_area("Cover Letter for this Application", value=current_cl, height=250)

        col_act1, col_act2, col_act3, col_act4 = st.columns(4)

        with col_act1:
            if st.button("⚡ Autonomous Auto-Apply (Auto-Submit)", type="primary"):
                if not selected_job.url or not selected_job.url.startswith("http"):
                    st.error("Please provide a valid application URL for this job.")
                else:
                    with st.spinner("🤖 Agent is applying, uploading resume.pdf, and submitting..."):
                        try:
                            filler = get_form_filler()
                            res = filler.auto_apply(selected_job.url, cover_letter=cl_text, headless=False)
                            if res.get('status') in ['submitted', 'opened', 'filled']:
                                selected_job.status = "applied"
                                selected_job.save()
                                set_job_cover_letter(selected_job, cl_text)

                                notifier = get_notifier()
                                notifier.notify_applied(selected_job.title, selected_job.company)

                                st.balloons()
                                st.success(f"🎉 Successfully applied to {selected_job.title} at {selected_job.company}!")
                                st.info(f"Details submitted: {', '.join(res.get('fields_filled', []))} | Resume: attached")
                                time.sleep(1.5)
                                st.rerun()
                            else:
                                st.warning(f"Application status: {res.get('message')}")
                        except Exception as e:
                            st.error(f"Auto-apply error: {e}")

        with col_act2:
            if st.button("🌐 Open & Pre-fill (Manual Submit)"):
                if not selected_job.url or not selected_job.url.startswith("http"):
                    st.error("Please provide a valid application URL for this job.")
                else:
                    with st.spinner("Launching visible browser and filling form fields..."):
                        try:
                            filler = get_form_filler()
                            res = filler.open_and_prefill(selected_job.url, cover_letter=cl_text)
                            st.success("✅ Browser opened! Review the form in your browser window.")
                        except Exception as e:
                            st.error(f"Error: {e}")

        with col_act3:
            if st.button("✍️ Regenerate Cover Letter"):
                with st.spinner("Generating fresh cover letter..."):
                    cl_gen = get_cover_letter_generator()
                    new_cl = cl_gen.generate({
                        'title': selected_job.title,
                        'company': selected_job.company,
                        'description': selected_job.description
                    })
                    set_job_cover_letter(selected_job, new_cl)
                    st.rerun()

        with col_act4:
            if st.button("🎉 Mark as Applied"):
                selected_job.status = "applied"
                selected_job.save()
                set_job_cover_letter(selected_job, cl_text)

                notifier = get_notifier()
                notifier.notify_applied(selected_job.title, selected_job.company)

                st.balloons()
                st.success(f"Marked as applied to {selected_job.title} at {selected_job.company}!")
                time.sleep(1.5)
                st.rerun()

# =====================================================================
# PAGE 5: SETTINGS
# =====================================================================
elif page == "⚙️ Settings":
    st.header("⚙️ Settings & Configuration")

    profile = load_profile()
    keywords = load_keywords()
    settings = load_settings()

    # --- Profile Section ---
    st.subheader("👤 Candidate Profile")
    with st.form("profile_form"):
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            name = st.text_input("Full Name", value=profile.get('name', ''))
            email = st.text_input("Email", value=profile.get('email', ''))
            phone = st.text_input("Phone Number", value=profile.get('phone', ''))
            location = st.text_input("Location / City", value=profile.get('location', ''))
        with col_p2:
            current_title = st.text_input("Current Title", value=profile.get('current_title', ''))
            experience_years = st.number_input("Years of Experience", value=int(profile.get('experience_years', 2)), min_value=0, max_value=50)
            linkedin = st.text_input("LinkedIn Profile URL", value=profile.get('linkedin_url', ''))
            resume_path = st.text_input("Resume PDF Path", value=profile.get('resume_path', ''))

        skills_list = profile.get('skills', [])
        skills_text = st.text_area("Skills (comma-separated)", value=", ".join(skills_list) if isinstance(skills_list, list) else str(skills_list))
        summary = st.text_area("Professional Summary", value=profile.get('summary', ''), height=100)

        if st.form_submit_button("💾 Save Profile", type="primary"):
            profile['name'] = name
            profile['email'] = email
            profile['phone'] = phone
            profile['location'] = location
            profile['current_title'] = current_title
            profile['experience_years'] = experience_years
            profile['linkedin_url'] = linkedin
            profile['resume_path'] = resume_path
            profile['summary'] = summary
            profile['skills'] = [s.strip() for s in skills_text.split(",") if s.strip()]

            st.session_state["user_profile"] = profile
            save_yaml(os.path.join(get_project_root(), "config", "profile.yaml"), profile)
            st.success("Candidate profile updated successfully!")

    st.divider()

    # --- Keywords Section ---
    st.subheader("🎯 Job Search Criteria & Filters")
    with st.form("keywords_form"):
        target_titles = keywords.get('target_titles', [])
        target_text = st.text_area("Target Job Titles (comma-separated)", value=", ".join(target_titles) if isinstance(target_titles, list) else str(target_titles))

        locations = keywords.get('preferred_locations', [])
        loc_text = st.text_area("Preferred Locations (comma-separated)", value=", ".join(locations) if isinstance(locations, list) else str(locations))

        excludes = keywords.get('exclude_keywords', [])
        exclude_text = st.text_area("Exclude Keywords (e.g. Senior, Lead, 10+ years)", value=", ".join(excludes) if isinstance(excludes, list) else str(excludes))

        min_score = st.slider("Minimum Match Score (%) to Notify", min_value=10, max_value=100, value=int(keywords.get('min_match_score', 60)))

        if st.form_submit_button("💾 Save Search Criteria", type="primary"):
            keywords['target_titles'] = [s.strip() for s in target_text.split(",") if s.strip()]
            keywords['preferred_locations'] = [s.strip() for s in loc_text.split(",") if s.strip()]
            keywords['exclude_keywords'] = [s.strip() for s in exclude_text.split(",") if s.strip()]
            keywords['min_match_score'] = min_score

            st.session_state["user_keywords"] = keywords
            save_yaml(os.path.join(get_project_root(), "config", "keywords.yaml"), keywords)
            st.success("Job search criteria updated!")

    st.divider()

    # --- AI Engine Configuration Section ---
    st.subheader("🤖 AI Engine Configuration (Local & Cloud)")
    st.write("The agent works **100% locally with Ollama** on your laptop. For **Streamlit Cloud deployment**, you can enter a free Groq or Gemini API key below:")

    with st.form("ai_form"):
        ai_cfg = settings.get('ai', {})
        col_k1, col_k2 = st.columns(2)
        with col_k1:
            groq_key = st.text_input("Groq API Key (Free, fast Llama 3.3)", value=ai_cfg.get('groq_api_key', ''), type="password", help="Get free key at console.groq.com/keys")
            st.caption("👉 [Get a free Groq API key (Instant)](https://console.groq.com/keys)")
        with col_k2:
            gemini_key = st.text_input("Google Gemini API Key (Free tier)", value=ai_cfg.get('gemini_api_key', ''), type="password", help="Get free key at aistudio.google.com/app/apikey")
            st.caption("👉 [Get a free Gemini API key](https://aistudio.google.com/app/apikey)")

        ollama_model = st.text_input("Local Ollama Model", value=settings.get('ollama', {}).get('model', 'phi3:mini'))

        if st.form_submit_button("💾 Save AI Settings", type="primary"):
            st.session_state['groq_api_key'] = groq_key
            st.session_state['gemini_api_key'] = gemini_key
            if 'ai' not in settings:
                settings['ai'] = {}
            settings['ai']['groq_api_key'] = groq_key
            settings['ai']['gemini_api_key'] = gemini_key
            if 'ollama' not in settings:
                settings['ollama'] = {}
            settings['ollama']['model'] = ollama_model

            try:
                save_yaml(os.path.join(get_project_root(), "config", "settings.yaml"), settings)
            except Exception:
                pass
            st.cache_resource.clear()
            st.success("AI engine settings saved! Reloading...")
            time.sleep(1)
            st.rerun()

    # Test AI
    col_ai1, col_ai2 = st.columns(2)
    with col_ai1:
        st.info(f"**Active AI Engine:** {st.session_state.ai_status} ({st.session_state.ai_provider})")
    with col_ai2:
        if st.button("🧪 Test Active AI Model"):
            with st.spinner("Generating AI test response..."):
                try:
                    ollama = get_ollama_client()
                    response = ollama.generate("Say 'Hello! Your AI Job Agent is fully operational.' in under 15 words.")
                    st.success(f"AI Response: {response}")
                except Exception as e:
                    st.error(f"AI Test failed: {e}")

    st.divider()

    # --- Twilio SMS Section ---
    st.subheader("📱 Twilio SMS Notifications")
    with st.form("twilio_form"):
        twilio_cfg = settings.get('twilio', {})
        sid = st.text_input("Twilio Account SID", value=twilio_cfg.get('account_sid', ''), type="password")
        token = st.text_input("Twilio Auth Token", value=twilio_cfg.get('auth_token', ''), type="password")
        from_num = st.text_input("Twilio Virtual Number (From)", value=twilio_cfg.get('from_number', ''))
        to_num = st.text_input("Your Mobile Number (To)", value=twilio_cfg.get('to_number', ''))

        col_t1, col_t2 = st.columns(2)
        with col_t1:
            if st.form_submit_button("💾 Save Twilio Settings"):
                if 'twilio' not in settings:
                    settings['twilio'] = {}
                settings['twilio']['account_sid'] = sid
                settings['twilio']['auth_token'] = token
                settings['twilio']['from_number'] = from_num
                settings['twilio']['to_number'] = to_num
                save_yaml(os.path.join(get_project_root(), "config", "settings.yaml"), settings)
                st.success("Twilio settings saved!")
        with col_t2:
            if st.form_submit_button("📩 Send Test SMS"):
                notifier = get_notifier()
                if notifier.test_connection():
                    st.success("Test notification triggered!")
                else:
                    st.info("Twilio live credentials not configured. Notification was logged locally.")
