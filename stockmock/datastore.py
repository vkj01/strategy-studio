"""
datastore.py -- the local data layer (DuckDB).

All market data lives inside the project as a single local DuckDB file
(data/market.duckdb) -- no server, no credentials, no network. DuckDB gives us
fast SQL over the data now, and scales cleanly to the options chain later
("all Nifty 18000 CE for this expiry" is one query). A small in-memory cache
keeps repeated reads instant.

One-time setup (loads the consolidated CSVs into DuckDB):
    python -c "import datastore as d; print(d.load_equity_daily()); print(d.status())"

ASCII-only.
"""
import csv
import os

import duckdb
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
# data lives one level up, at the AI Backtester root (shared across projects)
DATA_DIR = os.path.abspath(os.path.join(HERE, "..", "data"))
DAILY_DIR = os.path.join(DATA_DIR, "equity")
UNIVERSE_CSV = os.path.join(DATA_DIR, "quality_universe.csv")
DB_FILE = os.path.join(DATA_DIR, "market.duckdb")


def connect(read_only=False):
    return duckdb.connect(DB_FILE, read_only=read_only)


SCHEMA = """
CREATE TABLE IF NOT EXISTS equity_daily (
    symbol VARCHAR NOT NULL,
    dt     DATE    NOT NULL,
    open   DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
    volume BIGINT,
    PRIMARY KEY (symbol, dt)
);
"""


def init_schema():
    con = connect()
    try:
        con.execute(SCHEMA)
    finally:
        con.close()
    return "schema ready"


def top_universe(n=150):
    out = []
    with open(UNIVERSE_CSV, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("in_top150") == "Y":
                out.append(r["symbol"])
    return out[:n]


def load_equity_daily(start="2019-01-01", replace=True):
    """Bulk-load every equity CSV in data/equity into DuckDB in one query.
    The symbol comes from the filename. Returns total rows loaded."""
    glob = os.path.join(DAILY_DIR, "*.csv").replace("\\", "/")
    con = connect()
    try:
        con.execute(SCHEMA)
        if replace:
            con.execute("DELETE FROM equity_daily")
        con.execute(
            "INSERT INTO equity_daily "
            "SELECT parse_filename(filename, true) AS symbol, "
            "       \"Date\"::DATE, \"Open\", \"High\", \"Low\", \"Close\", "
            "       CAST(\"Volume\" AS BIGINT) "
            "FROM read_csv_auto('%s', filename=true) "
            "WHERE \"Date\"::DATE >= ?::DATE" % glob, [start])
        n = con.execute("SELECT COUNT(*) FROM equity_daily").fetchone()[0]
    finally:
        con.close()
    return n


# --- reads (with a small cache) ----------------------------------------------
_CACHE = {}


def list_symbols():
    con = connect(read_only=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT symbol FROM equity_daily ORDER BY symbol").fetchall()]
    finally:
        con.close()


def get_daily(symbol, start=None, end=None):
    """Daily OHLCV DataFrame (indexed by date) for one symbol."""
    key = (symbol, start, end)
    if key in _CACHE:
        return _CACHE[key]
    q = "SELECT dt, open, high, low, close, volume FROM equity_daily WHERE symbol = ?"
    params = [symbol]
    if start:
        q += " AND dt >= ?::DATE"; params.append(start)
    if end:
        q += " AND dt <= ?::DATE"; params.append(end)
    q += " ORDER BY dt"
    con = connect(read_only=True)
    try:
        df = con.execute(q, params).df()
    finally:
        con.close()
    df["dt"] = pd.to_datetime(df["dt"])
    df = df.set_index("dt")
    _CACHE[key] = df
    return df


def status():
    con = connect(read_only=True)
    try:
        row = con.execute(
            "SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(dt), MAX(dt) FROM equity_daily"
        ).fetchone()
    finally:
        con.close()
    return {"rows": row[0], "symbols": row[1], "from": str(row[2]), "to": str(row[3])}
