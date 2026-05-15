"""
check_ipo.py
------------
Runs on GitHub Actions cron (Mon & Thu).
Logs into MeroShare using the FIRST account from Google Sheets,
scrapes the ASBA page for open IPOs, then sends one Discord message
per IPO with Apply / Skip buttons.

There is no public MeroShare API — this uses Selenium just like
the apply bot does, logging in with one account to check for open IPOs.

Secrets required (GitHub Actions):
    DISCORD_BOT_TOKEN       - your Discord bot token
    DISCORD_CHANNEL_ID      - channel ID to post alerts in
    GOOGLE_SHEET_ID         - your Google Sheet ID
    GOOGLE_SERVICE_ACCOUNT  - full service account JSON
"""

import os
import sys
import json
import requests
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from time import sleep

# ─────────────────────────────────────────────
DISCORD_BOT_TOKEN  = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "")
GOOGLE_SHEET_ID        = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT = os.environ.get("GOOGLE_SERVICE_ACCOUNT", "")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
# ─────────────────────────────────────────────


def get_first_account() -> dict:
    """Load just the first account from Google Sheets for the IPO check login."""
    if not GOOGLE_SHEET_ID or not GOOGLE_SERVICE_ACCOUNT:
        print("ERROR: Google Sheets secrets not set.")
        sys.exit(1)

    sa_info = json.loads(GOOGLE_SERVICE_ACCOUNT)
    creds   = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    client  = gspread.authorize(creds)
    sheet   = client.open_by_key(GOOGLE_SHEET_ID).sheet1
    rows    = sheet.get_all_records()

    for row in rows:
        normalized = {k.strip().lower(): str(v).strip() for k, v in row.items()}
        if normalized.get("username") and normalized.get("password"):
            # Clean float-style numbers
            for field in ["crn", "pin"]:
                if normalized.get(field, "").endswith(".0"):
                    normalized[field] = normalized[field][:-2]
            return {
                "Name":     normalized.get("name", "Account 1"),
                "DP":       normalized.get("dp", ""),
                "Username": normalized.get("username", ""),
                "Password": normalized.get("password", ""),
            }

    print("ERROR: No valid accounts found in Google Sheets.")
    sys.exit(1)


def make_driver() -> webdriver.Chrome:
    """Create a headless Chrome driver for GitHub Actions environment."""
    import subprocess
    # Print Chrome and ChromeDriver versions for debugging
    try:
        chrome_ver = subprocess.check_output(["google-chrome", "--version"]).decode().strip()
        driver_ver = subprocess.check_output(["chromedriver", "--version"]).decode().strip()
        print(f"[check_ipo] {chrome_ver}")
        print(f"[check_ipo] {driver_ver}")
    except Exception as e:
        print(f"[check_ipo] Could not get versions: {e}")

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-setuid-sandbox")
    opts.add_argument("--remote-debugging-port=9222")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    try:
        driver = webdriver.Chrome(options=opts)
        print("[check_ipo] Chrome launched successfully")
        return driver
    except Exception as e:
        print(f"[check_ipo] Chrome failed to launch: {type(e).__name__}: {e}")
        raise


def login(driver, dp_name: str, username: str, password: str):
    """Log into MeroShare."""
    wait = WebDriverWait(driver, 15)
    driver.get("https://meroshare.cdsc.com.np/#/login")
    sleep(3)

    # Click DP dropdown
    driver.find_element(By.CLASS_NAME, "select2-selection__placeholder").click()
    dp_input = driver.find_element(By.XPATH, "/html/body/span/span/span[1]/input")
    dp_input.send_keys(dp_name, Keys.ENTER)
    sleep(1)

    driver.find_element(By.ID, "username").send_keys(username)
    driver.find_element(By.ID, "password").send_keys(password, Keys.ENTER)
    sleep(3)

    # Confirm we reached the dashboard
    wait.until(EC.url_contains("dashboard"))


def scrape_open_ipos(driver) -> list[dict]:
    """
    Navigate to the ASBA page, click into each IPO's detail page
    to extract accurate name, scrip, type, open/close dates, and kitta limits.
    Returns a list of dicts.
    """
    driver.get("https://meroshare.cdsc.com.np/#/asba")
    sleep(3)

    wait = WebDriverWait(driver, 10)

    # Wait for apply buttons to appear
    try:
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-issue")))
    except Exception:
        print("[check_ipo] No open IPOs found on ASBA page.")
        return []

    # Count how many IPOs are listed
    buttons = driver.find_elements(By.CLASS_NAME, "btn-issue")
    total   = len(buttons)
    print(f"[check_ipo] Found {total} apply button(s) on ASBA page")

    ipos = []

    for idx in range(total):
        try:
            # Re-fetch buttons each iteration (DOM may refresh after navigating back)
            driver.get("https://meroshare.cdsc.com.np/#/asba")
            sleep(2)
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-issue")))
            btns = driver.find_elements(By.CLASS_NAME, "btn-issue")

            if idx >= len(btns):
                break

            # Grab row text BEFORE clicking (for fallback)
            row_text = ""
            try:
                row      = btns[idx].find_element(By.XPATH, "./ancestor::tr")
                row_text = row.text.strip()
                print(f"[check_ipo] Row {idx+1} raw text: {repr(row_text)}")
            except Exception:
                pass

            # Click into the IPO detail page
            btns[idx].click()
            sleep(2)

            # ── Scrape detail page ────────────────────────────────
            name       = "—"
            scrip      = f"IPO{idx+1}"
            share_type = "—"
            open_date  = "—"
            close_date = "—"
            min_unit   = "—"
            max_unit   = "—"

            # MeroShare detail page uses labeled fields — grab all label/value pairs
            try:
                # Try to get all text content in the detail panel
                page_text = driver.find_element(By.TAG_NAME, "body").text

                # Helper: find value after a label in the page text
                def extract_after(label, text, fallback="—"):
                    if label in text:
                        after = text.split(label)[-1].strip()
                        value = after.split("\n")[0].strip()
                        return value if value else fallback
                    return fallback

                name       = extract_after("Company Name",  page_text, name)
                scrip      = extract_after("Scrip",         page_text, scrip)
                share_type = extract_after("Share Type",    page_text, share_type)
                open_date  = extract_after("Open Date",     page_text, open_date)
                close_date = extract_after("Close Date",    page_text, close_date)
                min_unit   = extract_after("Minimum Unit",  page_text, min_unit)
                max_unit   = extract_after("Maximum Unit",  page_text, max_unit)

                # Fallback: try alternate label names
                if name == "—":
                    name = extract_after("Issue Name", page_text, name)
                if scrip == f"IPO{idx+1}":
                    scrip = extract_after("Symbol", page_text, scrip)

                print(f"[check_ipo] Scraped: {name} ({scrip}) | {share_type} | {open_date} → {close_date}")

            except Exception as e:
                print(f"[check_ipo] Detail scrape error for IPO {idx+1}: {e}")
                # Fall back to row text parsing
                if row_text:
                    lines = [l.strip() for l in row_text.split("\n") if l.strip()]
                    name  = lines[0] if lines else name

            # Clean up scrip — remove any whitespace
            scrip = scrip.strip().upper()
            # If scrip is still generic, derive from name
            if not scrip or scrip == f"IPO{idx+1}":
                scrip = name.split()[0].upper()[:8] if name != "—" else f"IPO{idx+1}"

            ipos.append({
                "name":       name,
                "scrip":      scrip,
                "share_type": share_type,
                "open_date":  open_date,
                "close_date": close_date,
                "min_unit":   min_unit,
                "max_unit":   max_unit,
            })

        except Exception as e:
            print(f"[check_ipo] Error processing IPO {idx+1}: {e}")
            ipos.append({
                "name":       f"IPO #{idx+1}",
                "scrip":      f"IPO{idx+1}",
                "share_type": "—",
                "open_date":  "—",
                "close_date": "—",
                "min_unit":   "—",
                "max_unit":   "—",
            })

    return ipos


def logout(driver):
    try:
        driver.find_element(
            By.XPATH,
            "/html/body/app-dashboard/header/div[2]/div/div/div/ul/li[1]/a/i",
        ).click()
        sleep(1)
    except Exception:
        pass


def send_ipo_message(ipo: dict, index: int, total: int):
    """Send one Discord message per IPO with Apply / Skip buttons."""
    name       = ipo["name"]
    scrip      = ipo["scrip"].strip().upper()
    share_type = ipo["share_type"]
    open_date  = ipo.get("open_date", "—")
    close_date = ipo["close_date"]
    min_unit   = ipo.get("min_unit", "—")
    max_unit   = ipo.get("max_unit", "—")

    apply_id = f"apply_ipo:{scrip}"
    skip_id  = f"skip_ipo:{scrip}"

    payload = {
        "embeds": [
            {
                "title": f"🔔 IPO Open: {name} ({scrip})",
                "description": (
                    f"IPO **{index} of {total}** currently open on MeroShare."
                    if total > 1 else
                    "An IPO is currently open on MeroShare."
                ),
                "color": 0x3498DB,
                "fields": [
                    {"name": "📂 Type",      "value": share_type, "inline": True},
                    {"name": "📅 Opens",     "value": open_date,  "inline": True},
                    {"name": "📅 Closes",    "value": close_date, "inline": True},
                    {"name": "📦 Min Kitta", "value": min_unit,   "inline": True},
                    {"name": "📦 Max Kitta", "value": max_unit,   "inline": True},
                    {"name": "🔖 Scrip",     "value": scrip,      "inline": True},
                ],
                "footer": {"text": "MeroShare IPO Bot • Scraped from ASBA page"},
                "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        ],
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 3,
                        "label": f"✅ Apply — {name}",
                        "custom_id": apply_id,
                    },
                    {
                        "type": 2,
                        "style": 4,
                        "label": "❌ Skip",
                        "custom_id": skip_id,
                    },
                ],
            }
        ],
    }

    url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }

    r = requests.post(url, json=payload, headers=headers, timeout=10)
    if r.status_code in (200, 201):
        print(f"[check_ipo] Alert sent for {name} ({scrip})")
    else:
        print(f"[check_ipo] Failed to send alert for {scrip}: {r.status_code} {r.text}")


def main():
    print("[check_ipo] Starting MeroShare IPO check...")

    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        print("ERROR: Missing DISCORD_BOT_TOKEN or DISCORD_CHANNEL_ID")
        sys.exit(1)

    # Get first account to use for login
    account = get_first_account()
    print(f"[check_ipo] Using account: {account['Name']} to check for open IPOs")

    driver = make_driver()

    try:
        login(driver, account["DP"], account["Username"], account["Password"])
        print("[check_ipo] Logged in successfully")

        ipos = scrape_open_ipos(driver)
        logout(driver)

    except Exception as e:
        import traceback
        print(f"[check_ipo] Error during scrape: {type(e).__name__}: {e}")
        print(traceback.format_exc())
        driver.quit()
        sys.exit(1)
    finally:
        driver.quit()

    if not ipos:
        print("[check_ipo] No open IPOs found. Nothing to do.")
        sys.exit(0)

    total = len(ipos)
    print(f"[check_ipo] Found {total} open IPO(s):")
    for ipo in ipos:
        print(f"  - {ipo['name']} ({ipo['scrip']})")

    for i, ipo in enumerate(ipos, start=1):
        send_ipo_message(ipo, index=i, total=total)


if __name__ == "__main__":
    main()
