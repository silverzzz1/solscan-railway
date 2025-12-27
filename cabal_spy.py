import asyncio
import re
import time
import os
import aiohttp
import threading, ctypes
from collections import defaultdict
from playwright.async_api import async_playwright

# --- CONFIG ---
WALLETS_MAP = {
    "2fg5QD1eD7rzNNCsvnhmXFm5hqNgwTTG8p7kQ6f3rx6f": "Whale 1",
    "8rvAsDKeAcEjEkiZMug9k8v1y8mW6gQQiMobd89Uy7qR": "Whale 2"
}
ALERT_THRESHOLD = 40.0
COOLDOWN = 3600 

# Telegram Credentials
BOT_TOKEN = "7847691278:AAE9ZSubv0MVn3S9sMT79X-b79TLCZ1-qVM"
CHAT_ID = "-4637484974"

def desktop_popup(title, message):
    """Windows-only popup for when you run it locally."""
    if os.name == 'nt': 
        def _show():
            try: ctypes.windll.user32.MessageBoxW(0, message, title, 0x00001040)
            except: pass
        threading.Thread(target=_show, daemon=True).start()

async def send_telegram(message):
    """Sends alert to your Telegram group."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as session:
        try:
            payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
            await session.post(url, json=payload)
        except Exception as e:
            print(f"Telegram failed: {e}")

def parse_time_ago(time_str: str) -> int:
    nums = re.findall(r'\d+', time_str or "")
    if not nums: return 999
    val = int(nums[0])
    if 's' in time_str: return 0
    if 'm' in time_str: return val
    if 'h' in time_str: return val * 60
    return val

async def monitor_single_wallet(browser, address, nickname):
    context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    page = await context.new_page()
    alert_timestamps = {}
    url = f"https://cabalspy.xyz/wallet.php?wallet={address}"
    
    while True:
        try:
            print(f"[{time.strftime('%H:%M:%S')}] Scanning {nickname}...")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000) 

            rows = await page.query_selector_all("tr")
            active_totals = defaultdict(float)

            for row in rows:
                txt = await row.inner_text()
                if "BUY" in txt.upper():
                    cells = await row.query_selector_all("td")
                    if len(cells) >= 5:
                        token = (await cells[1].inner_text()).split('\n')[0].strip()
                        amt_raw = await cells[3].inner_text()
                        amt = float(re.sub(r'[^\d.]', '', amt_raw.replace(',', '.')))
                        minutes = parse_time_ago(await cells[4].inner_text())
                        if minutes <= 8: active_totals[token] += amt

            for token, total in active_totals.items():
                if total >= ALERT_THRESHOLD:
                    now = time.time()
                    if token not in alert_timestamps or (now - alert_timestamps[token] > COOLDOWN):
                        msg = f"🚨 <b>{nickname}</b> bought <b>{token}</b>\nTotal: {total:.2f} SOL"
                        desktop_popup("WHALE ALERT", msg.replace("<b>", "").replace("</b>", ""))
                        await send_telegram(msg)
                        alert_timestamps[token] = now
        except Exception as e:
            print(f"Error: {e}")
        await asyncio.sleep(60)

async def main():
    async with async_playwright() as p:
        is_linux = os.name != 'nt' # Render is Linux, your PC is Windows
        browser = await p.chromium.launch(
            headless=is_linux, 
            args=["--no-sandbox", "--disable-dev-shm-usage"] if is_linux else []
        )
        tasks = [monitor_single_wallet(browser, addr, nick) for addr, nick in WALLETS_MAP.items()]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
