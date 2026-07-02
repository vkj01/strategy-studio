"""
options_data.py -- serve NIFTY spot + option prices to the options engine.

Primary source: a slim in-project DuckDB (data/options.duckdb) of 1-minute
"candle open" prices, built once by preprocess_options.py -- microsecond
lookups, no zips to open. If that DB isn't present it falls back to reading the
raw NSE F&O tick zips directly (slower, but self-contained).

Convention (validated vs StockMock, exact): the price at HH:MM is the first tick
of that minute -- i.e. the price at HH:MM:00. ASCII-only.
"""
import functools
import os
import zipfile

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_LOCAL = r"C:\quant_data\options_raw"
RAW = _LOCAL if os.path.isdir(_LOCAL) else os.path.abspath(os.path.join(HERE, "..", "data", "options_raw"))
OPTDB = os.path.abspath(os.path.join(HERE, "..", "data", "options.duckdb"))


# --- fast path: DuckDB -------------------------------------------------------
_DUCK = None
_USE_DB = None


def _duck():
    global _DUCK
    if _DUCK is None:
        import duckdb
        _DUCK = duckdb.connect(OPTDB, read_only=True)
    return _DUCK


def _db_ready():
    global _USE_DB
    if _USE_DB is None:
        try:
            _USE_DB = _duck().execute("SELECT COUNT(*) FROM nifty_options").fetchone()[0] > 0
        except Exception:
            _USE_DB = False
    return _USE_DB


@functools.lru_cache(maxsize=30000)
def _series_db(date, expiry, strike, typ):
    return _duck().execute(
        "SELECT time, open, high, low FROM nifty_options "
        "WHERE date=? AND expiry=? AND strike=? AND type=? ORDER BY time",
        [int(date), str(expiry), int(strike), typ]).fetchall()


@functools.lru_cache(maxsize=200)
def _spot_series_db(date):
    return _duck().execute(
        "SELECT time, price FROM nifty_spot WHERE date=? ORDER BY time",
        [int(date)]).fetchall()


def _from_rows(rows, hhmm):
    """rows sorted by time; price = col 1 (open). First candle at/after hhmm."""
    if not rows:
        return None
    for r in rows:
        if r[0] >= hhmm:
            return float(r[1])
    return float(rows[-1][1])


# --- fallback path: raw zips -------------------------------------------------
def _opt_zip(date):
    return os.path.join(RAW, "NSE_OPT_TICK_%s.zip" % date)


def _idx_zip(date):
    return os.path.join(RAW, "NSE_IDX_TICK_%s.zip" % date)


_ZIP_CACHE = {}


def _zip(zippath):
    z = _ZIP_CACHE.get(zippath)
    if z is None:
        z = zipfile.ZipFile(zippath)
        _ZIP_CACHE[zippath] = z
    return z


@functools.lru_cache(maxsize=2048)
def _read_csv(zippath, csvname):
    try:
        with _zip(zippath).open(csvname) as f:
            return pd.read_csv(f, header=None,
                               names=["date", "time", "price", "qty", "oi"],
                               dtype={"time": str})
    except (KeyError, FileNotFoundError):
        return None


def _price_at_zip(df, hhmm):
    if df is None or df.empty:
        return None
    target = hhmm + ":00"
    m = df["time"].to_numpy() >= target
    if m.any():
        return float(df["price"].to_numpy()[m][0])
    return float(df["price"].iloc[-1])


# --- public API (routes to DB, else zips) ------------------------------------
def spot_at(date, hhmm):
    if _db_ready():
        return _from_rows(_spot_series_db(int(date)), hhmm)
    return _price_at_zip(_read_csv(_idx_zip(date), "NIFTY.csv"), hhmm)


def spot_series(date):
    """[(time, price)] 1-min NIFTY spot for the day (for range-breakout entry)."""
    if _db_ready():
        return [(t, float(p)) for (t, p) in _spot_series_db(int(date))]
    df = _read_csv(_idx_zip(date), "NIFTY.csv")
    if df is None or df.empty:
        return []
    df = df.copy()
    df["hm"] = df["time"].str[:5]
    o = df.groupby("hm")["price"].first()
    return [(hm, float(o[hm])) for hm in o.index]


def option_price_at(date, expiry, strike, opt_type, hhmm):
    if _db_ready():
        return _from_rows(_series_db(int(date), str(expiry), int(strike), opt_type), hhmm)
    csv = "NIFTY%s%d%s.csv" % (expiry, int(strike), opt_type)
    return _price_at_zip(_read_csv(_opt_zip(date), csv), hhmm)


def option_series(date, expiry, strike, opt_type):
    """[(time, open, high, low)] 1-min candles for one contract (for stop-loss)."""
    if _db_ready():
        return _series_db(int(date), str(expiry), int(strike), opt_type)
    df = _read_csv(_opt_zip(date), "NIFTY%s%d%s.csv" % (expiry, int(strike), opt_type))
    if df is None or df.empty:
        return []
    df = df.copy()
    df["hm"] = df["time"].str[:5]
    g = df.groupby("hm")["price"]
    o, h, l = g.first(), g.max(), g.min()
    return [(hm, float(o[hm]), float(h[hm]), float(l[hm])) for hm in o.index]


def weekly_expiry(date):
    """Current-week expiry for a date (as stored, e.g. '260609')."""
    if _db_ready():
        r = _duck().execute("SELECT expiry FROM nifty_options WHERE date=? LIMIT 1",
                            [int(date)]).fetchone()
        return r[0] if r else None
    d6 = int(str(date)[2:])
    for e in _zip_expiries(date):
        if e >= d6:
            return "%06d" % e
    return None


@functools.lru_cache(maxsize=64)
def _zip_expiries(date):
    exps = set()
    try:
        with zipfile.ZipFile(_opt_zip(date)) as z:
            for n in z.namelist():
                if n.startswith("NIFTY") and (n.endswith("CE.csv") or n.endswith("PE.csv")):
                    body = n[5:]
                    if len(body) >= 6 and body[:6].isdigit():
                        exps.add(int(body[:6]))
    except FileNotFoundError:
        pass
    return sorted(exps)


def atm_strike(spot, step=50):
    return int(round(spot / step) * step)


def available_days():
    if _db_ready():
        return [int(r[0]) for r in _duck().execute(
            "SELECT DISTINCT date FROM nifty_options ORDER BY date").fetchall()]
    days = []
    for f in os.listdir(RAW) if os.path.isdir(RAW) else []:
        if f.startswith("NSE_OPT_TICK_") and f.endswith(".zip"):
            days.append(int(f[len("NSE_OPT_TICK_"):-4]))
    return sorted(days)
