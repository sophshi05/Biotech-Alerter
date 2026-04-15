import logging
import os

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


@app.route("/api/companies")
def api_companies():
    from companies import get_all_companies
    conn = get_db()
    rows = get_all_companies(conn)
    result = []
    for r in rows:
        cik_int = int(r["cik"])
        result.append({
            "ticker": r["ticker"],
            "cik": r["cik"],
            "name": r["name"],
            "bamsec_url": f"https://www.bamsec.com/companies/{cik_int}/",
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


@app.route("/api/summary/<accession_no>")
def api_summary(accession_no: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT summary, primary_doc_url FROM filings WHERE accession_no = %s",
        (accession_no,),
    )
    row = cur.fetchone()
    cur.close()

    if not row:
        return jsonify({"summary": ""}), 404

    if row["summary"]:
        return jsonify({"summary": row["summary"]})

    from fetcher import fetch_filing_summary
    import requests as req
    session = req.Session()
    summary = fetch_filing_summary(row["primary_doc_url"], session)
    session.close()

    if summary:
        cur = conn.cursor()
        cur.execute(
            "UPDATE filings SET summary = %s WHERE accession_no = %s",
            (summary, accession_no),
        )
        conn.commit()
        cur.close()

    return jsonify({"summary": summary})


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
# Startup
# ---------------------------------------------------------------------------

def _startup():
    from companies import get_db_connection, init_db, resolve_companies
    conn = get_db_connection()
    try:
        init_db(conn)
        resolve_companies(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    _startup()
    app.run(debug=False, threaded=True, port=8080)
