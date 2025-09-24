import time
import re
import os
from collections import Counter
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# --- CONFIGURATION ---
CABALSPY_URL = "https://cabalspy.xyz/dashboard.php"
SCAN_INTERVAL_SECONDS = 160  # Check every 160 seconds
MIN_KOL_COUNT = 22           # Alert threshold for KOL count

# --- FILE PATH FOR SERVER ---
ALERT_FILE = "alerted_tokens.txt"

# --- ALERT FILE LOGIC ---
def load_alerted_tokens():
    if not os.path.exists(ALERT_FILE):
        return set()
    with open(ALERT_FILE, 'r') as f:
        return {line.strip().lower() for line in f}

def save_alerted_token(token_name):
    with open(ALERT_FILE, 'a') as f:
        f.write(f"{token_name.lower()}\n")

# --- SERVER-FRIENDLY ALERTING VIA PRINTING TO LOGS ---
def trigger_alert_and_save(token_name, kol_count, market_cap, dev_bought):
    print("\n" + "="*40)
    print("🚨🚨🚨 NEW HIGH KOL TOKEN DETECTED! 🚨🚨🚨")
    print(f"    Token: {token_name}")
    print(f"    KOLs: {kol_count}")
    print(f"    Market Cap: {market_cap}")
    print(f"    Dev Bought: {dev_bought}")
    print("="*40 + "\n")
    try:
        save_alerted_token(token_name)
        print(f"✅ Saved '{token_name}' to alert history.")
    except Exception as e:
        print(f"❌ Could not save alert to file: {e}")

# --- TOKEN DATA EXTRACTION ---
def extract_kol_count(text):
    try:
        return int(re.findall(r'\d+', text)[0])
    except (IndexError, TypeError):
        return 0

def extract_token_ticker(text):
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    skip = ['KOL', 'Market Cap', 'Dev Bought', 'VIEW', 'VISUALIZE', 'TRADE', 'SPY']
    for line in lines[:8]:
        if not any(s in line.upper() for s in skip) and 2 < len(line) < 20 and not re.match(r'^[\d.+\-$%\s]+$', line):
            return line
    return "UNKNOWN_TOKEN"

def get_thumbnail_id(container):
    try:
        img = container.query_selector("img")
        if img:
            return (img.get_attribute("src") or "").strip().lower()
    except Exception:
        pass
    return "no_thumb"

def report_duplicates(tokens):
    names = Counter(t['name'].lower() for t in tokens if t['name'] != "UNKNOWN_TOKEN")
    dupes = [f"{name} (x{count})" for name, count in names.items() if count > 1]
    if dupes:
        print(f"⚠️  Duplicate token names on page: {', '.join(dupes)}")

# --- SCANNING LOGIC ---
def scan_page_for_tokens(page):
    found_tokens = []
    print("🔎 Scanning page for token cards...")
    # This is a general selector for card-like elements. You may need to adjust it if the site changes.
    containers = page.query_selector_all("div[class*='card'], div[class*='token'], div[class*='item']")
    for container in containers:
        text = container.inner_text()
        if "KOL" not in text:
            continue
        kol_count = extract_kol_count(text)
        if kol_count >= MIN_KOL_COUNT:
            token = {
                'name': extract_token_ticker(text),
                'kol_count': kol_count,
                'market_cap': (m.group(1).strip() if (m := re.search(r'Market Cap[:\s]*([^\n]+)', text)) else "Unknown"),
                'dev_bought': (m.group(1).strip() if (m := re.search(r'Dev Bought[:\s]*([^\n]+)', text)) else "Unknown"),
                'thumb_id': get_thumbnail_id(container)
            }
            found_tokens.append(token)
    return found_tokens

# --- MAIN LOOP ---
def main():
    print("🚀 CabalSpy KOL Token Scanner Starting.")
    alerted_tokens = load_alerted_tokens()
    print(f"📝 {len(alerted_tokens)} tokens loaded from alert history.")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        scan_count = 0
        while True:
            scan_count += 1
            print("\n" + "="*60)
            print(f"🔍 Scan #{scan_count} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            try:
                page.goto(CABALSPY_URL, timeout=60000, wait_until='networkidle')
                print("⏳ Page loaded, waiting for dynamic content...")
                time.sleep(10) # Wait for JS rendering
                
                found_tokens = scan_page_for_tokens(page)
                if not found_tokens:
                    print("✅ No tokens matching criteria found in this scan.")
                else:
                    print(f"✅ Found {len(found_tokens)} potential tokens. Checking against history...")
                    report_duplicates(found_tokens)
                    unique_tokens = {t['name'].lower(): t for t in found_tokens}.values()
                    for token in unique_tokens:
                        if token['name'].lower() not in alerted_tokens:
                            trigger_alert_and_save(token['name'], token['kol_count'], token['market_cap'], token['dev_bought'])
                            alerted_tokens.add(token['name'].lower())
                        else:
                            print(f"  - Already alerted for '{token['name']}', skipping.")
            except Exception as e:
                print(f"❌ An error occurred during the scan cycle: {e}")
            print(f"💤 Waiting {SCAN_INTERVAL_SECONDS} seconds...")
            time.sleep(SCAN_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
