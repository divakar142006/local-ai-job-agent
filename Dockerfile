FROM python:3.11-slim

# Install system dependencies for Playwright Chromium
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gnupg \
    procps \
    git \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser binaries
RUN playwright install chromium --with-deps

# Copy application files
COPY . .

# Ensure executable entrypoint script
RUN chmod +x entrypoint.sh

# Expose Streamlit port
EXPOSE 8501

# Run both the 24/7 Autonomous Agent and the Dashboard
CMD ["./entrypoint.sh"]
