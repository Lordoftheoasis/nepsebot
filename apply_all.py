"""
apply_all.py
------------
Reads account details from a private Google Sheet and applies
a specific IPO (identified by scrip) for every account.

Google Sheet format (row 1 = headers):
    Name | DP | Username | Password | CRN | PIN

Secrets required (GitHub Actions):
    GOOGLE_SHEET_ID         - the ID from your sheet URL
    GOOGLE_SERVICE_ACCOUNT  - full JSON of your service account key
    DISCORD_WEBHOOK_URL     - for notifications
    APPLIED_KITTA           - optional, defaults to 10

Workflow inputs (passed from Discord button via apply_ipo.yml):
    IPO_SCRIP               - stock symbol to apply e.g. "NABIL"
    IPO_NAME                - friendly display name e.g. "Nabil Bank IPO"
"""

import os
import sys
import json
import gspread
from google.oauth2.service_account import Credentials
from ipobot import MeroShare
from discord_notifier import (
    notify_start,
    notify_success,
    notify_failure,
    notify_summary,
)

# ─────────────────────────────────────────────
APPLIED_KITTA = int(os.environ.get("APPLIED_KITTA", 10))
DRIVER_PATH   = None
IPO_NAME      = os.environ.get("IPO_NAME", "Current IPO")
IPO_SCRIP     = os.environ.get("IPO_SCRIP", None)   # None = fall back to first IPO

GOOGLE_SHEET_ID        = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT = os.environ.get("GOOGLE_SERVICE_ACCOUNT", "")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
# ─────────────────────────────────────────────


def load_accounts_from_sheets() -> list[dict]:
    """Authenticate with Google Sheets and load account rows."""
    if not GOOGLE_SHEET_ID or not GOOGLE_SERVICE_ACCOUNT:
        print("ERROR: GOOGLE_SHEET_ID or GOOGLE_SERVICE_ACCOUNT not set.")
        sys.exit(1)

    try:
        sa_info = json.loads(GOOGLE_SERVICE_ACCOUNT)
    except json.JSONDecodeError as e:
        print(f"ERROR: Could not parse GOOGLE_SERVICE_ACCOUNT JSON: {e}")
        sys.exit(1)

    creds  = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet  = client.open_by_key(GOOGLE_SHEET_ID).sheet1

    # numericise_ignore=['all'] tells gspread to return ALL values as strings
    # without converting numbers — this preserves leading zeros in CRN/PIN
    rows = sheet.get_all_records(
        value_render_option="FORMATTED_VALUE",
        numericise_ignore=["all"],
    )

    required = ["Name", "DP", "Username", "Password", "CRN", "PIN"]
    accounts = []

    for row in rows:
        normalized = {k.strip().lower(): str(v).strip() for k, v in row.items()}
        if not any(normalized.values()):
            continue

        account = {}
        for field in required:
            val = normalized.get(field.lower(), "")
            if val.endswith(".0"):
                val = val[:-2]
            account[field] = val

        if not account["Username"] or not account["Password"]:
            continue

        # Strip float formatting but preserve leading zeros
        # Use split(".")[0] not lstrip("0") — we want "005006148" not "5006148"
        account["PIN"] = account["PIN"].split(".")[0].strip()
        account["CRN"] = account["CRN"].split(".")[0].strip()

        # Use Name for display if available, fall back to Username
        account["label"] = account.get("Name") or account["Username"]
        accounts.append(account)

    return accounts


def load_accounts_from_excel(filepath: str = "accounts.xlsx") -> list[dict]:
    """Fallback: load from local Excel file (for local dev/testing)."""
    import pandas as pd

    df = pd.read_excel(filepath)
    df.columns = [c.strip() for c in df.columns]

    required = ["Name", "DP", "Username", "Password", "CRN", "PIN"]
    col_map  = {}
    for req in required:
        match = next((c for c in df.columns if c.lower() == req.lower()), None)
        if match is None and req != "Name":  # Name is optional
            raise ValueError(f"Missing column: '{req}'")
        if match:
            col_map[req] = match

    df = df.rename(columns={v: k for k, v in col_map.items()})
    available = [c for c in required if c in df.columns]
    df = df[available]
    df = df.dropna(subset=["Username", "Password", "CRN", "PIN"], how="all")
    df["PIN"] = df["PIN"].astype(str).str.strip().str.split(".").str[0]
    df["CRN"] = df["CRN"].astype(str).str.strip().str.split(".").str[0]
    records = df.to_dict(orient="records")
    for r in records:
        r["label"] = r.get("Name") or r["Username"]
    return records


def main():
    scrip_label = f" ({IPO_SCRIP})" if IPO_SCRIP else ""
    print(f"Applying IPO: {IPO_NAME}{scrip_label}")

    # Load accounts
    if GOOGLE_SERVICE_ACCOUNT and GOOGLE_SHEET_ID:
        print("Loading accounts from Google Sheets...")
        accounts = load_accounts_from_sheets()
    else:
        print("Loading accounts from local Excel (dev mode)...")
        accounts = load_accounts_from_excel()

    total = len(accounts)
    if total == 0:
        print("No accounts found. Exiting.")
        sys.exit(0)

    print(f"Found {total} account(s). Starting...\n")
    notify_start(total_accounts=total, ipo_name=IPO_NAME, kitta=APPLIED_KITTA)

    bot     = MeroShare(driver_path=DRIVER_PATH)
    results = []

    for i, user in enumerate(accounts, start=1):
        label = user["label"]
        print(f"[{i}/{total}] Processing: {label}")

        try:
            bot.login(user["DP"], user["Username"], user["Password"])
            bot.find_ipo(scrip=IPO_SCRIP)
            bot.apply_ipo(str(APPLIED_KITTA), user["CRN"])
            bot.enter_pin(user["PIN"])
            bot.logout()

            print(f"  ✓ Applied successfully: {label}")
            results.append({"label": label, "Status": "Success"})
            notify_success(
                label=label, index=i, total=total,
                dp=user["DP"], kitta=APPLIED_KITTA, crn=user["CRN"],
            )

        except Exception as e:
            error_msg = str(e)
            print(f"  ✗ Failed: {label} — {error_msg}")
            results.append({"label": label, "Status": f"Failed: {error_msg}"})
            notify_failure(label=label, index=i, total=total, reason=error_msg)

            try:
                bot.driver.get("https://meroshare.cdsc.com.np/#/login")
            except Exception:
                pass

    bot.quit()

    print("\n" + "=" * 40)
    success = sum(1 for r in results if r["Status"] == "Success")
    for r in results:
        icon = "✓" if r["Status"] == "Success" else "✗"
        print(f"  {icon} {r['label']}: {r['Status']}")
    print(f"\nCompleted: {success}/{total} successful")

    notify_summary(results=results, kitta=APPLIED_KITTA)


if __name__ == "__main__":
    main()
