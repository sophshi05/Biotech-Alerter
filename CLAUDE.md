# Biotech Alerter — Codebase Guide

## What This Is

A Flask web app that tracks SEC 8-K filings ("news") for ~49 major public biotech companies. It pulls data directly from SEC EDGAR's public API, caches everything in Neon (serverless Postgres), and displays filings as a news feed. Clicking **Refresh** fetches any filings that have arrived since the last pull and highlights them with a NEW badge.

Deployed on Vercel at `biotech-alerter.vercel.app`. No scheduler, no background jobs — all data loading is on-demand.

---

## File Structure

```
biotech-alerter/
├── app.py           # Flask entry point — routes + DB startup
├── companies.py     # Ticker list, CIK resolution, companies table
├── fetcher.py       # EDGAR API client, Postgres caching, summaries
├── templates/
│   └── index.html   # Single-page frontend (plain JS, no framework)
├── static/
│   └── style.css    # Minimal styles
├── vercel.json      # Vercel routing config
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `POSTGRES_URL` | Yes | Neon/Postgres connection string (auto-set by Vercel when you link a Postgres store) |
| `REFRESH_SECRET` | No | If set, `POST /api/refresh` requires `X-Refresh-Secret: <value>` header |

For local dev, copy `.env.example` → `.env` and fill in `POSTGRES_URL` (copy from Vercel dashboard → Settings → Environment Variables).

---

## Running Locally

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in POSTGRES_URL
python app.py          # runs on http://localhost:8080
```

On first run, `_startup()` creates the DB tables and resolves CIKs for all tickers. Then click **Refresh** on the site to pull the initial filings from EDGAR (~49 API calls, takes ~10s).

---

## Architecture

### Data Flow

1. **Startup** (`_startup()` in `app.py`): runs on every cold start (module import). Creates Postgres tables if they don't exist, then calls `resolve_companies()` to populate the `companies` table from SEC EDGAR's `company_tickers.json`.

2. **Refresh** (`POST /api/refresh`): iterates all 49 companies, fetches each company's filing list from `data.sec.gov/submissions/CIK{cik}.json`, inserts new 8-K/8-K/A rows into `filings` (`ON CONFLICT DO NOTHING`). Returns the list of newly inserted accession numbers so the frontend can badge them `NEW`.

3. **Display** (`GET /api/news`): pure Postgres query, no EDGAR calls. Returns filings from the last 30 days sorted by date.

4. **Summaries** (`GET /api/summary/<accession_no>`): fetches the filing's HTML from SEC, strips tags with BeautifulSoup, extracts the first substantive sentence, caches in the `summary` column permanently.

### Caching Strategy

- **Company list** (`companies` table): refreshed from EDGAR every 7 days. Cached locally — most cold starts skip the EDGAR call entirely.
- **Filing lists** (`cache_meta` TTL per CIK): 2-hour TTL. Within 2 hours, `fetch_company_filings()` returns from Postgres without hitting EDGAR.
- **Summaries** (`filings.summary`): cached forever by accession number. SEC filings are immutable once published.
- **Rate limiting**: 0.15s delay between every EDGAR API call. Up to 3 retries with exponential backoff on 429/503.

### "New" Filing Detection

Each filing row has a `first_seen_at` Unix timestamp set on INSERT and never updated. When `fetch_company_filings()` does `INSERT ... ON CONFLICT DO NOTHING`, it checks `cur.rowcount == 1` to know if the row was actually new. These accession numbers are returned up through `refresh_all_companies()` → `/api/refresh` → frontend, which renders the `NEW` badge.

---

## Database Schema

```sql
companies (
    ticker       TEXT PRIMARY KEY,
    cik          TEXT NOT NULL,          -- zero-padded 10 digits, e.g. "0001792789"
    name         TEXT NOT NULL,
    last_updated DOUBLE PRECISION        -- Unix timestamp
)

filings (
    accession_no    TEXT PRIMARY KEY,    -- e.g. "0001564590-24-000123"
    cik             TEXT NOT NULL,
    ticker          TEXT,
    company_name    TEXT,
    form_type       TEXT NOT NULL,       -- "8-K" or "8-K/A"
    filed_date      TEXT NOT NULL,       -- "YYYY-MM-DD" (sorts correctly as text)
    title           TEXT,               -- SEC "items" field, e.g. "2.02,9.01"
    primary_doc_url TEXT,               -- direct link to the filing HTML on sec.gov
    summary         TEXT,               -- first substantive sentence, cached forever
    first_seen_at   DOUBLE PRECISION,   -- Unix timestamp of first insert
    last_updated    DOUBLE PRECISION
)

cache_meta (
    key          TEXT PRIMARY KEY,      -- e.g. "filings_last_refresh:0001792789"
    value        TEXT NOT NULL,
    last_updated DOUBLE PRECISION
)
```

Key `cache_meta` entries:
- `filings_last_refresh:{cik}` — timestamp of last EDGAR fetch per company
- `last_global_refresh` — ISO timestamp of last full refresh (shown on UI)

---

## API Routes

| Method | Route | Description |
|---|---|---|
| `GET` | `/` | Serves `index.html` |
| `GET` | `/api/companies` | All tracked companies with BAMSec URL |
| `GET` | `/api/news?days=30` | Recent 8-K filings across all companies |
| `GET` | `/api/news/<cik>` | Filings for a single company by CIK |
| `GET` | `/api/summary/<accession_no>` | One-sentence summary for a filing (fetches + caches on demand) |
| `POST` | `/api/refresh` | Pull new filings from EDGAR; returns `{filings, new_accession_nos, last_refreshed}` |

---

## Company List

Defined in `companies.py` as `BIOTECH_TICKERS` — 49 hardcoded tickers. CIKs are resolved at runtime from `https://www.sec.gov/files/company_tickers.json` (one fetch per week). To add a company, add its ticker to `BIOTECH_TICKERS`. To remove one, remove it from the list (existing DB rows persist but won't appear in the sidebar after the next company refresh).

Current list: MRNA, BIIB, REGN, GILD, AMGN, VRTX, ALNY, BMRN, INCY, SRPT, ILMN, BPMC, EXAS, NTLA, BEAM, EDIT, CRSP, RXRX, ACAD, RARE, FOLD, IONS, PTCT, ARWR, DNTH, KYMR, RVMD, KDNY, ROIVT, SDGR, LEGN, PRAX, APLS, INSM, ADMA, ARQT, DAWN, IMVT, CORT, MDGL, AKRO, NKTR, BHVN, AGEN, ARDX, FATE, ABCL, TGTX

Some tickers (SGEN, ILMN post-merger) may not resolve — missing tickers are logged and skipped, never fatal.

---

## EDGAR API Notes

- All requests require `User-Agent: BiotechAlerter daniel4duan@gmail.com` header (SEC requirement).
- Submissions endpoint: `https://data.sec.gov/submissions/CIK{10-digit-zero-padded}.json`
- Response has `filings.recent` with parallel arrays: `accessionNumber`, `filingDate`, `form`, `primaryDocument`, `items`. Filter `form == "8-K"` or `"8-K/A"` for news.
- Filing URL: `https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{primaryDocument}`
- The `items` field is the filing "title" (e.g. `"2.02,9.01"` = Results of Operations + Financial Statements). Can be empty for amendments.

---

## Deployment (Vercel)

Deployed via `vercel.json` which routes all traffic to `app.py` using `@vercel/python`.

To redeploy after code changes:
```bash
git add -A && git commit -m "..." && git push
```
Vercel auto-deploys on push to `main`.

`_startup()` runs on every cold start (Vercel imports `app.py` as a module, so it's called at module level). `init_db()` uses `CREATE TABLE IF NOT EXISTS` so it's safe to call repeatedly.

The Neon Postgres database is linked to the Vercel project — `POSTGRES_URL` is injected automatically into the runtime environment.
