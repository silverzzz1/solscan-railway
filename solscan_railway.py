# Headless Playwright script to monitor buy transactions on CabalSpy
# QUIET MODE: Only prints when finds >=20 SOL grouped buys and sends a desktop popup (local) or just logs in cloud.

import asyncio
import re
import time
import argparse
import os
import requests
from collections import defaultdict
from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PWTimeoutError

# Local Windows popup (ignored in cloud)
import threading, ctypes
def desktop_popup(title: str, message: str):
    def _show():
        try:
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x00001040)
        except Exception:
            pass
    threading.Thread(target=_show, daemon=True).start()

def parse_time_ago(time_str: str) -> int:
    """Convert '5s ago', '2m ago', '1h ago' → minutes."""
    if not time_str:
        return 999
    nums = re.findall(r'\d+', time_str)
    if not nums:
        return 999
    v = int(nums[0])
    if 's' in time_str:
        return 0
    if 'm' in time_str:
        return v
    if 'h' in time_str:
        return v * 60
    if 'd' in time_str:
        return v * 1440
    return v

async def monitor_buys(url: str):
    async with async_playwright() as p:
        # IMPORTANT for Render/containers
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page()

        print(f"🚀 Starting quiet monitor for {url}")
        print("📊 Monitoring for buys over 20 SOL... (terminal stays quiet until alerts)")
        print("=" * 70)

        await page.goto(url, timeout=60000)

        alert_timestamps = {}
        ALERT_COOLDOWN_SECONDS = 3600  # 1 hour
        cycle_count = 0

        while True:
            cycle_count += 1

            # “alive” ping every 10 minutes
            if cycle_count % 10 == 0:
                print(f"⏰ Still monitoring... ({cycle_count} checks completed)")

            # Reload page, with recovery
            try:
                await page.reload(wait_until="domcontentloaded", timeout=60000)
            except PWTimeoutError:
                try:
                    await page.evaluate("location.reload()")
                    await page.wait_for_load_state("domcontentloaded", timeout=60000)
                except Exception:
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    except Exception:
                        if cycle_count % 5 == 0:
                            print(f"⚠️  Connection issues detected (attempt {cycle_count})")
                        await page.wait_for_timeout(5000)
                        continue

            await page.wait_for_timeout(4000)  # let JS populate

            # Grab rows
            try:
                table = await page.query_selector("#transactions-table")
                rows = await table.query_selector_all("tr")
            except Exception:
                # stay quiet; try next loop
                await page.wait_for_timeout(60000)
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

                    buy_transactions.append({"token": token_name, "amount": amount, "time": minutes_ago})
                except Exception:
                    continue

            if buy_transactions:
                grouped = defaultdict(list)
                for tx in buy_transactions:
                    grouped[tx["token"]].append(tx)

                alerts_triggered = False

                for token, txs in grouped.items():
                    txs.sort(key=lambda x: x["time"], reverse=True)
                    if not txs:
                        continue

                    current_total = 0.0
                    group_start = txs[0]["time"]

                    for tx in txs:
                        if tx["time"] - group_start <= 3:
                            current_total += tx["amount"]
                        else:
                            if current_total > 20:
                                now = time.time()
                                if not alert_timestamps.get(token) or (now - alert_timestamps[token] > ALERT_COOLDOWN_SECONDS):
                                    if not alerts_triggered:
                                        print(f"\n🚨 HIGH VOLUME ALERT - {time.strftime('%Y-%m-%d %H:%M:%S')}")
                                        print("=" * 70)
                                        alerts_triggered = True
                                    print(f"💰 {token}: {current_total:.2f} SOL (THRESHOLD EXCEEDED!)")
                                    desktop_popup("High Volume Buy Alert!", f"{token}: {current_total:.2f} SOL")
                                    alert_timestamps[token] = now
                            group_start = tx["time"]
                            current_total = tx["amount"]

                    # final group
                    if current_total > 20:
                        now = time.time()
                        if not alert_timestamps.get(token) or (now - alert_timestamps[token] > ALERT_COOLDOWN_SECONDS):
                            if not alerts_triggered:
                                print(f"\n🚨 HIGH VOLUME ALERT - {time.strftime('%Y-%m-%d %H:%M:%S')}")
                                print("=" * 70)
                                alerts_triggered = True
                            print(f"💰 {token}: {current_total:.2f} SOL (THRESHOLD EXCEEDED!)")
                            desktop_popup("High Volume Buy Alert!", f"{token}: {current_total:.2f} SOL")
                            alert_timestamps[token] = now

                if alerts_triggered:
                    print("=" * 70)
                    print("🔄 Returning to quiet monitoring...\n")

            # Sleep 1 minute
            await page.wait_for_timeout(60000)

        await browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quiet Playwright buy monitor - only shows 20+ SOL alerts")
    parser.add_argument("--url", type=str, required=True, help="Target wallet URL")
    args = parser.parse_args()
    asyncio.run(monitor_buys(args.url))
