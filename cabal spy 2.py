import time
import re
import os
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import messagebox
from collections import Counter

# >>> Playwright (sync) instead of Selenium
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# --- CONFIGURATION ---
CABALSPY_URL = "https://cabalspy.xyz/dashboard.php"
SCAN_INTERVAL_SECONDS = 160  # Check every 160 seconds for new tokens
MIN_KOL_COUNT = 22   # Alert threshold for KOL count

# --- FILE PATH & ALERT HISTORY ---
SCRIPT_DIR = r"C:\Users\yourf\Desktop"  # Fixed path to Desktop
ALERT_FILE = os.path.join(SCRIPT_DIR, "alerted_tokens.txt")

# --- Windows Taskbar Flashing ---
class FLASHWINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("hwnd", wintypes.HWND),
        ("dwFlags", wintypes.DWORD),
        ("uCount", wintypes.UINT),
        ("dwTimeout", wintypes.DWORD),
    ]

FLASHW_ALL, FLASHW_TIMERNOFG = 0x00000003, 0x0000000C

def flash_taskbar_icon():
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return
        flash_info = FLASHWINFO(
            cbSize=ctypes.sizeof(FLASHWINFO),
            hwnd=hwnd,
            dwFlags=FLASHW_ALL | FLASHW_TIMERNOFG,
            uCount=0,
            dwTimeout=0,
        )
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(flash_info))
    except Exception:
        pass

# --- POP-UPS ---
def show_popup_alert(token_name, kol_count, market_cap, dev_bought):
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    alert_message = (
        f"🚨 NEW HIGH KOL TOKEN DETECTED! 🚨\n\n"
        f"Token: {token_name}\n"
        f"KOLs: {kol_count}\n"
        f"Market Cap: {market_cap}\n"
        f"Dev Bought: {dev_bought}"
    )
    messagebox.showwarning("🚨 KOL ALERT! 🚨", alert_message)
    root.destroy()

def show_duplicates_popup(dup_names, dup_thumbs):
    if not dup_names and not dup_thumbs:
        return
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    lines = []
    if dup_names:
        lines.append("Duplicate Token Names:\n  - " + "\n  - ".join(dup_names))
    if dup_thumbs:
        lines.append("Duplicate Thumbnails (same image src/bg):\n  - " + "\n  - ".join(dup_thumbs))

    message = "⚠️ Duplicates detected on page:\n\n" + "\n\n".join(lines)
    messagebox.showinfo("Duplicate Tokens Detected", message)
    root.destroy()

# --- ALERT FILE LOGIC ---
def load_alerted_tokens():
    if not os.path.exists(ALERT_FILE):
        return set()
    with open(ALERT_FILE, 'r') as f:
        return {line.strip().lower() for line in f}

def save_alerted_token(token_name):
    with open(ALERT_FILE, 'a') as f:
        f.write(f"{token_name.lower()}\n")

def trigger_alert_and_save(token_name, kol_count, market_cap, dev_bought):
    print(f"🚨🚨🚨 NEW TOKEN ALERT: {token_name} with {kol_count} KOLs! 🚨🚨🚨")
    print(f"   Market Cap: {market_cap}")
    print(f"   Dev Bought: {dev_bought}")

    show_popup_alert(token_name, kol_count, market_cap, dev_bought)
    flash_taskbar_icon()

    try:
        save_alerted_token(token_name)
        print(f"✅ Saved {token_name} to alert history.")
    except Exception as e:
        print(f"❌ Could not save alert to file: {e}")

# --- TOKEN TEXT EXTRACTION ---
def extract_kol_count(kol_text):
    """Extract numeric KOL count from text like '10 KOLs'"""
    try:
        numbers = re.findall(r'\d+', kol_text)
        if numbers:
            return int(numbers[0])
    except:
        pass
    return 0

def extract_token_ticker(container_text):
    """Extract token ticker/symbol from the card text."""
    lines = [line.strip() for line in container_text.split('\n') if line.strip()]

    # Skip lines that are definitely not token names
    skip_keywords = [
        'KOL', 'Market Cap', 'Dev Bought', 'VIEW', 'VISUALIZE',
        'GMGN', 'PHOTON', 'AXIOM', 'BULLX', 'PADRE', 'COPY',
        'TRADE', 'SPY', 'WALLET', '%', 'SOL', '+', '-', 'WOULD', 'TRULI'
    ]

    # Look for the token name - usually one of the first few lines
    for line in lines[:8]:
        line_upper = line.upper()
        if any(keyword in line_upper for keyword in skip_keywords):
            continue
        if re.match(r'^[\d.+\-$%\s]+$', line):
            continue
        if len(line) < 2 or len(line) > 20:
            continue
        return line

    # Fallback patterns
    ticker_patterns = [
        r'\b[A-Z]{3,8}\b',           # 3-8 uppercase letters
        r'\$([A-Za-z]{2,10})\b',     # $TICKER
        r'\b([A-Za-z]{2,15})\s*\(',  # NAME (desc
    ]
    for line in lines:
        for pattern in ticker_patterns:
            matches = re.findall(pattern, line)
            for match in matches:
                ticker = match if isinstance(match, str) else match
                if not any(keyword in ticker.upper() for keyword in skip_keywords):
                    return ticker

    return "UNKNOWN_TOKEN"

# --- THUMBNAIL/IMAGE ID EXTRACTION (for duplicate detection) ---
def get_thumbnail_id(container):
    """
    Return a stable identifier for the token card's thumbnail.
    Prefers <img src>; falls back to background-image url(...) in inline styles.
    """
    try:
        imgs = container.query_selector_all("img")
        for img in imgs:
            src = (img.get_attribute("src") or "").strip()
            if src:
                return src.lower()
    except Exception:
        pass

    try:
        styled_nodes = container.query_selector_all("[style*='background-image']")
        for node in styled_nodes:
            bg = (node.get_attribute("style") or "")
            m = re.search(r'background-image\s*:\s*url\(([^)]+)\)', bg, re.IGNORECASE)
            if m:
                url = m.group(1).strip('\'" ')
                if url:
                    return url.lower()
    except Exception:
        pass

    return "no_thumb"

def report_duplicates(tokens, popup=True):
    """
    Print and (optionally) popup duplicates by token name and by thumbnail id.
    """
    name_counts = Counter([t['name'].strip().lower() for t in tokens if t['name'] and t['name'] != "UNKNOWN_TOKEN"])
    thumb_counts = Counter([t.get('thumb_id', 'no_thumb') for t in tokens])

    dup_names = [f"{n} (x{name_counts[n]})" for n, c in name_counts.items() if c > 1]
    dup_thumbs = [f"{h} (x{thumb_counts[h]})" for h, c in thumb_counts.items() if h != "no_thumb" and c > 1]

    if dup_names:
        print("⚠️  DUPLICATE TOKEN NAMES DETECTED:", ", ".join(dup_names))
    if dup_thumbs:
        print("⚠️  DUPLICATE THUMBNAILS DETECTED:", ", ".join(dup_thumbs))

    if popup and (dup_names or dup_thumbs):
        show_duplicates_popup(
            [n.split(" (x")[0] for n in dup_names],
            [h.split(" (x")[0] for h in dup_thumbs],
        )

# --- SCAN LOGIC (Playwright page instead of Selenium driver) ---
def scan_tokens_on_right_panel(page):
    """Scan the right panel for tokens with KOL information"""
    found_tokens = []

    try:
        print("🔎 Scanning for tokens with KOL counts.")

        # Wait for any content; page is dynamic
        try:
            page.wait_for_selector("body", timeout=8000)
        except PWTimeout:
            return []

        # Find elements that contain 'KOL' somewhere (broad), we’ll filter by regex after
        # Playwright supports text selectors; this grabs elements containing 'KOL'
        kol_candidates = page.locator(":text('KOL')").all()

        # Filter for actual KOL counts by text like "12 KOLs"
        valid_nodes = []
        valid_kol_texts = []
        for node in kol_candidates:
            try:
                txt = (node.inner_text() or "").strip()
                if re.search(r'\d+\s*KOLs?', txt, re.IGNORECASE):
                    valid_nodes.append(node)
                    valid_kol_texts.append(txt)
            except Exception:
                continue

        unique_kol_texts = list(dict.fromkeys(valid_kol_texts))  # preserve order, unique
        print(f"🔍 Found {len(unique_kol_texts)} unique KOL count elements")

        for node in valid_nodes:
            try:
                kol_text = (node.inner_text() or "").strip()
                kol_count = extract_kol_count(kol_text)

                if kol_count >= MIN_KOL_COUNT:
                    print(f"   🎯 FOUND HIGH KOL TOKEN: {kol_count} KOLs!")

                    # climb up to a container that includes Market Cap / Dev Bought fields
                    container = node
                    container_text = ""
                    for _ in range(8):
                        container_text = (container.inner_text() or "")
                        if any(s in container_text for s in ['Market Cap', 'Dev Bought', 'VISUALIZE', 'VIEW']):
                            break
                        parent = container.evaluate_handle("el => el.parentElement")
                        container = parent.as_element() if parent else container
                        if container is None:
                            break

                    container_text = container.inner_text() if container else ""

                    # Extract token ticker
                    token_ticker = extract_token_ticker(container_text)

                    # Extract market cap
                    market_cap = "Unknown"
                    m = re.search(r'Market Cap[:\s]*([^\n]+)', container_text)
                    if m:
                        market_cap = m.group(1).strip()

                    # Extract dev bought
                    dev_bought = "Unknown"
                    d = re.search(r'Dev Bought[:\s]*([^\n]+)', container_text)
                    if d:
                        dev_bought = d.group(1).strip()

                    # Thumbnail identifier for duplicate detection
                    thumb_id = get_thumbnail_id(container) if container else "no_thumb"

                    print(f"   📊 Token: {token_ticker} | KOLs: {kol_count} | Cap: {market_cap} | Dev: {dev_bought} | Thumb: {thumb_id}")

                    found_tokens.append({
                        'name': token_ticker,
                        'kol_count': kol_count,
                        'market_cap': market_cap,
                        'dev_bought': dev_bought,
                        'thumb_id': thumb_id
                    })

            except Exception:
                continue

        return found_tokens

    except Exception as e:
        print(f"❌ Error scanning tokens: {e}")
        return []

# --- MAIN LOOP (Playwright headless) ---
def main():
    print("🚀 CabalSpy KOL Token Scanner Starting.")
    print(f"🎯 Monitoring for tokens with {MIN_KOL_COUNT}+ KOLs")

    alerted_tokens = load_alerted_tokens()
    print(f"📝 {len(alerted_tokens)} tokens in alert history file")

    with sync_playwright() as p:
        # headless Chromium
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            print(f"🌐 Opening {CABALSPY_URL}")
            page.goto(CABALSPY_URL, timeout=60000)
            time.sleep(5)

            scan_count = 0

            while True:
                scan_count += 1
                print("\n" + "=" * 60)
                print(f"🔍 Scan #{scan_count} at {time.strftime('%I:%M:%S %p')}")

                try:
                    page.reload(timeout=60000)
                    print("⏳ Page refreshed, waiting for content to load.")
                    time.sleep(7)

                    found_tokens = scan_tokens_on_right_panel(page)

                    if found_tokens:
                        print(f"✅ Found {len(found_tokens)} tokens with {MIN_KOL_COUNT}+ KOLs")

                        # Check for duplicates and show popup
                        report_duplicates(found_tokens, popup=True)

                        # Alert once per token name
                        for token in found_tokens:
                            token_name = token['name']
                            kol_count = token['kol_count']
                            market_cap = token['market_cap']
                            dev_bought = token['dev_bought']

                            print(f"  📊 {token_name}: {kol_count} KOLs")

                            if token_name.lower() not in alerted_tokens:
                                trigger_alert_and_save(token_name, kol_count, market_cap, dev_bought)
                                alerted_tokens.add(token_name.lower())
                            else:
                                print(f"  ⚠️  Already alerted for {token_name}")
                    else:
                        print(f"✅ No tokens found with {MIN_KOL_COUNT}+ KOLs in this scan")

                except Exception as e:
                    print(f"❌ Error during scan: {e}")
                    print("   Will retry on next cycle.")

                print(f"💤 Waiting {SCAN_INTERVAL_SECONDS} seconds before next scan.")
                time.sleep(SCAN_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("\n🛑 Scanner stopped by user")
        except Exception as e:
            print(f"\n❌ Fatal error: {e}")
        finally:
            print("🚪 Closing browser.")
            try:
                browser.close()
            except Exception:
                pass
            print("✅ Scanner shut down complete")

if __name__ == "__main__":
    print("=" * 50)
    print("   CABALSPY KOL TOKEN SCANNER")
    print("=" * 50)
    try:
        main()
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        print("📝 Check that all required packages are installed:")
        print("   pip install playwright")
        input("\nPress Enter to exit.")
    except KeyboardInterrupt:
        print("\n🛑 Scanner stopped by user")
        input("Press Enter to exit.")
