# Use a standard Python image
FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# IMPORTANT: Install Playwright's browser binaries and dependencies
RUN playwright install --with-deps chromium

# Copy the rest of your application code into the container
COPY . .

# The command to run your script (Render will use its own Start Command)
CMD ["python", "cabal_spy.py"]
