import os
import time
import logging

import psycopg2
import psycopg2.extras
import requests

logger = logging.getLogger(__name__)

# FinViz Biotechnology screener (2026-04-15) plus large-cap biotech/pharma added manually.
# Add new tickers manually when biotech IPOs occur.
BIOTECH_TICKERS = [
    # A
    "AAPG", "AARD", "ABCL", "ABEO", "ABOS", "ABSI", "ABUS", "ABVC", "ABVX",
    "ACAD", "ACET", "ACHV", "ACIU", "ACLX", "ACOG", "ACRS", "ACRV", "ACTU",
    "ACXP", "ADAG", "ADCT", "ADIL", "ADMA", "ADPT", "ADTX", "ADXN", "AEON",
    "AGEN", "AGIO", "AGMB", "AIM", "AKTS", "AKTX", "ALDX", "ALEC", "ALGS",
    "ALLO", "ALLR", "ALMS", "ALNY", "ALPS", "ALT", "ALXO", "ALZN", "ANAB",
    "ANABV", "ANIX", "ANL", "ANNX", "ANRO", "ANTX", "ANVS", "APGE", "APLM",
    "APLS", "APM", "APRE", "APVO", "ARCT", "ARDX", "ARGX", "ARMP", "ARQT",
    "ARTL", "ARTV", "ARVN", "ARWR", "ASBP", "ASMB", "ASND", "ATAI", "ATHE",
    "ATNM", "ATOS", "ATRA", "ATYR", "AUPH", "AURA", "AUTL", "AVBP", "AVIR",
    "AVTX", "AVXL", "AXSM", "AZTR",
    # B
    "BBIO", "BBLG", "BBOT", "BCAB", "BCAX", "BCDA", "BCTX", "BCYC", "BDRX",
    "BDTX", "BEAM", "BGMS", "BHVN", "BIVI", "BLRX", "BLTE", "BMEA", "BMRN",
    "BNTC", "BNTX", "BOLD", "BOLT", "BRNS", "BRTX", "BYSI",
    # C
    "CABA", "CADL", "CAI", "CALC", "CAMP", "CANF", "CAPR", "CBIO", "CBUS",
    "CCCC", "CDIO", "CDT", "CDXS", "CELC", "CELU", "CELZ", "CGEM", "CGEN",
    "CGON", "CGTX", "CHRS", "CING", "CLDI", "CLDX", "CLGN", "CLLS", "CLNN",
    "CLRB", "CLYM", "CMMB", "CMND", "CMPX", "CNSP", "CNTA", "CNTB", "CNTN",
    "CNTX", "COCP", "COEP", "COGT", "CORT", "COYA", "CPRX", "CRBP", "CRBU",
    "CRDF", "CRIS", "CRMD", "CRNX", "CRSP", "CRVO", "CRVS", "CSBR", "CTMX",
    "CTNM", "CTXR", "CUE", "CURX", "CVKD", "CVM", "CYCN", "CYPH", "CYTK",
    # D
    "DARE", "DAWN", "DBVT", "DCOY", "DFTX", "DMAC", "DMRA", "DNA", "DNLI",
    "DNTH", "DRMA", "DRTS", "DRUG", "DSGN", "DTIL", "DWTX", "DYAI", "DYN",
    # E
    "EDIT", "EDSA", "EIKN", "ELAB", "ELDN", "ELTX", "ELVN", "ENGN", "ENLV",
    "ENSC", "ENTA", "ENTX", "ENVB", "EPRX", "EQ", "ERAS", "ERNA", "ESLA",
    "EVAX", "EVGN", "EVMN", "EWTX", "EXEL", "EXOZ", "EYPT",
    # F
    "FATE", "FBIO", "FBLG", "FBRX", "FDMT", "FENC", "FHTX", "FLNA", "FOLD",
    "FTRE", "FULC",
    # G
    "GALT", "GANX", "GDTC", "GENB", "GERN", "GHRS", "GLMD", "GLPG", "GLSI",
    "GLUE", "GMAB", "GNLX", "GNPX", "GNTA", "GOSS", "GOVX", "GPCR", "GRCE",
    "GRDX", "GRI", "GTBP", "GUTS", "GYRE",
    # H
    "HALO", "HCWB", "HELP", "HIND", "HOTH", "HOWL", "HRMY", "HRTX", "HUMA",
    "HURA", "HYFT", "HYPD",
    # I
    "IBIO", "IBO", "IBRX", "ICCC", "ICU", "IDYA", "IFRX", "IGC", "IKT",
    "IMA", "IMCR", "IMMP", "IMMX", "IMNM", "IMNN", "IMRN", "IMRX", "IMTX",
    "IMUX", "IMVT", "INAB", "INBX", "INCY", "INDP", "INKT", "INMB", "INO",
    "INSM", "INTS", "INVA", "IOBT", "IONS", "IOVA", "IPHA", "IPSC", "IRD",
    "IRON", "IVA", "IVVD",
    # J
    "JAGX", "JAN", "JANX", "JAZZ", "JBIO", "JSPR", "JUNS",
    # K
    "KALA", "KALV", "KAPA", "KLRS", "KOD", "KPRX", "KPTI", "KROS", "KRRO",
    "KRYS", "KTTA", "KURA", "KYMR", "KYNB", "KYTX", "KZIA", "KZR",
    # L
    "LBRX", "LCTX", "LEGN", "LENZ", "LEXX", "LGND", "LGVN", "LIMN", "LITS",
    "LIXT", "LNAI", "LONA", "LPCN", "LRMR", "LSTA", "LTRN", "LXEO", "LXRX",
    "LYEL",
    # M
    "MAIA", "MANE", "MAZE", "MBIO", "MBRX", "MBX", "MCRB", "MDGL", "MDWD",
    "MDXG", "MENS", "MESO", "MGNX", "MGTX", "MGX", "MIRM", "MIST", "MLEC",
    "MLTX", "MLYS", "MNKD", "MNOV", "MNPR", "MOLN", "MPLT", "MREO", "MRKR",
    "MRNA", "MRVI", "MSLE", "MTNB", "MTVA",
    # N
    "NAGE", "NAMS", "NAUT", "NBP", "NBTX", "NBY", "NCEL", "NCNA", "NERV",
    "NEUP", "NGEN", "NGNE", "NKTR", "NKTX", "NMRA", "NNVC", "NRIX", "NRSN",
    "NRXP", "NRXS", "NTHI", "NTLA", "NTRB", "NUVB", "NUVL", "NVAX", "NVCT",
    "NXTC",
    # O
    "OABI", "OBIO", "OCGN", "OCS", "OCUL", "OGEN", "OKUR", "OKYO", "OLMA",
    "OMER", "ONC", "ONCO", "ONCY", "ORIC", "ORKA", "ORMP", "OSRH", "OSTX",
    "OTLK", "OVID",
    # P
    "PALI", "PASG", "PBM", "PBYI", "PCSA", "PCVX", "PDSB", "PEPG", "PGEN",
    "PHAR", "PHAT", "PHGE", "PHIO", "PHVS", "PLRX", "PLRZ", "PLUR", "PLX",
    "PLYX", "PMCB", "PMN", "PMVP", "PPBT", "PPCB", "PRAX", "PRLD", "PRME",
    "PROK", "PRQR", "PRTA", "PRTC", "PSTV", "PTCT", "PTGX", "PTHS", "PTN",
    "PULM", "PVLA", "PYPD", "PYXS",
    # Q
    "QNCX", "QNRX", "QNTM", "QTTB", "QURE",
    # R
    "RADX", "RANI", "RAPP", "RARE", "RCKT", "RCUS", "REGN", "REPL", "REVB",
    "RGNX", "RIGL", "RLAY", "RLMD", "RLYB", "RNA", "RNAC", "RNAZ", "RNTX",
    "RNXT", "ROIV", "RPRX", "RVMD", "RVPH", "RXRX", "RYTM", "RZLT",
    # S
    "SABS", "SANA", "SCNI", "SEER", "SEPN", "SER", "SGMO", "SGMT", "SGP",
    "SILO", "SION", "SKYE", "SLDB", "SLGL", "SLN", "SLNO", "SLS", "SLXN",
    "SMMT", "SNDX", "SNGX", "SNSE", "SNTI", "SPRB", "SPRC", "SPRO", "SPRY",
    "SRPT", "SRRK", "SRZN", "STOK", "STRO", "STTK", "SVRA", "SXTP", "SYRE",
    # T
    "TARA", "TARS", "TBPH", "TCRT", "TCRX", "TECH", "TECX", "TELO", "TENX",
    "TERN", "TGTX", "TIL", "TKVA", "TLSA", "TLX", "TNGX", "TNXP", "TNYA",
    "TOVX", "TPST", "TRAW", "TRAXV", "TRDA", "TRVI", "TSHA", "TTRX", "TVGN",
    "TVRD", "TVTX", "TYRA",
    # U
    "UNCY", "UPB", "URGN",
    # V
    "VALN", "VANI", "VCEL", "VERA", "VERU", "VIR", "VIVS", "VKTX", "VNDA",
    "VOR", "VRAX", "VRCA", "VRDN", "VRTX", "VSTM", "VTGN", "VTVT", "VYGR",
    "VYNE",
    # W–X
    "WHWK", "WVE", "XBIO", "XBIT", "XCUR", "XENE", "XERS", "XFOR", "XLO",
    "XNCR", "XOMA", "XRTX", "XTLB",
    # Y–Z
    "YDES", "ZBIO", "ZLAB", "ZNTL", "ZURA", "ZVRA", "ZYME",
    # Large-cap biotech (not in FinViz "Biotechnology" industry classification)
    "AMGN", "BIIB", "GILD", "ILMN", "BPMC", "EXAS", "SDGR", "AKRO",
    # Large pharma
    "ABBV", "AZN", "BMY", "GSK", "JNJ", "LLY", "MRK", "NVO", "NVS",
    "PFE", "RHHBY", "SNY", "TAK",
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
    cur.execute("SELECT ticker, last_updated FROM companies")
    existing = {row["ticker"]: row["last_updated"] for row in cur.fetchall()}
    cur.close()

    now = time.time()
    needs_update = any(
        t not in existing or (now - existing[t]) > COMPANY_TTL
        for t in BIOTECH_TICKERS
    )
    if not needs_update:
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
