# MeroShare IPO Bot

Automatically checks MeroShare for open IPOs twice a week and lets you apply
for all accounts with a single Discord button click. Completely free to run —
no servers, no credit card required.

---

## Architecture

```
GitHub Actions cron (Mon & Thu 8:45 AM NPT)
        │
        ▼
check_ipo.py — logs into MeroShare, scrapes ASBA page
        │
        ├── No IPO open → silent, does nothing
        │
        └── IPO found → Discord message with [✅ Apply] [❌ Skip] buttons
                              │
                        You click ✅ Apply
                              │
                              ▼
                   Cloudflare Worker (worker.js)
                   receives button click from Discord
                   → verifies signature
                   → calls GitHub API
                              │
                              ▼
                   GitHub Actions (apply_ipo.yml)
                   → reads accounts from Google Sheets
                   → opens headless Chrome
                   → logs into MeroShare for each account
                   → applies for the IPO
                              │
                              ▼
                   Discord webhook notifications
                   (✅/❌ per account + final summary)
```

---

## Files

| File | Purpose | Runs on |
|---|---|---|
| `check_ipo.py` | Logs into MeroShare, scrapes open IPOs, sends Discord alert | GitHub Actions |
| `apply_all.py` | Reads Google Sheets accounts, applies IPO for each | GitHub Actions |
| `ipobot.py` | Selenium browser automation for MeroShare | Called by apply_all.py |
| `discord_notifier.py` | Sends webhook notifications to Discord | Called by apply_all.py |
| `worker.js` | Handles Discord button clicks, triggers GitHub workflow | Cloudflare Workers |
| `.github/workflows/check_ipo.yml` | Cron + manual IPO check workflow | GitHub Actions |
| `.github/workflows/apply_ipo.yml` | IPO apply workflow, triggered by Cloudflare | GitHub Actions |
| `requirements.txt` | Python dependencies | GitHub Actions |

---

## What Lives Where

| Component | Platform | Cost |
|---|---|---|
| Code + workflows | GitHub (private repo) | Free |
| Button handler | Cloudflare Workers | Free (100k req/day) |
| Accounts data | Google Sheets | Free |
| Credentials | GitHub Secrets + Cloudflare Variables | Free |
| Notifications | Discord Webhook | Free |

---

## Setup Guide

### 1 — Discord

1. Go to **https://discord.com/developers/applications** → **New Application**
2. Name it anything → **Create**
3. **General Information** tab → copy and save:
   - **Application ID** → `DISCORD_APP_ID`
   - **Public Key** → `DISCORD_PUBLIC_KEY`
4. **Bot** tab → **Reset Token** → copy and save as `DISCORD_BOT_TOKEN`
5. Scroll down → enable **Message Content Intent**
6. Invite the bot to your server:
   - Go to `https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&permissions=52224&scope=bot`
   - Replace `YOUR_APP_ID` with your Application ID
   - Select your server → **Authorise**
7. In Discord, enable **Developer Mode**: Settings → Advanced → Developer Mode → ON
8. Right-click the channel you want alerts in → **Copy Channel ID** → save as `DISCORD_CHANNEL_ID`
9. Edit that channel → **Integrations → Webhooks → New Webhook** → copy URL → save as `DISCORD_WEBHOOK_URL`

---

### 2 — Google Sheets

1. Go to **https://sheets.google.com** → create a new blank sheet
2. Row 1 headers (exact, case-insensitive):
   ```
   Name | DP | Username | Password | CRN | PIN
   ```
3. Fill in your accounts from row 2 onwards
4. **Important:** Select the CRN column → Format → Number → **Plain text**. Do the same for the PIN column. This preserves leading zeros.
5. Copy the Sheet ID from the URL:
   ```
   https://docs.google.com/spreadsheets/d/COPY_THIS_PART/edit
   ```
   Save as `GOOGLE_SHEET_ID`

**Create a Google Service Account:**
1. Go to **https://console.cloud.google.com** → create a new project
2. Search **Google Sheets API** → Enable
3. Search **Google Drive API** → Enable
4. Left sidebar → **IAM & Admin → Service Accounts → Create Service Account**
5. Give it any name → **Done**
6. Click the service account → **Keys → Add Key → Create new key → JSON** → download
7. Open the downloaded JSON → copy the entire file contents → save as `GOOGLE_SERVICE_ACCOUNT`
8. Copy the `client_email` field from the JSON (looks like `name@project.iam.gserviceaccount.com`)
9. Back in your Google Sheet → **Share** → paste the service account email → set to **Viewer** → Send

---

### 3 — GitHub Repository

1. Go to **https://github.com/new** → create a **private** repo named `meroshare-ipo-bot`
2. Upload these files maintaining the exact folder structure:
   ```
   meroshare-ipo-bot/
   ├── .github/
   │   └── workflows/
   │       ├── check_ipo.yml
   │       └── apply_ipo.yml
   ├── apply_all.py
   ├── check_ipo.py
   ├── ipobot.py
   ├── discord_notifier.py
   └── requirements.txt
   ```
   > Note: `worker.js` is deployed directly to Cloudflare — it does NOT go in the repo.

3. Go to **Settings → Actions → General → Workflow permissions** → select **Read and write permissions** → Save

4. Go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Value |
|---|---|
| `DISCORD_BOT_TOKEN` | Your Discord bot token |
| `DISCORD_CHANNEL_ID` | Channel ID for IPO alerts |
| `DISCORD_WEBHOOK_URL` | Webhook URL for apply notifications |
| `GOOGLE_SHEET_ID` | Your Google Sheet ID |
| `GOOGLE_SERVICE_ACCOUNT` | Full contents of the service account JSON |
| `APPLIED_KITTA` | `10` (or `100` for mutual funds) |

---

### 4 — GitHub Personal Access Token

The Cloudflare Worker needs this to trigger GitHub Actions when you click Apply.

1. Go to **https://github.com/settings/tokens** → **Generate new token (classic)**
2. Name: `meroshare-bot`
3. Scopes: ✅ `repo` ✅ `workflow`
4. Click **Generate token** → copy immediately (shown once only) → save as `GITHUB_TOKEN`

---

### 5 — Cloudflare Workers

1. Go to **https://cloudflare.com** → sign up free (no credit card)
2. Dashboard → **Workers & Pages** → **Create** → **Create Worker**
3. Name it `meroshare-ipo-bot` → **Deploy**
4. Click **Edit Code** → delete all existing code → paste the full contents of `worker.js` → **Deploy**
5. Go to **Settings → Variables → Environment Variables** → add each variable below, then click **Save and deploy**:

| Variable | Type | Value |
|---|---|---|
| `DISCORD_PUBLIC_KEY` | Text | Public Key from Discord → General Information |
| `DISCORD_APP_ID` | Text | Application ID from Discord → General Information |
| `DISCORD_BOT_TOKEN` | Secret | Your Discord bot token |
| `GITHUB_TOKEN` | Secret | GitHub PAT from Step 4 |
| `GITHUB_OWNER` | Text | Your GitHub username |
| `GITHUB_REPO` | Text | `meroshare-ipo-bot` |
| `GITHUB_WORKFLOW_FILE` | Text | `apply_ipo.yml` |
| `ALLOWED_USER_IDS` | Text | Your Discord user ID (right-click your name in Discord → Copy User ID) |

6. Copy your Worker URL from the top of the page:
   ```
   https://meroshare-ipo-bot.YOUR-SUBDOMAIN.workers.dev
   ```

---

### 6 — Connect Discord to Cloudflare

1. Go to **https://discord.com/developers/applications** → your app → **General Information**
2. Find **Interactions Endpoint URL**
3. Paste your Cloudflare Worker URL
4. Click **Save Changes**

Discord sends a verification PING to your Worker. If everything is set up correctly it responds and Discord shows a green checkmark. If it fails, check that `DISCORD_PUBLIC_KEY` is correct in Cloudflare and that the Worker code was deployed (not just saved).

---

## Testing

**Test 1 — Worker is alive:**
Open your Worker URL in a browser. You should see `Method Not Allowed`. This confirms the Worker is running.

**Test 2 — Full flow:**
1. GitHub → Actions → **Check for Open IPOs** → **Run workflow**
2. Wait for it to complete — you should get a Discord message with Apply/Skip buttons
3. Click **✅ Apply**
4. Watch Cloudflare logs (Worker → Logs → Begin log stream) for the request
5. GitHub → Actions should show a new **Apply IPO** run starting
6. Discord webhook should post per-account results and a final summary

**Test 3 — Manual apply (bypass Discord button):**
GitHub → Actions → **Apply IPO** → **Run workflow** → enter scrip manually (e.g. `KAHL`)

---

## Usage

Every **Monday and Thursday at 8:45 AM Nepal time**, `check_ipo.py` runs automatically.

- **No IPO open** → silent, nothing happens, no notifications
- **IPO found** → Discord alert with company name, type, dates, price, min/max kitta + Apply and Skip buttons
- **Click ✅ Apply** → Cloudflare triggers GitHub Actions → applies for all accounts → Discord notifications per account + summary
- **Click ❌ Skip** → buttons removed, no application made

**Manual triggers** (GitHub → Actions):
- **Check for Open IPOs** → run the IPO check right now
- **Apply IPO** → apply directly without Discord, type the scrip when prompted

---

## Google Sheet Format

| Name | DP | Username | Password | CRN | PIN |
|---|---|---|---|---|---|
| Ram Sharma | GLOBAL IME CAPITAL LIMITED (11200) | 9841000001 | password1 | 005006148 | 1234 |
| Sita Thapa | NMB CAPITAL LIMITED (11300) | 9841000002 | password2 | 7654321 | 5678 |

- **DP** must be the full name exactly as shown in MeroShare's dropdown, including the number in brackets
- **Username** is your MeroShare login (usually your phone number)
- **CRN** is your bank CRN/account number for ASBA — format the column as Plain Text to preserve leading zeros
- **PIN** is your 4-digit MeroShare transaction PIN

---

## Secrets Reference

### GitHub Secrets
| Secret | Description |
|---|---|
| `DISCORD_BOT_TOKEN` | Discord bot token — used by check_ipo.py to post alerts |
| `DISCORD_CHANNEL_ID` | Channel where IPO alerts are posted |
| `DISCORD_WEBHOOK_URL` | Webhook for apply notifications |
| `GOOGLE_SHEET_ID` | ID from your Google Sheet URL |
| `GOOGLE_SERVICE_ACCOUNT` | Full service account JSON (entire file contents) |
| `APPLIED_KITTA` | Number of kitta to apply per account |

### Cloudflare Variables
| Variable | Description |
|---|---|
| `DISCORD_PUBLIC_KEY` | Used to verify button click requests came from Discord |
| `DISCORD_APP_ID` | Your Discord application ID |
| `DISCORD_BOT_TOKEN` | Used to edit messages (remove buttons after clicking) |
| `GITHUB_TOKEN` | PAT used to trigger apply_ipo.yml workflow |
| `GITHUB_OWNER` | Your GitHub username |
| `GITHUB_REPO` | Your repo name |
| `GITHUB_WORKFLOW_FILE` | `apply_ipo.yml` |
| `ALLOWED_USER_IDS` | Comma-separated Discord user IDs allowed to click Apply |
