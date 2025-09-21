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
MIN_SOL_ALERT = float(os.getenv("MIN_SOL_ALERT", "40.0"))  # Only alert for 40+ SOL
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "").strip()

# Data dir for alert history
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)
ALERT_FILE = os.path.join(DATA_DIR, "alerted_tokens.txt")
SCAN_LOG_FILE = os.path.join(DATA_DIR, "scan_history.txt")

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

def log_scan_result(token_name, kol_count, sol_amount, market_cap, dev_bought):
    """Log all scanned tokens to file for record keeping"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {token_name} | {kol_count} KOLs | {sol_amount} SOL | Cap: {market_cap} | Dev: {dev_bought}\n"
    try:
        with open(SCAN_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception:
        pass

def extract_kol_count(kol_text):
    try:
        m = re.search(r"(\d+)\s*KOLs?", kol_text, re.IGNORECASE)
        return int(m.group(1)) if m else 0
    except:
        return 0

def extract_sol_amount(text):
    """Extract SOL amount from various text formats"""
    try:
        # Look for patterns like "12.5 SOL", "45SOL", "SOL 23.8", etc.
        patterns = [
            r"(\d+\.?\d*)\s*SOL",  # "12.5 SOL" or "45SOL"
            r"SOL\s*(\d+\.?\d*)",  # "SOL 12.5"
            r"(\d+\.?\d*)\s*sol",  # lowercase variants
            r"sol\s*(\d+\.?\d*)"
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Return the largest SOL amount found
                amounts = [float(m) for m in matches if m]
                if amounts:
                    return max(amounts)
        
        # If no SOL found, try to extract from dev bought field
        dev_match = re.search(r"Dev Bought[:\s]*([^\n]+)", text, re.IGNORECASE)
        if dev_match:
            dev_text = dev_match.group(1)
            for pattern in patterns:
                matches = re.findall(pattern, dev_text, re.IGNORECASE)
                if matches:
                    amounts = [float(m) for m in matches if m]
                    if amounts:
                        return max(amounts)
        
        return 0.0
    except Exception:
        return 0.0

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
    found_qualifying = []  # Only tokens meeting MIN_KOL_COUNT and SOL requirements
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
        print("\n📊 SCANNING ALL TOKENS (SHOWING SOL AMOUNTS):")
        print("-" * 90)
        print("🔥=40+SOL ✅=16+KOL 💧=<40SOL ❌=<16KOL")
        print("-" * 90)
        
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

                # Extract SOL amount from container text
                sol_amount = extract_sol_amount(container_text)

                m = re.search(r"Market Cap[:\s]*([^\n]+)", container_text)
                market_cap = m.group(1).strip() if m else "Unknown"
                d = re.search(r"Dev Bought[:\s]*([^\n]+)", container_text)
                dev_bought = d.group(1).strip() if d else "Unknown"
                thumb_id = get_thumbnail_id(container) if container else "no_thumb"

                token_data = {'name': token, 'kol_count': kol_count, 'sol_amount': sol_amount, 
                             'market_cap': market_cap, 'dev_bought': dev_bought, 'thumb_id': thumb_id}
                
                # Add to all tokens list
                found_all.append(token_data)
                
                # Log this scan result to file
                log_scan_result(token, kol_count, sol_amount, market_cap, dev_bought)
                
                # Show detailed scan info for EVERY SINGLE TOKEN - NO QUIET MODE!
                sol_display = f"{sol_amount:.1f}" if sol_amount > 0 else "0.0"
                kol_indicator = "✅" if kol_count >= MIN_KOL_COUNT else "❌"
                sol_indicator = "🔥" if sol_amount >= MIN_SOL_ALERT else "💧"
                
                print(f"{kol_indicator}{sol_indicator} {token:15} | {kol_count:2d} KOLs | {sol_display:8s} SOL | MC: {market_cap[:12]:12s} | Dev: {dev_bought[:20]}")
                
                # ALWAYS show what we're processing - VERBOSE!
                if sol_amount >= MIN_SOL_ALERT:
                    print(f"   🚨 HIGH SOL DETECTED: {sol_amount:.1f} SOL!")
                if kol_count >= MIN_KOL_COUNT:
                    print(f"   📈 HIGH KOL COUNT: {kol_count} KOLs!")
                
                # Only add to qualifying list if meets BOTH thresholds
                if kol_count >= MIN_KOL_COUNT and sol_amount >= MIN_SOL_ALERT:
                    found_qualifying.append(token_data)
                    print(f"   🎯 *** QUALIFIES FOR ALERT *** {token} → {kol_count} KOLs + {sol_amount:.1f} SOL")

            except Exception as e:
                print(f"   ❌ Error processing token: {e}")
                continue
    except Exception as e:
        print(f"❌ Scan error: {e}")
    
    return found_all, found_qualifying

def main():
    print("="*60)
    print("🚀 CabalSpy KOL Token Scanner (server) - VERBOSE MODE")
    print(f"URL={CABALSPY_URL}")
    print(f"MIN_KOL_COUNT={MIN_KOL_COUNT}, MIN_SOL_ALERT={MIN_SOL_ALERT}, SCAN_INTERVAL_SECONDS={SCAN_INTERVAL_SECONDS}")
    print("📊 WILL SHOW ALL TOKENS SCANNED WITH SOL AMOUNTS!")
    print("🔔 WILL ONLY ALERT FOR 40+ SOL BUYS!")
    alerted = load_alerted_tokens()
    print(f"📝 {len(alerted)} tokens in alert history")
    print(f"📋 Scan results logged to: {SCAN_LOG_FILE}")
    print("🚫 NO QUIET MODE - SHOWING EVERYTHING!")

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
                print(f"🔎 Scan #{scan_id} - {time.strftime('%Y-%m-%d %H:%M:%S')}")
                try:
                    page.reload(timeout=60000)
                    time.sleep(7)
                    all_tokens, qualifying_tokens = scan_tokens_on_right_panel(page)
                    
                    print(f"\n📈 SCAN SUMMARY - SCAN #{scan_id}:")
                    print(f"   • Total tokens scanned: {len(all_tokens)}")
                    print(f"   • Tokens ≥ {MIN_KOL_COUNT} KOLs: {len([t for t in all_tokens if t['kol_count'] >= MIN_KOL_COUNT])}")
                    print(f"   • Tokens ≥ {MIN_SOL_ALERT} SOL: {len([t for t in all_tokens if t['sol_amount'] >= MIN_SOL_ALERT])}")
                    print(f"   • Tokens qualifying for alerts: {len(qualifying_tokens)}")
                    
                    # Show ALL tokens with their SOL amounts in summary
                    print(f"\n📋 ALL SCANNED TOKENS THIS ROUND:")
                    for t in all_tokens:
                        status = "ALERT SENT" if t['name'].lower() in alerted else "MONITORING"
                        if t['kol_count'] >= MIN_KOL_COUNT and t['sol_amount'] >= MIN_SOL_ALERT:
                            status = "🚨 ALERT WORTHY"
                        print(f"   • {t['name']:15} - {t['kol_count']:2d} KOLs, {t['sol_amount']:6.1f} SOL - {status}")
                    
                    if qualifying_tokens:
                        report_duplicates(qualifying_tokens)
                        for t in qualifying_tokens:
                            name = t['name']
                            if name.lower() not in alerted:
                                msg = f"🚨 MAJOR KOL ALERT — {name}: {t['kol_count']} KOLs + {t['sol_amount']:.1f} SOL | Cap {t['market_cap']} | Dev {t['dev_bought']}"
                                print(f"🔔 SENDING ALERT: {msg}")
                                send_discord(msg)
                                save_alerted_token(name)
                                alerted.add(name.lower())
                            else:
                                print(f"  ✅ (already alerted) {name}")
                    else:
                        print(f"✅ No tokens meet BOTH criteria (≥{MIN_KOL_COUNT} KOLs AND ≥{MIN_SOL_ALERT} SOL)")
                        
                except Exception as e:
                    print(f"❌ scan loop error: {e}")
                print(f"💤 Sleeping {SCAN_INTERVAL_SECONDS}s")
                time.sleep(SCAN_INTERVAL_SECONDS)
        finally:
            try: browser.close()
            except: pass

if __name__ == "__main__":
    main()
