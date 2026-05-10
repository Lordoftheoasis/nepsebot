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
    return webdriver.Chrome(options=opts)


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
    Navigate to the ASBA page and scrape all open IPO entries.
    Returns a list of dicts with: name, scrip, close_date, share_type
    """
    driver.get("https://meroshare.cdsc.com.np/#/asba")
    sleep(3)

    ipos = []

    try:
        # Wait for the issue buttons to appear
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-issue")))
    except Exception:
        # No IPOs found — page loaded but no buttons
        print("[check_ipo] No open IPOs found on ASBA page.")
        return []

    # Each IPO is in a table row — scrape the rows
    try:
        rows = driver.find_elements(By.XPATH, "//table//tr[td]")
        for row in rows:
            try:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) < 3:
                    continue

                # Extract text from cells — column order varies but name is usually first
                # We grab all text and the apply button to confirm it's an active IPO
                has_apply_btn = len(row.find_elements(By.CLASS_NAME, "btn-issue")) > 0
                if not has_apply_btn:
                    continue

                # Pull cell text — typical columns: Company Name, Share Type, Close Date
                texts = [c.text.strip() for c in cells]

                # Company name is the first non-empty cell with substantial text
                name = next((t for t in texts if len(t) > 3 and not t.startswith("Apply")), "Unknown")

                # Try to find close date (usually contains "/" or "-")
                close_date = next(
                    (t for t in texts if ("/" in t or "-" in t) and len(t) > 4 and t != name),
                    "—"
                )

                # Share type — look for known keywords
                share_type = next(
                    (t for t in texts if any(k in t.upper() for k in ["IPO", "FPO", "RIGHT", "DEBENTURE", "MUTUAL"])),
                    "—"
                )

                # Scrip: try to get it from a dedicated column or derive from name
                # Some MeroShare versions show scrip in a separate column
                scrip = next(
                    (t for t in texts if t.isupper() and 2 <= len(t) <= 10 and t not in ["IPO", "FPO"]),
                    name.split()[0].upper()[:8]  # fallback: first word of name
                )

                ipos.append({
                    "name":       name,
                    "scrip":      scrip,
                    "close_date": close_date,
                    "share_type": share_type,
                })

            except Exception as e:
                print(f"[check_ipo] Error parsing row: {e}")
                continue

    except Exception as e:
        print(f"[check_ipo] Error scraping ASBA table: {e}")

    # If table scraping yielded nothing but buttons exist, fall back to button text
    if not ipos:
        buttons = driver.find_elements(By.CLASS_NAME, "btn-issue")
        for i, btn in enumerate(buttons, 1):
            try:
                row  = btn.find_element(By.XPATH, "./ancestor::tr")
                text = row.text.strip()
                name = text.split("\n")[0].strip() or f"IPO #{i}"
                ipos.append({
                    "name":       name,
                    "scrip":      name.split()[0].upper()[:8],
                    "close_date": "—",
                    "share_type": "—",
                })
            except Exception:
                ipos.append({
                    "name":       f"IPO #{i}",
                    "scrip":      f"IPO{i}",
                    "close_date": "—",
                    "share_type": "—",
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
    close_date = ipo["close_date"]

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
                    {"name": "📂 Type",   "value": share_type, "inline": True},
                    {"name": "📅 Closes", "value": close_date, "inline": True},
                    {"name": "🔖 Scrip",  "value": scrip,      "inline": True},
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
        print(f"[check_ipo] Error during scrape: {e}")
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
