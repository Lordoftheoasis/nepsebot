# MeroShare IPO Bot

Automatically checks for open IPOs twice a week and lets you apply for all
accounts with a single Discord button click. Free to run.

---

## Architecture

```
GitHub Actions cron (Mon & Thu 8:45 AM NPT)
        │
        ▼
check_ipo.py → MeroShare API
        │
        ├── No IPO open → does nothing
        │
        └── IPO found → Discord message with [✅ Apply] [❌ Skip] buttons
                              │
                        You click ✅ Apply
                              │
                              ▼
                        bot.py (Railway) receives click
                        → calls GitHub API → triggers apply_ipo.yml
                              │
                              ▼
                        GitHub Actions runner
                        → reads accounts from Google Sheets
                        → opens Chrome (headless) → MeroShare
                        → applies for every account
                              │
                              ▼
                        Discord webhook notifications
                        (per account ✅/❌ + final summary)
```

---

## Files

| File | Purpose | Runs on |
|---|---|---|
| `check_ipo.py` | Scrapes MeroShare for open IPOs, sends Discord alert | GitHub Actions (cron) |
| `apply_all.py` | Reads Google Sheets, applies IPO for all accounts | GitHub Actions (on demand) |
| `ipobot.py` | Selenium browser automation for MeroShare | Called by apply_all.py |
| `discord_notifier.py` | Webhook notifications | Called by apply_all.py |
| `bot.py` | Handles Discord button clicks, triggers GitHub workflow | Railway (24/7) |
| `.github/workflows/check_ipo.yml` | Cron workflow | GitHub Actions |
| `.github/workflows/apply_ipo.yml` | Apply workflow (triggered by bot) | GitHub Actions |

---

## Setup Guide

### 1. Discord Bot & Server

1. Go to https://discord.com/developers/applications → **New Application**
2. **Bot** tab → **Reset Token** → copy the token → save as `DISCORD_BOT_TOKEN`
3. Enable **"Message Content Intent"** under Privileged Gateway Intents
4. **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Permissions: `Send Messages`, `Embed Links`, `Read Message History`
5. Open the URL → invite the bot to your server
6. Go to the channel you want alerts in → right click → **Copy Channel ID** → save as `DISCORD_CHANNEL_ID`
7. In the same channel → **Edit Channel → Integrations → Webhooks → New Webhook** → copy URL → save as `DISCORD_WEBHOOK_URL`

---

### 2. Google Sheets (accounts storage)

1. Go to https://sheets.google.com → create a new sheet named **MeroShare Accounts**
2. Row 1 headers (exact): `Name | DP | Username | Password | CRN | PIN`
3. Fill in your accounts from row 2 onwards
4. Copy the Sheet ID from the URL:
   `https://docs.google.com/spreadsheets/d/THIS_PART_HERE/edit`
   Save as `GOOGLE_SHEET_ID`

**Create a Service Account (so GitHub can read the sheet):**
1. Go to https://console.cloud.google.com
2. Create a new project (or use existing)
3. Enable **Google Sheets API** and **Google Drive API**
4. **IAM & Admin → Service Accounts → Create Service Account**
5. Give it any name, click **Done**
6. Click the service account → **Keys → Add Key → JSON** → download the file
7. Open the JSON file, copy the entire contents → save as `GOOGLE_SERVICE_ACCOUNT`
8. Back in your Google Sheet → **Share** → paste the service account email (found in the JSON as `client_email`) → give **Viewer** access

---

### 3. GitHub Repository

1. Create a **private** repo at https://github.com/new
2. Upload all files from this project
3. Go to **Settings → Secrets and variables → Actions → New repository secret**

Add these secrets:

| Secret Name | Value |
|---|---|
| `DISCORD_BOT_TOKEN` | Your Discord bot token |
| `DISCORD_CHANNEL_ID` | Channel ID for alerts |
| `DISCORD_WEBHOOK_URL` | Webhook URL for notifications |
| `GOOGLE_SHEET_ID` | Your Google Sheet ID |
| `GOOGLE_SERVICE_ACCOUNT` | Full contents of the service account JSON |
| `APPLIED_KITTA` | `10` (or `100` for mutual funds) |

4. Go to **Settings → Actions → General → Workflow permissions** → enable **Read and write permissions**

---

### 4. GitHub Personal Access Token (for bot to trigger workflows)

1. Go to https://github.com/settings/tokens → **Generate new token (classic)**
2. Scopes: ✅ `repo`, ✅ `workflow`
3. Copy the token → save as `GITHUB_TOKEN`

---

### 5. Railway (hosts the Discord button handler bot)

1. Go to https://railway.app → sign up with GitHub (free)
2. **New Project → Deploy from GitHub repo** → select your repo
3. Railway will detect the `Procfile` and run `bot.py`
4. Go to **Variables** tab → add:

| Variable | Value |
|---|---|
| `DISCORD_BOT_TOKEN` | your bot token |
| `GITHUB_TOKEN` | your GitHub PAT |
| `GITHUB_OWNER` | your GitHub username |
| `GITHUB_REPO` | `meroshare-ipo-bot` |
| `GITHUB_WORKFLOW_FILE` | `apply_ipo.yml` |
| `ALLOWED_USER_IDS` | your Discord user ID (right-click your name → Copy ID) |

5. Deploy — the bot is now live 24/7

---

## Usage

- **Automatic**: Every Monday and Thursday at 8:45 AM NPT, `check_ipo.py` runs.
  - If no IPO is open: silent, nothing happens.
  - If an IPO is open: you get a Discord message with **Apply** and **Skip** buttons.
- **Manual check**: Go to GitHub → Actions → Check for Open IPOs → Run workflow
- **Apply**: Click ✅ in Discord. Bot triggers GitHub Actions. You get notified per account.

---

## Local Development

```bash
pip install -r requirements.txt
# Add accounts to accounts.xlsx
python check_ipo.py        # test IPO check (set env vars first)
python apply_all.py        # test applying (uses accounts.xlsx locally)
python bot.py              # run bot locally
```
