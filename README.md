# Biotech Alerter

A barebones web app that tracks SEC 8-K filings (news/press releases) for ~49 major public biotech companies. Data is pulled directly from SEC EDGAR. Click **Refresh** to fetch the latest filings — new ones since your last refresh are highlighted with a **NEW** badge.

Live at: [biotech-alerter.vercel.app](https://biotech-alerter.vercel.app)

---

## Features

- News feed of 8-K filings for 49 major biotech companies
- Company sidebar with search/filter
- One-sentence summary per filing extracted from the actual SEC document (no AI, no API key needed)
- NEW badge on filings that appeared since your last refresh
- "Last refreshed" timestamp
- Links to the SEC filing and BAMSec page for each entry
- Deployed on Vercel with Neon (serverless Postgres) for caching

---

## Tracked Companies

MRNA · BIIB · REGN · GILD · AMGN · VRTX · ALNY · BMRN · INCY · SRPT · ILMN · BPMC · EXAS · NTLA · BEAM · EDIT · CRSP · RXRX · ACAD · RARE · FOLD · IONS · PTCT · ARWR · DNTH · KYMR · RVMD · KDNY · ROIVT · SDGR · LEGN · PRAX · APLS · INSM · ADMA · ARQT · DAWN · IMVT · CORT · MDGL · AKRO · NKTR · BHVN · AGEN · ARDX · FATE · ABCL · TGTX

---

## Running Locally

**Prerequisites:** Python 3.9+, a [Neon](https://neon.tech) or Vercel Postgres database.

```bash
git clone https://github.com/sophshi05/Biotech-Alerter.git
cd Biotech-Alerter
pip install -r requirements.txt
cp .env.example .env
# Edit .env — add your POSTGRES_URL
python app.py
```

Open `http://localhost:8080`. Click **Refresh** on the site to load the initial data (takes ~10 seconds on first run).

### Getting POSTGRES_URL

**Easiest (via Vercel):** Deploy the project on Vercel, add a Postgres store (Storage → Create → Neon), then copy `POSTGRES_URL` from Vercel → Settings → Environment Variables into your local `.env`.

**Direct:** Sign up at [neon.tech](https://neon.tech), create a project, copy the connection string from the dashboard.

---

## Deploying to Vercel

1. Fork/push this repo to GitHub
2. Import at [vercel.com](https://vercel.com) → New Project
3. Before deploying: go to **Storage → Create → Postgres (Neon)** and link it to the project
4. Deploy — Vercel installs dependencies and runs the app automatically

After first deploy, open the site and click **Refresh** to populate the database.

---

## Stack

- **Backend:** Python + Flask
- **Database:** Neon (serverless Postgres) via psycopg2
- **Data source:** SEC EDGAR public API (`data.sec.gov`)
- **Summaries:** BeautifulSoup HTML extraction (no AI API needed)
- **Hosting:** Vercel (`@vercel/python`)
- **Frontend:** Plain HTML/CSS/JS, no framework

---

## Adding or Removing Companies

Edit the `BIOTECH_TICKERS` list in `companies.py`, commit, and push. The company list refreshes from EDGAR weekly.
