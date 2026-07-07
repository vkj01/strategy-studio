"""
preprocess_futures.py -- one-time: pull the near-month NIFTY future (the
"Continuous Futures/NIFTY-I.csv" series) out of the nested weekly Downloads zips
and store 1-minute candles in the project DuckDB (data/options.duckdb, table
nifty_futures).

We read the futures tick directly from the original archives (the flat
options_raw folder never extracted FUT), and keep ONLY the index near-month
future -- not the 1200+ stock futures -- so this stays tiny and fast. Same
1-minute "candle open + real-trade high/low" convention we validated for options.
ASCII-only.
"""
import io
import os
import zipfile

import duckdb
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OPTDB = os.path.abspath(os.path.join(HERE, "..", "data", "options.duckdb"))
OUTERS = [r"C:\Users\vises\Downloads\Last_3Month.zip",
          r"C:\Users\vises\Downloads\data.zip"]
# near-month continuous futures we care about (index only). NIFTY-I is the primary.
WANT = {"Continuous Futures/NIFTY-I.csv": "NIFTY",
        "Continuous Futures/BANKNIFTY-I.csv": "BANKNIFTY"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS nifty_futures (
    date INTEGER, symbol VARCHAR, time VARCHAR,
    open DOUBLE, high DOUBLE, low DOUBLE);
"""


def _one_min_ohlc(text):
    """{ 'HH:MM': [open, high, low] } -- open = first tick; high/low from REAL
    trades only (qty > 1) so single-tick quote spikes don't cause false stops."""
    out = {}
    for line in text.splitlines():
        p = line.split(",")
        if len(p) < 4:
            continue
        try:
            px = float(p[2]); qty = float(p[3])
        except ValueError:
            continue
        hm = p[1][:5]
        r = out.get(hm)
        if r is None:
            out[hm] = [px, None, None]; r = out[hm]
        if qty > 1:
            if r[1] is None or px > r[1]:
                r[1] = px
            if r[2] is None or px < r[2]:
                r[2] = px
    for r in out.values():
        if r[1] is None:
            r[1] = r[0]
        if r[2] is None:
            r[2] = r[0]
    return out


def run():
    con = duckdb.connect(OPTDB)
    con.execute("DROP TABLE IF EXISTS nifty_futures")
    con.execute(SCHEMA)
    total = 0
    for outer in OUTERS:
        if not os.path.exists(outer):
            print("missing outer zip:", outer, flush=True)
            continue
        with zipfile.ZipFile(outer) as oz:
            weeks = [n for n in oz.namelist() if n.lower().endswith(".zip")]
            for w in weeks:
                with zipfile.ZipFile(io.BytesIO(oz.read(w))) as wz:
                    fut_days = [n for n in wz.namelist()
                                if os.path.basename(n).startswith("NSE_FUT_TICK_")
                                and n.endswith(".zip")]
                    for dn in fut_days:
                        base = os.path.basename(dn)
                        date = int(base[len("NSE_FUT_TICK_"):-4])
                        rows = []
                        with zipfile.ZipFile(io.BytesIO(wz.read(dn))) as fz:
                            names = set(fz.namelist())
                            for path, sym in WANT.items():
                                if path in names:
                                    ohlc = _one_min_ohlc(fz.read(path).decode("utf-8", "ignore"))
                                    for hm, (o, h, l) in ohlc.items():
                                        rows.append((date, sym, hm, o, h, l))
                        if rows:
                            df = pd.DataFrame(rows, columns=["date", "symbol", "time",
                                                             "open", "high", "low"])
                            con.execute("INSERT INTO nifty_futures SELECT * FROM df")
                            total += len(rows)
                        print("day %d -> %d futures rows" % (date, len(rows)), flush=True)
    n = con.execute("SELECT COUNT(*) FROM nifty_futures").fetchone()[0]
    days = con.execute("SELECT COUNT(DISTINCT date) FROM nifty_futures").fetchone()[0]
    syms = con.execute("SELECT DISTINCT symbol FROM nifty_futures").fetchall()
    con.close()
    print("DONE. nifty_futures rows: %d over %d days, symbols %s" % (n, days, syms))


if __name__ == "__main__":
    run()
