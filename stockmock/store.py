"""
store.py -- persist every backtest the user runs, so the AI (and a history
panel) can fetch what's been done.

Static platform/strategy info stays in code (read live from the registry). This
stores only the DYNAMIC stuff: each run's strategy, params, and headline result.
Backed by a small DuckDB (data/runs.duckdb). ASCII-only.
"""
import json
import os
from datetime import datetime

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS_DB = os.path.abspath(os.path.join(HERE, "..", "data", "runs.duckdb"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id BIGINT, ts VARCHAR, instrument VARCHAR,
    strategy_key VARCHAR, strategy_name VARCHAR,
    params VARCHAR, summary VARCHAR, source VARCHAR
);
"""

_CON = None


def _con():
    global _CON
    if _CON is None:
        _CON = duckdb.connect(RUNS_DB)
        _CON.execute(SCHEMA)
    return _CON


def _summary(instrument, result):
    m, p = result["metrics"], result["performance"]
    pf = m["pf"]
    s = {"trades": m["n"], "win_pct": m["win"],
         "profit_factor": (pf if pf != float("inf") else None),
         "max_drawdown_pct": p["max_drawdown_pct"]}
    # base + Rs drawdown so cached comparisons across different-margin structures are fair
    base = p.get("margin_est") or p.get("capital_base")
    if base:
        s["margin_or_capital_rs"] = int(base)
    if p.get("max_drawdown_rs") is not None:
        s["max_drawdown_rs"] = int(p["max_drawdown_rs"])
    elif base and p.get("max_drawdown_pct") is not None:
        s["max_drawdown_rs"] = int(base * p["max_drawdown_pct"] / 100.0)
    if instrument in ("options", "positional", "futures"):    # P&L-based (rupee) instruments
        s["total_pnl"] = round(sum(t["pnl"] for t in result["trades"]))
    else:
        s["total_return_pct"] = p["total_return_pct"]
        s["cagr_pct"] = p["cagr_pct"]
    return s


def _db():
    """The db module if a Postgres DB is configured, else None (DuckDB-file mode --
    only safe for single-user local dev). If a DB URL IS configured but currently
    unreachable, this RAISES instead of silently falling back to the shared local
    file store -- that file store has no per-user scoping at all, so an outage would
    otherwise mix every beta user's conversations/runs together."""
    import db
    if db.ensure():
        return db
    if db.db_available():
        raise RuntimeError("Database is configured but unavailable right now.")
    return None


def log_run(instrument, strategy_key, strategy_name, params, result, source="ui"):
    """Record one backtest. Returns the run_id."""
    clean = {k: (str(v) if not isinstance(v, (int, float, bool, str, type(None))) else v)
             for k, v in params.items()}
    summary = _summary(instrument, result)
    d = _db()
    if d:
        d.log_run(d.current_user(), instrument, strategy_name, clean, summary, source)
        return None
    run_id = int(datetime.now().timestamp() * 1000)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _con().execute(
        "INSERT INTO backtest_runs VALUES (?,?,?,?,?,?,?,?)",
        [run_id, ts, instrument, strategy_key, strategy_name,
         json.dumps(clean), json.dumps(summary), source])
    return run_id


def list_runs(limit=25):
    d = _db()
    if d:
        return d.list_runs(d.current_user(), limit)
    rows = _con().execute(
        "SELECT run_id, ts, instrument, strategy_name, params, summary, source "
        "FROM backtest_runs ORDER BY run_id DESC LIMIT ?", [limit]).fetchall()
    return [{"run_id": r[0], "ts": r[1], "instrument": r[2], "strategy": r[3],
             "params": json.loads(r[4]), "summary": json.loads(r[5]), "source": r[6]}
            for r in rows]


def recent_context(limit=5):
    """Compact text of the user's recent backtests, for the AI's context. Kept SHORT
    (headline metrics + non-default params only) -- this block is re-sent on most
    calls, so trimming it is the main lever on per-question cost."""
    runs = list_runs(limit)
    if not runs:
        return "The user has not run any backtests yet."
    lines = ["The user's recent backtests (newest first):"]
    for r in runs:
        s = r.get("summary") or {}
        pnl = s.get("total_pnl_rs", s.get("net_pnl_rs"))
        metrics = "pnl=%s ret=%s%% win=%s%% dd=%s%%" % (
            pnl, s.get("total_return_pct"), s.get("win_pct"), s.get("max_drawdown_pct"))
        # only the params the user actually set (drop defaults/empties) to save tokens
        p = {k: v for k, v in (r.get("params") or {}).items()
             if v not in (None, 0, 0.0, "", False) and k not in ("legs",)}
        lines.append("- %s [%s] %s | %s" % (r["strategy"], r["instrument"], json.dumps(p), metrics))
    return "\n".join(lines)
