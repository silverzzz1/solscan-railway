# solscan_playwright.py
# Headless Playwright script to monitor buy transactions on CabalSpy
# QUIET MODE: Only shows output when finding coins over 20 SOL

import asyncio
import re
import time
import argparse
from collections import defaultdict
from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PWTimeoutError

# Desktop popup for Windows
import threading, ctypes
def desktop_popup(title: str, message: str):
    def _show():
        try:
            # 0x00001040 = MB_OK | MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x00001040)
        except Exception:
            pass
    threading.Thread(target=_show, daemon=True).start()

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
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Only show initial startup message
        print(f"🚀 Starting quiet monitor for {url}")
        print("📊 Monitoring for buys over 20 SOL... (terminal will stay quiet until alerts)")
        print("=" * 70)
        
        await page.goto(url, timeout=60000)

        alert_timestamps = {}
        ALERT_COOLDOWN_SECONDS = 3600  # 1 hour
        cycle_count = 0

        while True:
            cycle_count += 1
            
            # Show a simple "alive" indicator every 10 cycles (10 minutes)
            if cycle_count % 10 == 0:
                print(f"⏰ Still monitoring... ({cycle_count} checks completed)")

            # Reload page quietly
            try:
                await page.reload(wait_until="domcontentloaded", timeout=60000)
            except PWTimeoutError:
                # Silent recovery attempts
                try:
                    await page.evaluate("location.reload()")
                    await page.wait_for_load_state("domcontentloaded", timeout=60000)
                except Exception:
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    except Exception:
                        # Only show error if it's persistent
                        if cycle_count % 5 == 0:  # Show error every 5 failed attempts
                            print(f"⚠️  Connection issues detected (attempt {cycle_count})")
                        await page.wait_for_timeout(5000)
                        continue

            await page.wait_for_timeout(4000)

            try:
                table = await page.query_selector("#transactions-table")
                rows = await table.query_selector_all("tr")
            except Exception:
                # Silent continue - don't spam about missing table
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

            # Only process and show output if we have transactions
            if buy_transactions:
                grouped_by_token = defaultdict(list)
                for tx in buy_transactions:
                    grouped_by_token[tx['token']].append(tx)

                # Only show alerts for high volume buys
                alerts_triggered = False
                
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
                            if current_group_total > 20:
                                now = time.time()
                                if not alert_timestamps.get(token) or (now - alert_timestamps[token] > ALERT_COOLDOWN_SECONDS):
                                    if not alerts_triggered:
                                        print(f"\n🚨 HIGH VOLUME ALERT - {time.strftime('%Y-%m-%d %H:%M:%S')}")
                                        print("=" * 70)
                                        alerts_triggered = True
                                    
                                    print(f"💰 {token}: {current_group_total:.2f} SOL (THRESHOLD EXCEEDED!)")
                                    desktop_popup(
                                        "High Volume Buy Alert!",
                                        f"{token}: {current_group_total:.2f} SOL"
                                    )
                                    alert_timestamps[token] = now
                            
                            group_start_time = tx['time']
                            current_group_total = tx['amount']

                    # Check final group
                    if current_group_total > 20:
                        now = time.time()
                        if not alert_timestamps.get(token) or (now - alert_timestamps[token] > ALERT_COOLDOWN_SECONDS):
                            if not alerts_triggered:
                                print(f"\n🚨 HIGH VOLUME ALERT - {time.strftime('%Y-%m-%d %H:%M:%S')}")
                                print("=" * 70)
                                alerts_triggered = True
                            
                            print(f"💰 {token}: {current_group_total:.2f} SOL (THRESHOLD EXCEEDED!)")
                            desktop_popup(
                                "High Volume Buy Alert!",
                                f"{token}: {current_group_total:.2f} SOL"
                            )
                            alert_timestamps[token] = now

                if alerts_triggered:
                    print("=" * 70)
                    print("🔄 Returning to quiet monitoring...\n")

            # Wait 1 minute silently
            await page.wait_for_timeout(60000)

        await browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quiet Playwright buy monitor - only shows 20+ SOL alerts")
    parser.add_argument("--url", type=str, required=True, help="Target wallet URL")
    args = parser.parse_args()

    asyncio.run(monitor_buys(args.url))
