# kol_scanner_server.py
# CabalSpy KOL token scanner (server-safe). Sends Discord alerts; no GUI.

import time, re, os
from collections import Counter
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# --- Config via env ---
CABALSPY_URL = os.getenv("CABALSPY_URL", "https://cabalspy.xyz/dashboard.php")
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "160"))
MIN_KOL_COUNT = int(os.getenv("MIN_KOL_COUNT", "16"))
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "").strip()

# Data dir for alert history
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)
ALERT_FILE = os.path.join(DATA_DIR, "alerted_tokens.txt")

def send_discord(msg: str):
    if not DISCORD_WEBHOOK:
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=8)
    except Exception:
        pass

def load_alerted_tokens():
    if not os.path.exists(ALERT_FILE):
        return set()
    with open(ALERT_FILE, "r") as f:
        return {line.strip().lower() for line in f}

def save_alerted_token(token_name):
    with open(ALERT_FILE, "a") as f:
        f.write(f"{token_name.lower()}\n")

def extract_kol_count(kol_text):
    try:
        m = re.search(r"(\d+)\s*KOLs?", kol_text, re.IGNORECASE)
        return int(m.group(1)) if m else 0
    except:
        return 0

def extract_token_ticker(container_text):
    lines = [l.strip() for l in container_text.split("\n") if l.strip()]
    skip = {'KOL', 'MARKET CAP', 'DEV BOUGHT', 'VIEW', 'VISUALIZE',
            'GMGN','PHOTON','AXIOM','BULLX','PADRE','COPY','TRADE','SPY','WALLET','%','SOL','+','-','WOULD','TRULI'}
    for line in lines[:8]:
        up = line.upper()
        if any(k in up for k in skip): 
            continue
        if re.match(r"^[\d.+\-$%\s]+$", line): 
            continue
        if 2 <= len(line) <= 20:
            return line
    for line in lines:
        for pat in [r"\b[A-Z]{3,8}\b", r"\$([A-Za-z]{2,10})\b", r"\b([A-Za-z]{2,15})\s*\("]:
            m = re.findall(pat, line)
            for tok in m:
                tok = tok if isinstance(tok, str) else tok
                if tok and tok.upper() not in skip:
                    return tok
    return "UNKNOWN_TOKEN"

def get_thumbnail_id(container):
    try:
        for img in container.query_selector_all("img"):
            src = (img.get_attribute("src") or "").strip()
            if src: 
                return src.lower()
    except Exception:
        pass
    try:
        for node in container.query_selector_all("[style*='background-image']"):
            bg = (node.get_attribute("style") or "")
            m = re.search(r"background-image\s*:\s*url\(([^)]+)\)", bg, re.IGNORECASE)
            if m:
                return m.group(1).strip('\'" ').lower()
    except Exception:
        pass
    return "no_thumb"

def report_duplicates(tokens):
    name_counts = Counter([t['name'].strip().lower() for t in tokens if t['name'] and t['name'] != "UNKNOWN_TOKEN"])
    thumb_counts = Counter([t.get('thumb_id', 'no_thumb') for t in tokens])
    dup_names = [n for n,c in name_counts.items() if c>1]
    dup_thumbs = [h for h,c in thumb_counts.items() if h!="no_thumb" and c>1]
    if dup_names:
        print("⚠️ Duplicate token names:", ", ".join(dup_names))
    if dup_thumbs:
        print("⚠️ Duplicate thumbnails:", ", ".join(dup_thumbs))

def scan_tokens_on_right_panel(page):
    found_all = []  # All tokens found
    found_qualifying = []  # Only tokens meeting MIN_KOL_COUNT
    try:
        try:
            page.wait_for_selector("body", timeout=8000)
        except PWTimeout:
            return found_all, found_qualifying

        kol_candidates = page.locator(":text('KOL')").all()
        valid_nodes = []
        for node in kol_candidates:
            try:
                txt = (node.inner_text() or "").strip()
                if re.search(r"\d+\s*KOLs?", txt, re.IGNORECASE):
                    valid_nodes.append(node)
            except Exception:
                continue

        print(f"🔍 KOL elements found: {len(valid_nodes)}")
        for node in valid_nodes:
            try:
                kol_text = (node.inner_text() or "").strip()
                kol_count = extract_kol_count(kol_text)

                container = node
                for _ in range(8):
                    txt = (container.inner_text() or "")
                    if any(s in txt for s in ['Market Cap','Dev Bought','VISUALIZE','VIEW']):
                        break
                    parent = container.evaluate_handle("el => el.parentElement")
                    container = parent.as_element() if parent else container
                    if container is None:
                        break

                container_text = container.inner_text() if container else ""
                token = extract_token_ticker(container_text)

                m = re.search(r"Market Cap[:\s]*([^\n]+)", container_text)
                market_cap = m.group(1).strip() if m else "Unknown"
                d = re.search(r"Dev Bought[:\s]*([^\n]+)", container_text)
                dev_bought = d.group(1).strip() if d else "Unknown"
                thumb_id = get_thumbnail_id(container) if container else "no_thumb"

                token_data = {'name': token, 'kol_count': kol_count, 'market_cap': market_cap,
                             'dev_bought': dev_bought, 'thumb_id': thumb_id}
                
                # Add to all tokens list
                found_all.append(token_data)
                
                # Show in logs for every token scanned
                print(f"   📊 SCANNED: {token} → {kol_count} KOLs | Cap: {market_cap} | Dev: {dev_bought}")
                
                # Only add to qualifying list if meets threshold
                if kol_count >= MIN_KOL_COUNT:
                    found_qualifying.append(token_data)
                    print(f"   🎯 QUALIFIES: {token} → {kol_count} KOLs (≥{MIN_KOL_COUNT})")

            except Exception:
                continue
    except Exception as e:
        print(f"❌ Scan error: {e}")
    
    return found_all, found_qualifying

def main():
    print("="*60)
    print("🚀 CabalSpy KOL Token Scanner (server)")
    print(f"URL={CABALSPY_URL}")
    print(f"MIN_KOL_COUNT={MIN_KOL_COUNT}, SCAN_INTERVAL_SECONDS={SCAN_INTERVAL_SECONDS}")
    alerted = load_alerted_tokens()
    print(f"📝 {len(alerted)} tokens in alert history")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = browser.new_page()
        try:
            print(f"🌐 Opening {CABALSPY_URL}")
            page.goto(CABALSPY_URL, timeout=60000)
            time.sleep(5)
            scan_id = 0
            while True:
                scan_id += 1
                print("\n" + "="*60)
                print(f"🔎 Scan #{scan_id}")
                try:
                    page.reload(timeout=60000)
                    time.sleep(7)
                    all_tokens, qualifying_tokens = scan_tokens_on_right_panel(page)
                    
                    print(f"\n📈 SCAN RESULTS: Found {len(all_tokens)} total tokens, {len(qualifying_tokens)} qualify for alerts")
                    
                    if qualifying_tokens:
                        report_duplicates(qualifying_tokens)
                        for t in qualifying_tokens:
                            name = t['name']
                            if name.lower() not in alerted:
                                msg = f"🚨 KOL ALERT — {name}: {t['kol_count']} KOLs | Cap {t['market_cap']} | Dev {t['dev_bought']}"
                                print(f"🔔 ALERTING: {msg}")
                                send_discord(msg)
                                save_alerted_token(name)
                                alerted.add(name.lower())
                            else:
                                print(f"  ✅ (already alerted) {name}")
                    else:
                        print(f"✅ No tokens ≥ {MIN_KOL_COUNT} KOLs this scan")
                        
                except Exception as e:
                    print(f"❌ scan loop error: {e}")
                print(f"💤 Sleeping {SCAN_INTERVAL_SECONDS}s")
                time.sleep(SCAN_INTERVAL_SECONDS)
        finally:
            try: browser.close()
            except: pass

if __name__ == "__main__":
    main()
