FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install browsers via module form (works even if CLI isn't on PATH)
RUN python -m playwright install chromium || true

COPY solscan_railway.py .

ENV URL=""
ENV DISCORD_WEBHOOK=""

CMD ["bash", "-lc", "python solscan_railway.py --url \"$URL\""]
