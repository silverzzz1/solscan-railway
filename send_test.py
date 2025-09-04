# send_test.py
import os
import requests

# Grab webhook from environment
webhook = os.getenv("DISCORD_WEBHOOK")

if not webhook:
    raise ValueError("❌ No DISCORD_WEBHOOK set in environment!")

# Simple payload
data = {
    "content": "✅ Hello from Render! Your webhook is working."
}

# Send to Discord
resp = requests.post(webhook, json=data)

if resp.status_code == 204:
    print("✅ Message sent successfully to Discord.")
else:
    print(f"❌ Failed to send, status: {resp.status_code}, response: {resp.text}")
