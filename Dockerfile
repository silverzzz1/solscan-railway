FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy your whole repo (so whatever the script is named, it’s there)
COPY . /app

ENV PYTHONUNBUFFERED=1

# run YOUR actual file name; change it if different
CMD ["bash","-lc","python solscan_railway.py --url \"$URL\""]
