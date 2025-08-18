# ✅ Works on Railway. Installs Python deps + Chromium for Playwright.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System libs Chromium needs
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxdamage1 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 libxshmfence1 \
    ca-certificates wget curl gnupg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser (Chromium) + its OS deps
RUN python -m playwright install --with-deps chromium

# Your script
COPY solscan_railway.py .

# Start: read URL from env, add no-sandbox flags (required on Railway)
CMD ["bash","-lc","python solscan_railway.py --url \"${URL}\""]
