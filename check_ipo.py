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
            for field in ["crn", "pin"]:
                if normalized.get(field, "").endswith(".0"):
                    normalized[field] = normalized[field][:-2]
            return {
                "label":    normalized.get("username", "Account 1"),
                "DP":       normalized.get("dp", ""),
                "Username": normalized.get("username", ""),
                "Password": normalized.get("password", ""),
            }

    print("ERROR: No valid accounts found in Google Sheets.")
    sys.exit(1)


def make_driver() -> webdriver.Chrome:
    """Create a headless Chrome driver using webdriver-manager for matching ChromeDriver."""
    import os
    from webdriver_manager.chrome import ChromeDriverManager
    from pathlib import Path
    from selenium.webdriver.chrome.service import Service as ChromeService

    os.environ["WDM_LOG"] = "0"

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-setuid-sandbox")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    raw_path    = ChromeDriverManager().install()
    driver_path = raw_path
    if not os.access(raw_path, os.X_OK):
        for f in Path(raw_path).parent.iterdir():
            if f.name.startswith("chromedriver") and os.access(f, os.X_OK):
                driver_path = str(f)
                break

    print(f"[check_ipo] chromedriver: {driver_path}")
    driver = webdriver.Chrome(service=ChromeService(driver_path), options=opts)
    print("[check_ipo] Chrome launched successfully")
    return driver


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
    Navigate to ASBA, click into each IPO detail page and extract
    fields using the exact label names from MeroShare's UI:

    List row:   Company Name - Issue Description (Scrip)  [IPO]  Share Type  [Apply]
    Detail page labels:
        Company Name, Company Code, Issue Type,
        Share Type, Issue Description, Scrip,
        MaxUnit, MinUnit, Divisible By,
        Share Value Per Unit, Share Value,
        Issue Open Date, Issue Close Date
    """
    import re

    driver.get("https://meroshare.cdsc.com.np/#/asba")
    sleep(3)

    wait = WebDriverWait(driver, 10)

    try:
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-issue")))
    except Exception:
        print("[check_ipo] No open IPOs found on ASBA page.")
        return []

    total = len(driver.find_elements(By.CLASS_NAME, "btn-issue"))
    print(f"[check_ipo] Found {total} apply button(s) on ASBA page")

    ipos = []

    def get_field(page_text: str, label: str, fallback: str = "—") -> str:
        """
        Extract the value that appears on the line immediately after `label`
        in the page's text dump. MeroShare renders label on one line,
        value on the next.
        """
        lines = page_text.split("\n")
        for i, line in enumerate(lines):
            if line.strip() == label and i + 1 < len(lines):
                val = lines[i + 1].strip()
                if val:
                    return val
        return fallback

    for idx in range(total):
        try:
            # Re-navigate to ASBA each time — Angular re-renders after back navigation
            driver.get("https://meroshare.cdsc.com.np/#/asba")
            sleep(2)
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-issue")))
            btns = driver.find_elements(By.CLASS_NAME, "btn-issue")

            if idx >= len(btns):
                break

            # ── Parse list row for scrip fallback only ───────────
            # The row text contains ALL IPOs (whole list is one container)
            # So we extract per-IPO data from it by splitting on "Apply"
            row_name  = f"IPO #{idx+1}"
            row_scrip = f"IPO{idx+1}"
            row_type  = "—"
            try:
                row = btns[idx].find_element(By.XPATH, "./../../..")
                full_list_text = row.text.strip()

                # Split the list into individual IPO blocks by "Apply" keyword
                # Each block looks like:
                # "Company Name\n-\nFor General Public (SCRIP)\nIPO\nShare Type"
                blocks = re.split(r'\nApply\n?', full_list_text)
                if idx < len(blocks):
                    block = blocks[idx].strip()
                    lines = [l.strip() for l in block.split("\n") if l.strip()]

                    # Line 0: Company Name
                    row_name = lines[0] if lines else row_name

                    # Find scrip in parentheses e.g. "(RSY2)"
                    scrip_match = re.search(r'\(([A-Z0-9]+)\)', block)
                    if scrip_match:
                        row_scrip = scrip_match.group(1)

                    # Share type is last line of the block
                    row_type = lines[-1] if lines else "—"

                    print(f"[check_ipo] Row {idx+1}: name={row_name} scrip={row_scrip} type={row_type}")

            except Exception as e:
                print(f"[check_ipo] Row parse error: {e}")

            # ── Click into detail page ────────────────────────────
            btns[idx].click()
            sleep(2)

            # Dump page text — structure from logs:
            # "Apply for Company Share\n
            #  Company Name\n-\nFor General Public (SCRIP)\nIPO\nShare Type\n
            #  Issue Manager\nXXX\nIssue Open Date\n2026-...\nIssue Close Date\n2026-...
            #  No. Of Share Issued\nXXX\nPrice per Share\nXXX\n
            #  Minimum Quantity\nXXX\nMaximum Quantity\nXXX\nDivisible Quantity\nXXX"
            page_text = driver.find_element(By.TAG_NAME, "body").text

            # ── Extract fields from detail page ───────────────────
            # Actual page structure after "Apply for Company Share":
            # [0] Company Name  e.g. "Reliable Samriddhi Yojana-2"
            # [1] "-"
            # [2] "For General Public (RSY2)"
            # [3] "IPO"
            # [4] "Close Ended Mutual Fund"
            # [5] "Issue Manager"
            # [6] Manager name
            # [7] "Issue Open Date"
            # [8] "2026-05-12 3:15 AM"
            # [9] "Issue Close Date"
            # [10] "2026-05-26 11:15 AM"
            # ... "Minimum Quantity" / "Maximum Quantity" / "Price per Share"

            company_name = row_name
            scrip        = row_scrip
            issue_type   = "IPO"
            share_type   = row_type
            issue_desc   = "—"

            try:
                marker       = "Apply for Company Share"
                after        = page_text.split(marker)[-1].strip()
                detail_lines = [l.strip() for l in after.split("\n") if l.strip()]

                company_name = detail_lines[0] if len(detail_lines) > 0 else row_name
                issue_type   = detail_lines[3] if len(detail_lines) > 3 else "IPO"
                share_type   = detail_lines[4] if len(detail_lines) > 4 else row_type

                # Scrip from parentheses in line 2 e.g. "For General Public (RSY2)"
                if len(detail_lines) > 2:
                    sm = re.search(r'\(([A-Z0-9]+)\)', detail_lines[2])
                    scrip = sm.group(1) if sm else row_scrip
                    issue_desc = detail_lines[2].split("(")[0].strip() if "(" in detail_lines[2] else detail_lines[2]

            except Exception as e:
                print(f"[check_ipo] Detail line parse error: {e}")

            # These labels match the actual page text exactly
            open_date   = get_field(page_text, "Issue Open Date",  "—")
            close_date  = get_field(page_text, "Issue Close Date", "—")
            min_unit    = get_field(page_text, "Minimum Quantity", "—")
            max_unit    = get_field(page_text, "Maximum Quantity", "—")
            share_value = get_field(page_text, "Price per Share",  "—")

            scrip = scrip.strip().upper()

            print(f"[check_ipo] ✓ {company_name} ({scrip}) | {issue_type} | {share_type} | {open_date} → {close_date} | Min:{min_unit} Max:{max_unit}")

            ipos.append({
                "name":        company_name,
                "scrip":       scrip,
                "issue_type":  issue_type,
                "share_type":  share_type,
                "issue_desc":  issue_desc,
                "min_unit":    min_unit,
                "max_unit":    max_unit,
                "open_date":   open_date,
                "close_date":  close_date,
                "share_value": share_value,
            })

        except Exception as e:
            print(f"[check_ipo] Error processing IPO {idx+1}: {e}")
            ipos.append({
                "name":        row_name,
                "scrip":       row_scrip,
                "issue_type":  "—",
                "share_type":  row_type,
                "issue_desc":  "—",
                "min_unit":    "—",
                "max_unit":    "—",
                "open_date":   "—",
                "close_date":  "—",
                "share_value": "—",
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
    name        = ipo["name"]
    scrip       = ipo["scrip"].strip().upper()
    issue_type  = ipo.get("issue_type",  "—")
    share_type  = ipo.get("share_type",  "—")
    issue_desc  = ipo.get("issue_desc",  "—")
    open_date   = ipo.get("open_date",   "—")
    close_date  = ipo.get("close_date",  "—")
    min_unit    = ipo.get("min_unit",    "—")
    max_unit    = ipo.get("max_unit",    "—")
    share_value = ipo.get("share_value", "—")

    # Discord button labels max 80 chars — truncate company name if needed
    short_name  = name if len(name) <= 50 else name[:47] + "..."
    apply_label = f"✅ Apply — {short_name}"

    apply_id = f"apply_ipo:{scrip}"
    skip_id  = f"skip_ipo:{scrip}"

    payload = {
        "embeds": [
            {
                "title": f"🔔 {issue_type}: {name} ({scrip})",
                "description": (
                    f"Issue **{index} of {total}** currently open on MeroShare."
                    if total > 1 else
                    "An issue is currently open on MeroShare."
                ),
                "color": 0x3498DB,
                "fields": [
                    {"name": "📂 Issue Type",    "value": issue_type,          "inline": True},
                    {"name": "📋 Share Type",     "value": share_type,          "inline": True},
                    {"name": "📝 For",            "value": issue_desc,          "inline": True},
                    {"name": "📅 Opens",          "value": open_date,           "inline": True},
                    {"name": "📅 Closes",         "value": close_date,          "inline": True},
                    {"name": "💰 Price Per Unit", "value": f"Rs. {share_value}","inline": True},
                    {"name": "📦 Min Kitta",      "value": min_unit,            "inline": True},
                    {"name": "📦 Max Kitta",      "value": max_unit,            "inline": True},
                    {"name": "🔖 Scrip",          "value": scrip,               "inline": True},
                ],
                "footer": {"text": "MeroShare IPO Bot"},
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
                        "label": apply_label,
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
    print(f"[check_ipo] Using account: {account['label']} to check for open IPOs")

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
