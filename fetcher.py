import threading
import time
import logging
import re as _re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import requests

logger = logging.getLogger(__name__)

EDGAR_BASE = "https://data.sec.gov/submissions"
USER_AGENT = "BiotechAlerter daniel4duan@gmail.com"
REQUEST_DELAY = 0.12   # ~8 req/sec; SEC allows max 10
FILING_TTL = 7200      # 2 hours (active companies)
MAX_RETRIES = 3
LOOKBACK_DAYS = 30
MAX_WORKERS = 8        # parallel EDGAR fetches


class _RateLimiter:
    """Thread-safe token bucket: ensures requests don't exceed 1/min_interval per second."""
    def __init__(self, min_interval: float):
        self._lock = threading.Lock()
        self._interval = min_interval
        self._last = 0.0

    def wait(self):
        with self._lock:
            now = time.time()
            elapsed = now - self._last
            if elapsed < self._interval:
                time.sleep(self._interval - elapsed)
            self._last = time.time()


# ---------------------------------------------------------------------------
# EDGAR HTTP helpers
# ---------------------------------------------------------------------------

def _make_request(url: str, session: requests.Session) -> dict:
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, headers=headers, timeout=30)
            if resp.status_code in (429, 503):
                wait = 2 ** attempt
                logger.warning(f"Rate limited on {url}, retrying in {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError(f"All retries exhausted for {url}")


def _is_cache_stale(conn, cik: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT last_updated FROM cache_meta WHERE key = %s",
                (f"filings_last_refresh:{cik}",))
    row = cur.fetchone()
    if not row:
        cur.close()
        return True
    last_refresh = row["last_updated"]

    # Dynamic TTL: check active companies often, inactive ones rarely.
    # This keeps typical refreshes fast once the DB is populated.
    cur.execute("SELECT MAX(filed_date) FROM filings WHERE cik = %s", (cik,))
    date_row = cur.fetchone()
    cur.close()

    if date_row and date_row["max"]:
        days_since = (date.today() - date.fromisoformat(date_row["max"])).days
        if days_since <= 30:
            ttl = FILING_TTL          # 2h  — actively filing
        elif days_since <= 90:
            ttl = FILING_TTL * 3      # 6h  — semi-active
        else:
            ttl = FILING_TTL * 12     # 24h — dormant
    else:
        ttl = FILING_TTL              # 2h  — never fetched yet

    return (time.time() - last_refresh) > ttl


def _build_filing_url(cik: str, accession_no: str, primary_document: str) -> str:
    if not primary_document:
        cik_int = int(cik)
        return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_int}&type=8-K&dateb=&owner=include&count=10"
    cik_int = int(cik)
    accession_nodash = accession_no.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{primary_document}"


def _parse_filings(data: dict, cik: str, ticker: str, company_name: str) -> list:
    recent = data.get("filings", {}).get("recent", {})
    accession_numbers = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    forms = recent.get("form", [])
    primary_docs = recent.get("primaryDocument", [])
    items_list = recent.get("items", [])

    results = []
    now = time.time()
    for i, form in enumerate(forms):
        if form not in ("8-K", "8-K/A"):
            continue
        accession_no = accession_numbers[i] if i < len(accession_numbers) else ""
        filed_date = filing_dates[i] if i < len(filing_dates) else ""
        primary_doc = primary_docs[i] if i < len(primary_docs) else ""
        title = items_list[i] if i < len(items_list) else ""

        if not accession_no or not filed_date:
            continue

        results.append({
            "accession_no": accession_no,
            "cik": cik,
            "ticker": ticker,
            "company_name": company_name,
            "form_type": form,
            "filed_date": filed_date,
            "title": title,
            "primary_doc_url": _build_filing_url(cik, accession_no, primary_doc),
            "last_updated": now,
        })
    return results


# ---------------------------------------------------------------------------
# Per-company fetch & cache
# ---------------------------------------------------------------------------

def _get_cached_filings(conn, cik: str) -> list:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM filings WHERE cik = %s ORDER BY filed_date DESC",
        (cik,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    return rows


def fetch_company_filings(
    conn,
    cik: str,
    ticker: str,
    company_name: str,
    session: requests.Session,
    force: bool = False,
    rate_limiter: _RateLimiter = None,
    db_lock: threading.Lock = None,
) -> tuple:
    """Returns (filings: list[dict], new_accession_nos: set[str])."""
    _lock = db_lock or threading.Lock()

    with _lock:
        if not force and not _is_cache_stale(conn, cik):
            return _get_cached_filings(conn, cik), set()

    if rate_limiter:
        rate_limiter.wait()

    url = f"{EDGAR_BASE}/CIK{cik}.json"
    try:
        data = _make_request(url, session)
    except Exception as e:
        logger.error(f"Failed to fetch filings for {ticker} (CIK {cik}): {e}")
        with _lock:
            return _get_cached_filings(conn, cik), set()
    finally:
        if not rate_limiter:
            time.sleep(REQUEST_DELAY)

    filings = _parse_filings(data, cik, ticker, company_name)
    now = time.time()
    new_accession_nos = set()

    with _lock:
        cur = conn.cursor()
        for f in filings:
            cur.execute(
                """INSERT INTO filings
                   (accession_no, cik, ticker, company_name, form_type, filed_date,
                    title, primary_doc_url, first_seen_at, last_updated)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (accession_no) DO NOTHING""",
                (
                    f["accession_no"], f["cik"], f["ticker"], f["company_name"],
                    f["form_type"], f["filed_date"], f["title"],
                    f["primary_doc_url"], now, f["last_updated"],
                ),
            )
            if cur.rowcount == 1:
                new_accession_nos.add(f["accession_no"])

        cur.execute(
            """INSERT INTO cache_meta (key, value, last_updated)
               VALUES (%s, %s, %s)
               ON CONFLICT (key) DO UPDATE SET
                   value=EXCLUDED.value, last_updated=EXCLUDED.last_updated""",
            (f"filings_last_refresh:{cik}", datetime.utcnow().isoformat(), now),
        )
        conn.commit()
        cur.close()

    logger.info(
        f"Fetched {len(filings)} 8-K filings for {ticker} "
        f"({len(new_accession_nos)} new)"
    )
    return filings, new_accession_nos


def refresh_all_companies(conn) -> tuple:
    """Returns (companies_refreshed: int, all_new_accession_nos: set[str])."""
    from companies import get_all_companies
    companies = get_all_companies(conn)
    session = requests.Session()
    rate_limiter = _RateLimiter(REQUEST_DELAY)
    db_lock = threading.Lock()
    all_new = set()
    count = 0

    def _refresh_one(company):
        return fetch_company_filings(
            conn,
            company["cik"],
            company["ticker"],
            company["name"],
            session,
            rate_limiter=rate_limiter,
            db_lock=db_lock,
        )

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_refresh_one, c): c for c in companies}
        for future in as_completed(futures):
            company = futures[future]
            try:
                _, new = future.result()
                all_new |= new
                count += 1
            except Exception as e:
                logger.error(f"Error refreshing {company['ticker']}: {e}")

    # Fetch summaries for newly inserted filings (HTTP outside lock, DB write inside)
    if all_new:
        cur = conn.cursor()
        cur.execute(
            "SELECT accession_no, primary_doc_url FROM filings WHERE accession_no = ANY(%s)",
            (list(all_new),),
        )
        new_rows = cur.fetchall()
        cur.close()
        to_summarize = [
            r for r in new_rows
            if r["primary_doc_url"] and "browse-edgar" not in r["primary_doc_url"]
        ]
        summaries = {}
        for row in to_summarize[:25]:
            summary = fetch_filing_summary(row["primary_doc_url"], session)
            if summary:
                summaries[row["accession_no"]] = summary
        if summaries:
            cur = conn.cursor()
            for accession_no, summary in summaries.items():
                cur.execute(
                    "UPDATE filings SET summary = %s WHERE accession_no = %s",
                    (summary, accession_no),
                )
            conn.commit()
            cur.close()
        logger.info(f"Fetched summaries for up to {min(len(to_summarize), 25)} new filings.")

    # Record global refresh timestamp
    now = time.time()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO cache_meta (key, value, last_updated)
           VALUES (%s, %s, %s)
           ON CONFLICT (key) DO UPDATE SET
               value=EXCLUDED.value, last_updated=EXCLUDED.last_updated""",
        ("last_global_refresh", datetime.utcnow().isoformat(), now),
    )
    conn.commit()
    cur.close()

    session.close()
    logger.info(f"Refresh complete: {count}/{len(companies)} companies, {len(all_new)} new filings.")
    return count, all_new


# ---------------------------------------------------------------------------
# News queries
# ---------------------------------------------------------------------------

def get_recent_news(conn, days: int = LOOKBACK_DAYS) -> list:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    cur = conn.cursor()
    cur.execute(
        """SELECT * FROM filings
           WHERE filed_date >= %s
           ORDER BY filed_date DESC, company_name ASC""",
        (cutoff,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    return rows


def get_last_refreshed(conn) -> str:
    cur = conn.cursor()
    cur.execute(
        "SELECT value FROM cache_meta WHERE key = 'last_global_refresh'",
    )
    row = cur.fetchone()
    cur.close()
    return row["value"] if row else ""


# ---------------------------------------------------------------------------
# Filing summaries (free, no API key — scored sentence extraction)
# ---------------------------------------------------------------------------

_SKIP_PATTERNS = [
    _re.compile(p, _re.IGNORECASE) for p in [
        # SEC header boilerplate
        r"^united states",
        r"^securities and exchange commission",
        r"^washington",
        r"^form 8",
        r"^current report",
        r"pursuant to section 1[35]",
        r"commission file number",
        r"exact name of registrant",
        r"state or other jurisdiction",
        r"^item \d",
        r"check the appropriate box",
        r"^\d{4}$",
        r"^[a-z\s,\.]+, [a-z]{2} \d{5}",
        # Additional header / administrative boilerplate
        r"indicate by check mark",
        r"emerging growth company",
        r"^incorporated in",
        r"telephone.*\d{3}",
        r"^\(\d{3}\)\s*\d{3}",
        r"^trading symbol",
        r"securities registered",
        r"section 12\([bg]\)",
        # Filing-level boilerplate
        r"the (following|foregoing) information.{0,40}(furnished|filed)",
        r"this (current report|information).{0,40}(deemed|not deemed|furnished)",
        r"incorporated by reference",
        r"press release dated",
        r"^exhibit \d",
        r"^for immediate release",
        r"^contact:",
        r"^investor (relations|contact)",
        r"^media contact",
        r"^about [a-z]",          # "About Acme Bio" company description section
        r"safe harbor",
        r"forward.looking statement",
        r"pursuant to general instruction",
        r"^signature",
        r"^dated\b",
        r"^\*+\s*\*+",
        r"^-+\s*-+",
    ]
]

# Signals that a sentence contains the actual news
_SIGNAL_PATTERNS = [
    _re.compile(p, _re.IGNORECASE) for p in [
        r"\bphase [123i]{1,3}\b",
        r"\b(FDA|NDA|BLA|IND|PDUFA|ANDA|EMA|CDER|PRAC)\b",
        r"\b(trial|endpoint|efficacy|patients?|clinical study|cohort)\b",
        r"\b(acqui|merg|licens|partner|collaborat|tender offer)\b",
        r"\b(offering|underwr|placement|priced)\b",
        r"\$[\d,]+",
        r"\b\d+(?:\.\d+)?\s*(?:million|billion)\b",
        r"\b(approved?|granted?|cleared?|designated?|authorized?)\b",
        r"\b(announced?|entered?|agreed?|completed?|executed?|received?|reported?)\b",
        r"\b(today|quarter|fiscal year|Q[1-4]|[12][0-9]{3})\b",
        r"\b(positive|negative|statistically significant|primary endpoint)\b",
        r"\b(drug|compound|candidate|molecule|antibody|therapy|treatment)\b",
    ]
]


def _fetch_filing_text(url: str, session: requests.Session) -> str:
    try:
        resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        logger.debug(f"Could not fetch filing text: {e}")
        return ""
    finally:
        time.sleep(REQUEST_DELAY)

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "table"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def _extract_summary(text: str) -> str:
    text = _re.sub(r"\s+", " ", text).strip()
    sentences = _re.split(r"(?<=[.!?])\s+", text)

    best = ""
    best_score = -1
    first_valid = ""

    for sentence in sentences[:120]:
        s = sentence.strip()
        if len(s) < 60:
            continue
        if any(p.search(s) for p in _SKIP_PATTERNS):
            continue

        score = sum(1 for p in _SIGNAL_PATTERNS if p.search(s))

        if not first_valid:
            first_valid = s
        if score > best_score:
            best_score = score
            best = s
            if score >= 3:  # confident enough — stop scanning
                break

    result = best or first_valid
    return result[:300] + ("..." if len(result) > 300 else "")


def fetch_filing_summary(url: str, session: requests.Session) -> str:
    if not url or "browse-edgar" in url:
        return ""
    return _extract_summary(_fetch_filing_text(url, session))


def populate_missing_summaries(conn, session: requests.Session, days: int = 7) -> int:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    cur = conn.cursor()
    cur.execute(
        """SELECT accession_no, primary_doc_url FROM filings
           WHERE filed_date >= %s AND (summary IS NULL OR summary = '')
           ORDER BY filed_date DESC""",
        (cutoff,),
    )
    rows = cur.fetchall()
    cur.close()

    filled = 0
    cur = conn.cursor()
    for row in rows:
        summary = fetch_filing_summary(row["primary_doc_url"], session)
        if summary:
            cur.execute(
                "UPDATE filings SET summary = %s WHERE accession_no = %s",
                (summary, row["accession_no"]),
            )
            filled += 1

    if filled:
        conn.commit()
    cur.close()
    logger.info(f"Populated {filled} missing summaries.")
    return filled
