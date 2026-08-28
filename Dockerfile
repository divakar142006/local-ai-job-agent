FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies & Xvfb virtual display for Playwright
RUN apt-get update && apt-get install -y \
    xvfb \
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

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium with all OS dependencies
RUN playwright install chromium --with-deps

COPY . .

RUN chmod +x entrypoint.sh

EXPOSE 8501

CMD ["./entrypoint.sh"]
