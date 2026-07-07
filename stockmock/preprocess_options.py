"""
preprocess_options.py -- one-time: parse the NSE index-option tick zips into a
slim, fast, in-project DuckDB (data/options.duckdb).

Multi-index + weekly/monthly. For each trading day and each supported index we
store 1-minute "candle open + real-trade high/low" prices for:
  - the index spot
  - options within +/- range of that day's ATM, for BOTH the near WEEKLY expiry
    (if the index has weeklies) and the near MONTHLY expiry (the month-end one),
    call and put.

Tables (symbol-aware, replacing the old nifty_* ones):
  spot_1m(symbol, date, time, price)
  options_1m(symbol, date, expiry, strike, type, time, open, high, low)

NIFTY's config (step 50, range 2500, weekly) is unchanged, so its weekly rows are
byte-identical to the validated dataset; BANKNIFTY (monthly-only) and MIDCPNIFTY
plus the monthly-expiry rows are new. ASCII-only.
"""
import os
import zipfile

import duckdb
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = r"C:\quant_data\options_raw"
OPTDB = os.path.abspath(os.path.join(HERE, "..", "data", "options.duckdb"))

# per-index: spot csv in the IDX zip, strike step, +/- points around ATM, weeklies?
INDICES = {
    "NIFTY":      {"spot": "NIFTY.csv",      "step": 50,  "range": 2500, "weekly": True},
    "BANKNIFTY":  {"spot": "BANKNIFTY.csv",  "step": 100, "range": 5000, "weekly": False},
    "MIDCPNIFTY": {"spot": "MIDCPNIFTY.csv", "step": 25,  "range": 1500, "weekly": True},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS spot_1m (
    symbol VARCHAR, date INTEGER, time VARCHAR, price DOUBLE);
CREATE TABLE IF NOT EXISTS options_1m (
    symbol VARCHAR, date INTEGER, expiry VARCHAR, strike INTEGER, type VARCHAR,
    time VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE);
"""


def _one_min(text):
    out = {}
    for line in text.splitlines():
        p = line.split(",")
        if len(p) >= 3 and p[1][:5] not in out:
            out[p[1][:5]] = p[2]
    return out


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


def _at(candles, hhmm):
    for hm in sorted(candles):
        if hm >= hhmm:
            return float(candles[hm])
    return None


def _expiries_for(names, symbol):
    """All expiries (yymmdd ints) present for `symbol` in this OPT zip."""
    exps = set()
    for n in names:
        if n.startswith(symbol) and (n.endswith("CE.csv") or n.endswith("PE.csv")):
            body = n[len(symbol):]
            # guard against NIFTY vs NIFTYNXT etc: body must start with 6 digits
            if len(body) >= 6 and body[:6].isdigit():
                # and the char right after symbol must be a digit (not a letter -> different underlying)
                exps.add(int(body[:6]))
    return sorted(exps)


def _pick_expiries(exps, d6, has_weekly):
    """Return the (weekly, monthly) expiries to store for a day. weekly = nearest
    upcoming; monthly = nearest month-end upcoming. De-duplicated by the caller."""
    upcoming = [e for e in exps if e >= d6]
    if not upcoming:
        return []
    month_end = {}                                  # yymm -> max expiry that month
    for e in exps:
        ym = e // 100                               # yymmdd -> yymm
        month_end[ym] = max(month_end.get(ym, 0), e)
    monthly = min((e for e in upcoming if e == month_end.get(e // 100)), default=None)
    picks = []
    if has_weekly:
        picks.append(upcoming[0])                   # nearest expiry (weekly)
    if monthly is not None:
        picks.append(monthly)
    return sorted(set(picks))


def _days():
    return sorted(int(f[len("NSE_OPT_TICK_"):-4]) for f in os.listdir(RAW)
                  if f.startswith("NSE_OPT_TICK_") and f.endswith(".zip"))


def run():
    con = duckdb.connect(OPTDB)
    con.execute("DROP TABLE IF EXISTS spot_1m")
    con.execute("DROP TABLE IF EXISTS options_1m")
    con.execute(SCHEMA)

    for d in _days():
        idx_zip = os.path.join(RAW, "NSE_IDX_TICK_%d.zip" % d)
        opt_zip = os.path.join(RAW, "NSE_OPT_TICK_%d.zip" % d)
        if not (os.path.exists(idx_zip) and os.path.exists(opt_zip)):
            continue
        with zipfile.ZipFile(idx_zip) as iz, zipfile.ZipFile(opt_zip) as oz:
            idx_names = set(iz.namelist())
            opt_names = set(oz.namelist())
            day_opt_rows = 0
            for sym, cfg in INDICES.items():
                if cfg["spot"] not in idx_names:
                    continue
                spot_c = _one_min(iz.read(cfg["spot"]).decode("utf-8", "ignore"))
                spot_df = pd.DataFrame([(sym, d, hm, float(px)) for hm, px in spot_c.items()],
                                       columns=["symbol", "date", "time", "price"])
                con.execute("INSERT INTO spot_1m SELECT * FROM spot_df")

                spot0 = _at(spot_c, "09:20")
                if spot0 is None:
                    continue
                step = cfg["step"]
                atm = int(round(spot0 / step) * step)
                exps = _expiries_for(opt_names, sym)
                picks = _pick_expiries(exps, int(str(d)[2:]), cfg["weekly"])
                rows = []
                for exp in picks:
                    es = "%06d" % exp
                    for strike in range(atm - cfg["range"], atm + cfg["range"] + 1, step):
                        for typ in ("CE", "PE"):
                            fn = "%s%s%d%s.csv" % (sym, es, strike, typ)
                            if fn in opt_names:
                                for hm, ohl in _one_min_ohlc(oz.read(fn).decode("utf-8", "ignore")).items():
                                    rows.append((sym, d, es, strike, typ, hm, ohl[0], ohl[1], ohl[2]))
                if rows:
                    odf = pd.DataFrame(rows, columns=["symbol", "date", "expiry", "strike",
                                                      "type", "time", "open", "high", "low"])
                    con.execute("INSERT INTO options_1m SELECT * FROM odf")
                    day_opt_rows += len(rows)
        print("day %d -> %d option rows" % (d, day_opt_rows), flush=True)

    n_opt = con.execute("SELECT COUNT(*) FROM options_1m").fetchone()[0]
    syms = con.execute("SELECT symbol, COUNT(*) FROM options_1m GROUP BY symbol").fetchall()
    con.close()
    print("DONE. options_1m rows: %d | by symbol: %s | db: %s" % (n_opt, syms, OPTDB))


if __name__ == "__main__":
    run()
