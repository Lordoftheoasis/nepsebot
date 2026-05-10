"""
discord_notifier.py
-------------------
Sends rich embed notifications to a Discord channel via webhook.
Used by apply_all.py to report per-account results and final summary.

Secrets required:
    DISCORD_WEBHOOK_URL
"""

import os
import requests
from datetime import datetime

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

COLOR_SUCCESS = 0x2ECC71
COLOR_FAILURE = 0xE74C3C
COLOR_INFO    = 0x3498DB
COLOR_SUMMARY = 0xF39C12


def _send(payload: dict) -> bool:
    if not DISCORD_WEBHOOK_URL:
        print("[Discord] WARNING: DISCORD_WEBHOOK_URL not set — skipping.")
        return False
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[Discord] Failed to send: {e}")
        return False


def _ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def notify_start(total_accounts: int, ipo_name: str = "Current IPO", kitta: int = 10):
    _send({"embeds": [{
        "title": "🚀 IPO Application Started",
        "description": "Beginning automated IPO applications on MeroShare.",
        "color": COLOR_INFO,
        "fields": [
            {"name": "📋 IPO",              "value": ipo_name,          "inline": True},
            {"name": "👥 Accounts",         "value": str(total_accounts),"inline": True},
            {"name": "📦 Kitta / Account",  "value": str(kitta),        "inline": True},
        ],
        "footer": {"text": "MeroShare IPO Bot"},
        "timestamp": _ts(),
    }]})


def notify_success(name: str, index: int, total: int, dp: str, kitta: int, crn: str):
    _send({"embeds": [{
        "title": "✅ Application Successful",
        "color": COLOR_SUCCESS,
        "fields": [
            {"name": "👤 Name",         "value": name,              "inline": True},
            {"name": "🏦 DP",           "value": dp,                "inline": True},
            {"name": "📦 Kitta",        "value": str(kitta),        "inline": True},
            {"name": "🔑 CRN",          "value": f"||{crn}||",      "inline": True},
            {"name": "📊 Progress",     "value": f"{index}/{total}","inline": True},
        ],
        "footer": {"text": "MeroShare IPO Bot"},
        "timestamp": _ts(),
    }]})


def notify_failure(name: str, index: int, total: int, reason: str):
    short = (reason[:300] + "…") if len(reason) > 300 else reason
    _send({"embeds": [{
        "title": "❌ Application Failed",
        "color": COLOR_FAILURE,
        "fields": [
            {"name": "👤 Name",     "value": name,                  "inline": True},
            {"name": "📊 Progress", "value": f"{index}/{total}",    "inline": True},
            {"name": "⚠️ Reason",  "value": f"```{short}```",       "inline": False},
        ],
        "footer": {"text": "MeroShare IPO Bot"},
        "timestamp": _ts(),
    }]})


def notify_summary(results: list[dict], kitta: int):
    total   = len(results)
    success = sum(1 for r in results if r["Status"] == "Success")
    failed  = total - success
    lines   = [("✅" if r["Status"] == "Success" else "❌") + " " + r["Name"] for r in results]

    color = COLOR_SUCCESS if failed == 0 else (COLOR_FAILURE if success == 0 else COLOR_SUMMARY)

    _send({"embeds": [{
        "title": "📊 IPO Batch — Final Summary",
        "color": color,
        "fields": [
            {"name": "✅ Successful", "value": str(success),         "inline": True},
            {"name": "❌ Failed",     "value": str(failed),          "inline": True},
            {"name": "📦 Kitta",      "value": str(kitta),           "inline": True},
            {"name": "📋 Results",    "value": "\n".join(lines),     "inline": False},
        ],
        "footer": {"text": "MeroShare IPO Bot • All done"},
        "timestamp": _ts(),
    }]})
