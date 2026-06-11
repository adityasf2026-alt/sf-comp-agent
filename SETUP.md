# SF Competitiveness Agent — GitHub Actions Setup

## What this does
Runs automatically at **8:45 AM IST** and **5:45 PM IST** every day.  
Scrapes FK + AZ prices → writes to Google Sheet → Apps Script mailer fires at 9 AM / 6 PM.

---

## Step 1 — Google Cloud: Create Service Account

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project → name it `sf-comp-agent`
3. **Enable APIs:**
   - Search "Google Sheets API" → Enable
4. **Create service account:**
   - IAM & Admin → Service Accounts → Create Service Account
   - Name: `sf-comp-agent`
   - Role: skip (no project role needed)
   - Click Done
5. **Create JSON key:**
   - Click the service account → Keys → Add Key → Create New Key → JSON
   - Download the `.json` file — **keep it safe, never commit to Git**
6. **Note the service account email** (looks like `sf-comp-agent@sf-comp-agent.iam.gserviceaccount.com`)

---

## Step 2 — Share Google Sheet with Service Account

1. Open your [SF Competitiveness Agent sheet](https://docs.google.com/spreadsheets/d/1xeVplg5lAx-GRA-2ypxLi9zxgtjoQ-HsOUd0uAQqu2Y)
2. Click **Share**
3. Add the service account email with **Editor** access
4. Uncheck "Notify people" → Share

---

## Step 3 — GitHub: Create Repo & Add Secret

1. Go to [github.com](https://github.com) → New repository
   - Name: `sf-comp-agent`
   - Private ✅
   - No README (we'll push our files)
2. Push this folder to the repo:
   ```bash
   cd sf-comp-agent
   git init
   git add .
   git commit -m "Initial setup"
   git remote add origin https://github.com/YOUR_USERNAME/sf-comp-agent.git
   git push -u origin main
   ```
3. **Add the secret:**
   - Repo → Settings → Secrets and variables → Actions → New repository secret
   - Name: `GOOGLE_CREDENTIALS`
   - Value: paste the **entire contents** of the JSON key file
   - Save

---

## Step 4 — Test Run

1. Go to your GitHub repo → Actions tab
2. Click **SF Competitiveness Crawl** → Run workflow → Run workflow
3. Watch the logs — should complete in ~20 minutes
4. Check the Crawl Output sheet to confirm rows were written

---

## File Structure
```
sf-comp-agent/
├── src/
│   ├── scraper.py        # Playwright crawl logic
│   └── sheets_writer.py  # Google Sheets read/write
├── .github/
│   └── workflows/
│       └── crawl.yml     # Schedule: 8:45 AM + 5:45 PM IST daily
├── requirements.txt
└── SETUP.md              # This file
```

---

## Schedule
| Time (IST) | What happens |
|------------|-------------|
| 8:45 AM | GitHub Actions crawls FK + AZ, writes to Crawl Output sheet |
| 9:00 AM | Apps Script mailer reads sheet, sends email report |
| 5:45 PM | GitHub Actions crawls FK + AZ, writes to Crawl Output sheet |
| 6:00 PM | Apps Script mailer reads sheet, sends email report |

---

## Troubleshooting
- **Run failed — GOOGLE_CREDENTIALS error:** Check the secret is set and contains valid JSON
- **Prices showing NA:** FK/AZ may have changed page structure — run manually and compare with browser
- **GitHub Actions not triggering:** Cron schedules can be delayed 15-30 min; also check Actions are enabled in repo Settings
- **Sheet not updating:** Confirm service account has Editor access on the sheet
