# Chromium + Playwright + deps already baked in
FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

WORKDIR /app

# If you only need requests, keep this minimal
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your script (rename to app.py for simplicity)
COPY solscan_playwright.py /app/app.py

ENV PYTHONUNBUFFERED=1

# URL comes from Render env var
CMD ["bash","-lc","python app.py --url \"$URL\""]
