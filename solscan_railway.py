# Headless Playwright monitor (quiet) — sends Discord alerts for >=40 SOL grouped buys

import asyncio
import re
import time
import argparse
import os
import requests
from collections import defaultdict
from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PWTimeoutError

# Optional Discord webhook for cloud alerts
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "").strip()

def parse_time_ago(time_str: str) -> int:
    """Convert '5s ago', '2m ago', '1h ago' → minutes."""
    if not time_str:
        return 999
    m = re.search(r'(\d+)', time_str)
    if not m:
        return 999
    v = int(m.group(1))
    if 's' in time_str: return 0
    if 'm' in time_str: return v
    if 'h' in time_str: return v * 60
    if 'd' in time_str: return v * 1440
    return v

def send_discord(msg: str):
    if not DISCORD_WEBHOOK:
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=8)
    except Exception:
        pass  # stay quiet if webhook fails

async def monitor_buys(url: str):
    async with async_playwright() as p:
        # THIS is what you asked for — where to put the flags
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page()

        print(f"🚀 Starting quiet monitor for {url}")
        print("📊 Monitoring for buys over 40 SOL... (quiet until alerts)")
        print("=" * 70)

        await page.goto(url, timeout=60000)

        alert_timestamps = {}
        ALERT_COOLDOWN_SECONDS = 3600  # 1 hour
        cycle_count = 0

        while True:
            cycle_count += 1

            # “alive” ping every 10 minutes
            if cycle_count % 10 == 0:
                print(f"⏰ Still monitoring... ({cycle_count} checks)")

            # Reload with recovery
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
                            print(f"⚠️  Connection issues (attempt {cycle_count})")
                        await page.wait_for_timeout(5000)
                        continue

            await page.wait_for_timeout(4000)  # let JS populate

            # Pull rows
            try:
                table = await page.query_selector("#transactions-table")
                rows = await table.query_selector_all("tr")
            except Exception:
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

                    token = (await cells[1].inner_text()).strip().upper()
                    amount_str = (await cells[3].inner_text()).replace(" SOL", "").replace(",", ".")
                    amount = float(amount_str)
                    time_ago_str = await cells[4].inner_text()
                    minutes_ago = parse_time_ago(time_ago_str)

                    buy_transactions.append({"token": token, "amount": amount, "time": minutes_ago})
                except Exception:
                    continue

            # Only do work if we have buys
            if buy_transactions:
                grouped = defaultdict(list)
                for tx in buy_transactions:
                    grouped[tx["token"]].append(tx)

                any_alert = False

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
                            if current_total > 40:
                                now = time.time()
                                if not alert_timestamps.get(token) or (now - alert_timestamps[token] > ALERT_COOLDOWN_SECONDS):
                                    if not any_alert:
                                        print(f"\n🚨 HIGH VOLUME ALERT - {time.strftime('%Y-%m-%d %H:%M:%S')}")
                                        print("=" * 70)
                                        any_alert = True
                                    msg = f"💰 {token}: {current_total:.2f} SOL (>=40)"
                                    print(msg)
                                    send_discord(f"High Volume Buy — {msg}")
                                    alert_timestamps[token] = now
                            group_start = tx["time"]
                            current_total = tx["amount"]

                    # Check final group
                    if current_total > 40:
                        now = time.time()
                        if not alert_timestamps.get(token) or (now - alert_timestamps[token] > ALERT_COOLDOWN_SECONDS):
                            if not any_alert:
                                print(f"\n🚨 HIGH VOLUME ALERT - {time.strftime('%Y-%m-%d %H:%M:%S')}")
                                print("=" * 70)
                                any_alert = True
                            msg = f"💰 {token}: {current_total:.2f} SOL (>=40)"
                            print(msg)
                            send_discord(f"High Volume Buy — {msg}")
                            alert_timestamps[token] = now

                if any_alert:
                    print("=" * 70)
                    print("🔄 Back to quiet monitoring...\n")

            # Sleep 1 minute
            await page.wait_for_timeout(60000)

        await browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quiet Playwright buy monitor - only shows 40+ SOL alerts")
    parser.add_argument("--url", type=str, required=True, help="Target wallet URL")
    args = parser.parse_args()
    asyncio.run(monitor_buys(args.url))

