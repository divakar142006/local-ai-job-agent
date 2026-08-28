#!/bin/bash
set -e

echo "========================================================="
echo "🚀 Starting 24/7 Autonomous Job Application Cloud Agent"
echo "Candidate: Kantubothu Divakara Rao (divakantubothu@gmail.com)"
echo "========================================================="

# 1. Start the 24/7 Autonomous Job Agent background process
python run_agent.py &

# 2. Start the Streamlit Dashboard (accessible from anywhere in the world)
streamlit run app.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true
