# solscan_railway.py
# Headless Playwright script to monitor buy transactions on CabalSpy

import asyncio
import re
import time
import argparse
import os
import requests
from collections import defaultdict
from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PWTimeoutError

# --- Windows desktop popup (local fallback) ---
import threading, ctypes
def desktop_popup(title: str, message: str):
    def _show():
        try:
            # 0x00001040 = MB_OK | MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x00001040)
        except Exception:
            pass
    threading.Thread(target=_show, daemon=True).start()

# --- Discord webhook for cloud alerts ---
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "").strip()

def parse_time_ago(time_str: str) -> int:
    """
    Converts strings like "1m ago", "5s ago", "2h ago" into minutes.
    """
    if not time_str:
        return 999
    numbers = re.findall(r'\d+', time_str)
    if not numbers:
        return 999
    value = int(numbers[0])
    if 's' in time_str:
        return 0
    if 'm' in time_str:
        return value
    if 'h' in time_str:
        return value * 60
    if 'd' in time_str:
        return value * 1440
    return value

async def monitor_buys(url: str):
    async with async_playwright() as p:
        # >>> Modified line: add --no-sandbox and --disable-dev-shm-usage <<<
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page()
        print(f"Navigating to {url}")
        await page.goto(url, timeout=60000)

        alert_timestamps = {}
        ALERT_COOLDOWN_SECONDS = 3600  # 1 hour

        while True:
            print("\n" + "="*50)
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Refreshing page and checking for new buys...")

            # Robust reload so timeouts don't crash the script
            try:
                await page.reload(wait_until="domcontentloaded", timeout=60000)
            except PWTimeoutError:
                print("Reload timed out; attempting recovery without exiting...")
                # Try a gentle JS refresh first
                try:
                    await page.evaluate("location.reload()")
                    await page.wait_for_load_state("domcontentloaded", timeout=60000)
                except Exception:
                    # Fall back to a hard goto on the same URL
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    except Exception as e:
                        print(f"Secondary reload failed: {e}. Will retry next cycle.")
                        await page.wait_for_timeout(5000)
                        print("\nWaiting 2 minutes before next refresh...")
                        await page.wait_for_timeout(120000)
                        continue

            await page.wait_for_timeout(4000)  # wait for JS to load table

            try:
                table = await page.query_selector("#transactions-table")
                rows = await table.query_selector_all("tr")
            except Exception:
                print("ERROR: Could not find transaction table.")
                print("\nWaiting 2 minutes before next refresh...")
                await page.wait_for_timeout(120000)
                continue

            buy_transactions = []
            for row in rows:
                try:
                    if not await row.query_selector(".buy-text"):
                        continue

                    cells = await row.query_selector_all("td")
                    if len(cells) < 5:
                        continue

                    token_name = (await cells[1].inner_text()).strip().upper()
                    amount_str = (await cells[3].inner_text()).replace(" SOL", "").replace(",", ".")
                    amount = float(amount_str)
                    time_ago_str = await cells[4].inner_text()
                    minutes_ago = parse_time_ago(time_ago_str)

                    buy_transactions.append({
                        "token": token_name,
                        "amount": amount,
                        "time": minutes_ago
                    })
                except Exception:
                    continue

            if not buy_transactions:
                print("No 'buy' transactions found.")
            else:
                grouped_by_token = defaultdict(list)
                for tx in buy_transactions:
                    grouped_by_token[tx['token']].append(tx)

                print("--- Aggregated BUY Transactions (within 8-minute windows) ---")

                for token, transactions in grouped_by_token.items():
                    transactions.sort(key=lambda x: x['time'], reverse=True)
                    if not transactions:
                        continue

                    current_group_total = 0
                    group_start_time = transactions[0]['time']

                    for tx in transactions:
                        if tx['time'] - group_start_time <= 3:
                            current_group_total += tx['amount']
                        else:
                            if current_group_total > 0:
                                print(f"  - Token: {token:<10} | Total Buy: {current_group_total:.2f} SOL")
                                if current_group_total > 20:
                                    now = time.time()
                                    if not alert_timestamps.get(token) or (now - alert_timestamps[token] > ALERT_COOLDOWN_SECONDS):
                                        print(f"!!! ALERT: High volume buy for {token} !!!")
                                        if DISCORD_WEBHOOK:
                                            try:
                                                requests.post(
                                                    DISCORD_WEBHOOK,
                                                    json={"content": f"High Volume Buy — {token}: {current_group_total:.2f} SOL"},
                                                    timeout=8
                                                )
                                            except Exception:
                                                pass
                                        else:
                                            desktop_popup(
                                                "High Volume Buy",
                                                f"{token}: {current_group_total:.2f} SOL (>=20)"
                                            )
                                        alert_timestamps[token] = now
                            group_start_time = tx['time']
                            current_group_total = tx['amount']

                    if current_group_total > 0:
                        print(f"  - Token: {token:<10} | Total Buy: {current_group_total:.2f} SOL")
                        if current_group_total > 20:
                            now = time.time()
                            if not alert_timestamps.get(token) or (now - alert_timestamps[token] > ALERT_COOLDOWN_SECONDS):
                                print(f"!!! ALERT: High volume buy for {token} !!!")
                                if DISCORD_WEBHOOK:
                                    try:
                                        requests.post(
                                            DISCORD_WEBHOOK,
                                            json={"content": f"High Volume Buy — {token}: {current_group_total:.2f} SOL"},
                                            timeout=8
                                        )
                                    except Exception:
                                        pass
                                else:
                                    desktop_popup(
                                        "High Volume Buy",
                                        f"{token}: {current_group_total:.2f} SOL (>=20)"
                                    )
                                alert_timestamps[token] = now

            print("\nWaiting 2 minutes before next refresh...")
            await page.wait_for_timeout(120000)  # 2 minutes

        await browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Headless Playwright buy monitor")
    parser.add_argument("--url", type=str, required=True, help="Target wallet URL")
    args = parser.parse_args()

    asyncio.run(monitor_buys(args.url))
