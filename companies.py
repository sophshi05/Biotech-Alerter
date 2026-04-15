import os
import time
import logging

import psycopg2
import psycopg2.extras
import requests

logger = logging.getLogger(__name__)

BIOTECH_TICKERS = [
    "MRNA", "BIIB", "REGN", "GILD", "AMGN", "VRTX", "ALNY", "BMRN", "INCY",
    "SRPT", "ILMN", "BPMC", "EXAS", "NTLA", "BEAM", "EDIT", "CRSP", "RXRX",
    "ACAD", "RARE", "FOLD", "IONS", "PTCT", "ARWR", "DNTH", "KYMR", "RVMD",
    "KDNY", "ROIVT", "SDGR", "LEGN", "PRAX", "APLS", "INSM", "ADMA", "ARQT",
    "DAWN", "IMVT", "CORT", "MDGL", "AKRO", "NKTR", "BHVN", "AGEN", "ARDX",
    "FATE", "ABCL", "TGTX",
]

COMPANY_TTL = 7 * 24 * 3600  # 7 days
USER_AGENT = "BiotechAlerter daniel4duan@gmail.com"


def get_db_connection():
    conn = psycopg2.connect(
        os.environ["POSTGRES_URL"],
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    return conn


def init_db(conn) -> None:
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            ticker       TEXT PRIMARY KEY,
            cik          TEXT NOT NULL,
            name         TEXT NOT NULL,
            last_updated DOUBLE PRECISION NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS filings (
            accession_no    TEXT PRIMARY KEY,
            cik             TEXT NOT NULL,
            ticker          TEXT,
            company_name    TEXT,
            form_type       TEXT NOT NULL,
            filed_date      TEXT NOT NULL,
            title           TEXT,
            primary_doc_url TEXT,
            summary         TEXT,
            first_seen_at   DOUBLE PRECISION,
            last_updated    DOUBLE PRECISION NOT NULL
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_filings_filed_date ON filings(filed_date DESC)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_filings_cik ON filings(cik)
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cache_meta (
            key          TEXT PRIMARY KEY,
            value        TEXT NOT NULL,
            last_updated DOUBLE PRECISION NOT NULL
        )
    """)

    # Migrations: add columns that may not exist in older DBs
    cur.execute("""
        ALTER TABLE filings ADD COLUMN IF NOT EXISTS summary TEXT
    """)
    cur.execute("""
        ALTER TABLE filings ADD COLUMN IF NOT EXISTS first_seen_at DOUBLE PRECISION
    """)

    conn.commit()
    cur.close()


def fetch_cik_map() -> dict:
    url = "https://www.sec.gov/files/company_tickers.json"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    result = {}
    for entry in data.values():
        ticker = entry.get("ticker", "").upper()
        cik_int = entry.get("cik_str", 0)
        name = entry.get("title", "")
        if ticker and cik_int:
            result[ticker] = {
                "cik": f"{cik_int:010d}",
                "name": name,
            }
    return result


def resolve_companies(conn) -> None:
    cur = conn.cursor()
    cur.execute("SELECT MIN(last_updated) AS oldest FROM companies")
    row = cur.fetchone()
    cur.close()

    oldest = row["oldest"] if row else None
    is_stale = oldest is None or (time.time() - oldest) > COMPANY_TTL

    if not is_stale:
        logger.info("Company list cache is fresh, skipping EDGAR fetch.")
        return

    logger.info("Fetching company CIK map from EDGAR...")
    try:
        cik_map = fetch_cik_map()
    except Exception as e:
        logger.error(f"Failed to fetch company_tickers.json: {e}")
        return

    now = time.time()
    resolved = 0
    cur = conn.cursor()
    for ticker in BIOTECH_TICKERS:
        entry = cik_map.get(ticker.upper())
        if not entry:
            logger.warning(f"Ticker {ticker} not found in EDGAR — skipping.")
            continue
        cur.execute(
            """INSERT INTO companies (ticker, cik, name, last_updated)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (ticker) DO UPDATE SET
                   cik=EXCLUDED.cik,
                   name=EXCLUDED.name,
                   last_updated=EXCLUDED.last_updated""",
            (ticker, entry["cik"], entry["name"], now),
        )
        resolved += 1

    conn.commit()
    cur.close()
    logger.info(f"Resolved {resolved}/{len(BIOTECH_TICKERS)} biotech companies.")


def get_all_companies(conn) -> list:
    cur = conn.cursor()
    cur.execute("SELECT ticker, cik, name FROM companies ORDER BY name ASC")
    rows = cur.fetchall()
    cur.close()
    return rows
