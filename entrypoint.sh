#!/bin/bash
set -e

echo "========================================================="
echo "🚀 Starting 24/7 Autonomous Job Application Cloud Agent"
echo "Candidate: Kantubothu Divakara Rao (divakantubothu@gmail.com)"
echo "========================================================="

# 1. Start Xvfb Virtual Framebuffer Display in background
Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 &
export DISPLAY=:99

# 2. Start the 24/7 Autonomous Job Agent background process
python run_agent.py &

# 3. Start the Streamlit Dashboard
streamlit run app.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true
