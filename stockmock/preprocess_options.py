"""
preprocess_options.py -- one-time: parse the NIFTY tick zips into a slim,
fast, in-project DuckDB (data/options.duckdb).

For each trading day we store 1-minute "candle open" prices (first tick of each
minute -- exactly the price-at-HH:MM:00 convention we validated) for:
  - NIFTY spot
  - NIFTY options: strikes within +/- 2500 of the day's ATM, the current weekly
    expiry, both CE and PE.

After this, options_data reads from DuckDB (microsecond lookups) instead of
opening 23 MB zips -- every backtest, including the first, runs in well under a
second. ASCII-only.
"""
import os
import zipfile

import duckdb
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = r"C:\quant_data\options_raw"
OPTDB = os.path.abspath(os.path.join(HERE, "..", "data", "options.duckdb"))
STRIKE_RANGE = 2500          # +/- points around ATM to store

SCHEMA = """
CREATE TABLE IF NOT EXISTS nifty_spot (
    date INTEGER, time VARCHAR, price DOUBLE);
CREATE TABLE IF NOT EXISTS nifty_options (
    date INTEGER, expiry VARCHAR, strike INTEGER, type VARCHAR,
    time VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE);
"""


def _one_min(text):
    """{ 'HH:MM': first_price_str } -- first tick of each minute (candle open)."""
    out = {}
    for line in text.splitlines():
        p = line.split(",")
        if len(p) >= 3:
            hm = p[1][:5]
            if hm not in out:
                out[hm] = p[2]
    return out


def _one_min_ohlc(text):
    """{ 'HH:MM': [open, high, low] } per minute. open = first tick; high/low are
    computed from REAL trades only (qty > 1) so spurious single-tick quote spikes
    (qty=1) don't create false stop-loss triggers -- this matches StockMock."""
    out = {}
    for line in text.splitlines():
        p = line.split(",")
        if len(p) < 4:
            continue
        try:
            px = float(p[2])
            qty = float(p[3])
        except ValueError:
            continue
        hm = p[1][:5]
        r = out.get(hm)
        if r is None:
            out[hm] = [px, None, None]          # open (any tick); high/low pending
            r = out[hm]
        if qty > 1:                             # real trade -> update high/low
            if r[1] is None or px > r[1]:
                r[1] = px
            if r[2] is None or px < r[2]:
                r[2] = px
    for r in out.values():                      # minutes with no real trade -> use open
        if r[1] is None:
            r[1] = r[0]
        if r[2] is None:
            r[2] = r[0]
    return out


def _at(candles, hhmm):
    for hm in sorted(candles):
        if hm >= hhmm:
            return float(candles[hm])
    return None


def _weekly_expiry(names, date):
    d6 = int(str(date)[2:])
    exps = set()
    for n in names:
        if n.startswith("NIFTY") and (n.endswith("CE.csv") or n.endswith("PE.csv")):
            body = n[5:]
            if len(body) >= 6 and body[:6].isdigit():
                exps.add(int(body[:6]))
    for e in sorted(exps):
        if e >= d6:
            return "%06d" % e
    return None


def _days():
    return sorted(int(f[len("NSE_OPT_TICK_"):-4]) for f in os.listdir(RAW)
                  if f.startswith("NSE_OPT_TICK_") and f.endswith(".zip"))


def run():
    con = duckdb.connect(OPTDB)
    con.execute("DROP TABLE IF EXISTS nifty_spot")
    con.execute("DROP TABLE IF EXISTS nifty_options")
    con.execute(SCHEMA)

    for d in _days():
        idx_zip = os.path.join(RAW, "NSE_IDX_TICK_%d.zip" % d)
        opt_zip = os.path.join(RAW, "NSE_OPT_TICK_%d.zip" % d)

        with zipfile.ZipFile(idx_zip) as z:
            spot_c = _one_min(z.read("NIFTY.csv").decode("utf-8", "ignore"))
        spot_df = pd.DataFrame([(d, hm, float(px)) for hm, px in spot_c.items()],
                               columns=["date", "time", "price"])
        con.execute("INSERT INTO nifty_spot SELECT * FROM spot_df")

        spot0 = _at(spot_c, "09:20")
        if spot0 is None:
            print("skip %d (no spot)" % d, flush=True)
            continue
        atm = int(round(spot0 / 50) * 50)

        rows = []
        with zipfile.ZipFile(opt_zip) as z:
            names = set(z.namelist())
            exp = _weekly_expiry(names, d)
            if exp is None:
                print("skip %d (no expiry)" % d, flush=True)
                continue
            for strike in range(atm - STRIKE_RANGE, atm + STRIKE_RANGE + 1, 50):
                for typ in ("CE", "PE"):
                    fn = "NIFTY%s%d%s.csv" % (exp, strike, typ)
                    if fn in names:
                        for hm, ohl in _one_min_ohlc(z.read(fn).decode("utf-8", "ignore")).items():
                            rows.append((d, exp, strike, typ, hm, ohl[0], ohl[1], ohl[2]))
        if rows:
            opt_df = pd.DataFrame(rows, columns=["date", "expiry", "strike", "type",
                                                 "time", "open", "high", "low"])
            con.execute("INSERT INTO nifty_options SELECT * FROM opt_df")
        print("day %d: atm %d exp %s -> %d option rows" % (d, atm, exp, len(rows)), flush=True)

    n_opt = con.execute("SELECT COUNT(*) FROM nifty_options").fetchone()[0]
    n_spot = con.execute("SELECT COUNT(*) FROM nifty_spot").fetchone()[0]
    con.close()
    print("DONE. nifty_options rows: %d | nifty_spot rows: %d | db: %s" % (n_opt, n_spot, OPTDB))


if __name__ == "__main__":
    run()
