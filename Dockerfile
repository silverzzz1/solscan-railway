FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# bring ALL repo files in (avoids filename mismatch issues)
COPY . /app

ENV PYTHONUNBUFFERED=1

# run YOUR script by its actual name
CMD ["bash","-lc","python solscan_railway.py --url \"$URL\""]
