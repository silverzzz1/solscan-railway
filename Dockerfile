# Playwright + Chromium preinstalled (no font/apt hell)
FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bring your code in
COPY solscan_railway.py /app/app.py

# Better logging
ENV PYTHONUNBUFFERED=1

# URL comes from Render env var “URL”
CMD ["bash","-lc","python app.py --url \"$URL\""]
