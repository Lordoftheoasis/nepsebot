"""
bot.py
------
Lightweight Discord bot that:
  1. Listens for button clicks on IPO alert messages
  2. Parses the scrip from the button's custom_id (format: "apply_ipo:SCRIP")
  3. Triggers the GitHub Actions apply_ipo.yml workflow with that scrip
  4. Handles multiple simultaneous IPOs independently

Runs 24/7 on Railway free tier.

Environment variables (set in Railway):
    DISCORD_BOT_TOKEN       - your Discord bot token
    GITHUB_TOKEN            - GitHub PAT with repo + workflow scopes
    GITHUB_OWNER            - your GitHub username
    GITHUB_REPO             - repo name e.g. meroshare-ipo-bot
    GITHUB_WORKFLOW_FILE    - workflow filename e.g. apply_ipo.yml
    ALLOWED_USER_IDS        - comma-separated Discord user IDs (leave empty = everyone)
"""

import os
import sys
import requests
import discord
from discord.ext import commands
from datetime import datetime

# ─────────────────────────────────────────────
DISCORD_BOT_TOKEN    = os.environ.get("DISCORD_BOT_TOKEN", "")
GITHUB_TOKEN         = os.environ.get("GITHUB_TOKEN", "")
GITHUB_OWNER         = os.environ.get("GITHUB_OWNER", "")
GITHUB_REPO          = os.environ.get("GITHUB_REPO", "")
GITHUB_WORKFLOW_FILE = os.environ.get("GITHUB_WORKFLOW_FILE", "apply_ipo.yml")
ALLOWED_USER_IDS     = [
    int(uid.strip())
    for uid in os.environ.get("ALLOWED_USER_IDS", "").split(",")
    if uid.strip().isdigit()
]
# ─────────────────────────────────────────────

# Track in-progress scrips to prevent double-clicks
_running_scrips: set[str] = set()


def trigger_github_workflow(scrip: str, ipo_name: str) -> bool:
    """Trigger apply_ipo.yml with the specific scrip and IPO name."""
    url = (
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
        f"/actions/workflows/{GITHUB_WORKFLOW_FILE}/dispatches"
    )
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "ref": "main",
        "inputs": {
            "scrip":    scrip,
            "ipo_name": ipo_name,
        },
    }
    r = requests.post(url, json=payload, headers=headers, timeout=10)
    return r.status_code == 204


# ─────────────────────────────────────────────
intents = discord.Intents.default()
bot     = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Button handler bot online as {bot.user}")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="for IPO confirmations"
        )
    )


@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return

    custom_id = interaction.data.get("custom_id", "")

    # ── Permission check ─────────────────────────────────────
    if ALLOWED_USER_IDS and interaction.user.id not in ALLOWED_USER_IDS:
        await interaction.response.send_message(
            "⛔ You are not authorised to do this.", ephemeral=True
        )
        return

    # ── Parse action and scrip from custom_id ─────────────────
    # Format: "apply_ipo:SCRIP" or "skip_ipo:SCRIP"
    if ":" not in custom_id:
        return

    action, scrip = custom_id.split(":", 1)
    scrip = scrip.strip().upper()

    # Extract IPO name from the embed title if available
    ipo_name = scrip  # fallback
    try:
        if interaction.message.embeds:
            title = interaction.message.embeds[0].title or ""
            # Title: "🔔 IPO Open: Company Name (SCRIP)"
            if "IPO Open:" in title:
                ipo_name = title.split("IPO Open:")[-1].strip()
    except Exception:
        pass

    # ── Apply button ─────────────────────────────────────────
    if action == "apply_ipo":

        # Prevent double-clicking the same IPO
        if scrip in _running_scrips:
            await interaction.response.send_message(
                f"⚠️ Application for **{scrip}** is already in progress.", ephemeral=True
            )
            return

        await interaction.response.defer()
        _running_scrips.add(scrip)

        success = trigger_github_workflow(scrip=scrip, ipo_name=ipo_name)

        if success:
            # Disable the buttons on the original message
            try:
                await interaction.message.edit(
                    content=(
                        f"✅ **{ipo_name}** — application triggered by "
                        f"{interaction.user.mention}. Live updates below."
                    ),
                    components=[],
                )
            except Exception:
                pass

            await interaction.followup.send(
                embed=discord.Embed(
                    title=f"🚀 Workflow Triggered — {ipo_name}",
                    description=(
                        f"GitHub Actions is now applying **{scrip}** for all accounts.\n"
                        f"You'll receive a ✅/❌ notification per account as they complete."
                    ),
                    color=0x2ECC71,
                ).set_footer(text=f"Triggered by {interaction.user.display_name}"),
            )
        else:
            _running_scrips.discard(scrip)
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Failed to Trigger Workflow",
                    description=(
                        "Could not reach GitHub Actions. Check:\n"
                        "• `GITHUB_TOKEN` has `repo` + `workflow` scopes\n"
                        "• `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_WORKFLOW_FILE` are correct\n"
                        "• The workflow file is on the `main` branch"
                    ),
                    color=0xE74C3C,
                ),
                ephemeral=True,
            )

    # ── Skip button ───────────────────────────────────────────
    elif action == "skip_ipo":
        await interaction.response.defer()
        try:
            await interaction.message.edit(
                content=f"⏭️ **{ipo_name}** skipped by {interaction.user.mention}.",
                components=[],
            )
        except Exception:
            pass
        await interaction.followup.send(
            f"Skipped **{ipo_name}**. No applications will be made.", ephemeral=True
        )


# ─────────────────────────────────────────────
if __name__ == "__main__":
    missing = [k for k, v in {
        "DISCORD_BOT_TOKEN": DISCORD_BOT_TOKEN,
        "GITHUB_TOKEN":      GITHUB_TOKEN,
        "GITHUB_OWNER":      GITHUB_OWNER,
        "GITHUB_REPO":       GITHUB_REPO,
    }.items() if not v]

    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

    bot.run(DISCORD_BOT_TOKEN)
