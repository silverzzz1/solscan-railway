FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# bring all code in
COPY . /app

ENV PYTHONUNBUFFERED=1

# URL is read from env var URL
CMD ["bash","-lc","python solscan_railway.py --url \"$URL\""]
