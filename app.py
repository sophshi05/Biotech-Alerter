import logging
import os
import re

from flask import Flask, g, jsonify, render_template, request
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# DB helpers (per-request connection via Flask g)
# ---------------------------------------------------------------------------

def get_db():
    from companies import get_db_connection
    if "db" not in g:
        g.db = get_db_connection()
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


def _make_slug(name: str) -> str:
    """Convert a company name to a BAMSec URL slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@app.route("/api/companies")
def api_companies():
    from companies import get_all_companies
    conn = get_db()
    rows = get_all_companies(conn)
    result = []
    for r in rows:
        cik_int = int(r["cik"])
        slug = _make_slug(r["name"])
        result.append({
            "ticker": r["ticker"],
            "cik": r["cik"],
            "name": r["name"],
            "bamsec_url": f"https://www.bamsec.com/companies/{cik_int}/{slug}",
        })
    return jsonify(result)


@app.route("/api/news")
def api_news():
    from fetcher import get_recent_news, get_last_refreshed
    conn = get_db()
    try:
        days = int(request.args.get("days", 30))
        days = max(1, min(days, 365))
    except (ValueError, TypeError):
        days = 30
    filings = get_recent_news(conn, days=days)
    last_refreshed = get_last_refreshed(conn)
    return jsonify({"filings": filings, "last_refreshed": last_refreshed})


@app.route("/api/news/<cik>")
def api_news_by_cik(cik: str):
    from fetcher import _get_cached_filings, get_last_refreshed
    conn = get_db()
    try:
        cik_padded = f"{int(cik):010d}"
    except ValueError:
        return jsonify({"error": "Invalid CIK"}), 400
    filings = _get_cached_filings(conn, cik_padded)
    last_refreshed = get_last_refreshed(conn)
    return jsonify({"filings": filings, "last_refreshed": last_refreshed})



@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    secret = os.environ.get("REFRESH_SECRET", "")
    if secret:
        provided = request.headers.get("X-Refresh-Secret", "")
        if provided != secret:
            return jsonify({"error": "Unauthorized"}), 401

    from fetcher import refresh_all_companies, get_recent_news, get_last_refreshed
    conn = get_db()
    count, new_accession_nos = refresh_all_companies(conn)
    filings = get_recent_news(conn)
    last_refreshed = get_last_refreshed(conn)

    return jsonify({
        "companies_refreshed": count,
        "new_accession_nos": list(new_accession_nos),
        "filings": filings,
        "last_refreshed": last_refreshed,
    })


# ---------------------------------------------------------------------------
# Startup — runs on cold start (module import) AND locally
# ---------------------------------------------------------------------------

def _startup():
    from companies import get_db_connection, init_db, resolve_companies
    conn = get_db_connection()
    try:
        init_db(conn)
        resolve_companies(conn)
    finally:
        conn.close()


# Run on every cold start (Vercel imports this file as a module).
# init_db uses CREATE TABLE IF NOT EXISTS so it's safe to call repeatedly.
try:
    _startup()
except Exception as _e:
    logger.error(f"Startup error: {_e}")

if __name__ == "__main__":
    app.run(debug=False, threaded=True, port=8080)
