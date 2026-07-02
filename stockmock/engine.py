"""
engine.py -- the StockMock-style equity backtest engine (daily bars).

Clean, correct, causal (no lookahead), and fast:
- A strategy supplies entry/exit SIGNALS at each day's close.
- The engine executes them next-day-open, applies optional risk overlays
  (stop %, target %, max-hold) and realistic costs.
- Performance uses a proper DAILY equal-weight portfolio: on each day, capital
  is split equally across the stocks currently held, and daily returns are
  compounded. This is the standard, realistic model -- it does NOT explode the
  way naive trade-by-trade compounding does.

Signals are vectorised; the per-symbol walk is a tight numpy loop. ASCII-only.
"""
import numpy as np
import pandas as pd

import datastore
from strategies import registry


# --- one symbol: signals -> trades + a daily strategy-return series -----------
def backtest_symbol(df, entry, exit_, sl_pct=0.0, target_pct=0.0, max_hold=0, cost=0.001, trail_pct=0.0):
    """Returns (trades, daily) where `daily` is a per-day return contribution
    (NaN when flat). `cost` is charged PER SIDE (entry + exit = round-trip).
    `trail_pct` is a trailing stop: exit if price falls trail_pct below the
    highest high since entry."""
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float);  c = df["close"].to_numpy(float)
    dates = df.index
    n = len(df)

    enter_today = np.zeros(n, bool); enter_today[1:] = entry[:-1]   # act next open
    exit_today = np.zeros(n, bool);  exit_today[1:] = exit_[:-1]

    trades = []
    contrib = np.full(n, np.nan)          # daily return while held
    in_pos = False
    entry_price = 0.0; entry_date = None; prev_mark = 0.0; held = 0; peak = 0.0

    for t in range(n):
        just_entered = False
        if not in_pos and enter_today[t]:
            in_pos = True
            entry_price = o[t]; entry_date = dates[t]; prev_mark = o[t]; held = 0
            peak = h[t]; just_entered = True

        if in_pos:
            held += 1
            peak = max(peak, h[t])
            ec = cost if just_entered else 0.0          # entry-side cost (once, on entry day)
            # merge fixed stop + trailing stop -> the higher level triggers first on the way down
            stops = []
            if sl_pct > 0:
                stops.append(entry_price * (1 - sl_pct))
            if trail_pct > 0:
                stops.append(peak * (1 - trail_pct))
            best_stop = max(stops) if stops else None

            xp = None; reason = None
            if exit_today[t]:
                xp, reason = o[t], "signal"
            elif best_stop is not None and l[t] <= best_stop:
                xp = best_stop
                reason = "trail" if (trail_pct > 0 and best_stop == peak * (1 - trail_pct)) else "stop"
            elif target_pct > 0 and h[t] >= entry_price * (1 + target_pct):
                xp, reason = entry_price * (1 + target_pct), "target"
            elif max_hold > 0 and held >= max_hold:
                xp, reason = c[t], "time"

            if xp is not None:                          # exit today (charge exit + any entry cost)
                contrib[t] = xp / prev_mark - 1.0 - cost - ec
                ret = (xp / entry_price - 1.0) - 2.0 * cost
                trades.append({"entry_date": entry_date, "exit_date": dates[t],
                               "entry": round(entry_price, 2), "exit": round(xp, 2),
                               "ret": ret, "outcome": reason, "bars": held})
                in_pos = False
            else:                                       # still held -> mark to close
                contrib[t] = c[t] / prev_mark - 1.0 - ec
                prev_mark = c[t]

    return trades, pd.Series(contrib, index=dates)


# --- performance from a daily portfolio-return series -------------------------
def _perf_from_daily(port_daily, start_capital=100.0):
    port_daily = port_daily.dropna().sort_index()
    if port_daily.empty:
        return {"equity_curve": [], "final_equity": start_capital, "capital_base": start_capital,
                "total_return_pct": 0.0, "max_drawdown_pct": 0.0, "cagr_pct": 0.0}
    equity = (1.0 + port_daily).cumprod() * start_capital
    peak = equity.cummax()
    max_dd = (equity / peak - 1.0).min()
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    cagr = (equity.iloc[-1] / start_capital) ** (1 / years) - 1
    curve = [{"date": d.strftime("%Y-%m-%d"), "equity": round(v, 3)}
             for d, v in equity.items()]
    return {"equity_curve": curve, "final_equity": round(equity.iloc[-1], 3),
            "capital_base": round(start_capital, 0),
            "total_return_pct": round(100 * (equity.iloc[-1] / start_capital - 1), 2),
            "max_drawdown_pct": round(100 * max_dd, 2),
            "cagr_pct": round(100 * cagr, 2)}


def metrics(trades):
    if not trades:
        return {"n": 0, "win": 0.0, "avgw": 0.0, "avgl": 0.0, "pf": 0.0, "exp": 0.0, "avg_bars": 0.0}
    r = np.array([t["ret"] for t in trades])
    wins = r[r > 0]; losses = r[r <= 0]
    pf = (wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf")
    return {"n": len(trades), "win": round(100 * (r > 0).mean(), 1),
            "avgw": round(100 * wins.mean(), 2) if len(wins) else 0.0,
            "avgl": round(100 * losses.mean(), 2) if len(losses) else 0.0,
            "pf": round(pf, 2) if pf != float("inf") else float("inf"),
            "exp": round(100 * r.mean(), 2),
            "avg_bars": round(np.mean([t["bars"] for t in trades]), 1)}


# --- high-level entry point ---------------------------------------------------
def summarize(strategy_key, params):
    """Run a REGISTERED strategy by key -> {metrics, performance, trades}."""
    strat = registry.get(strategy_key)
    return summarize_with_signals(strat["signals"], strat["meta"]["name"], params)


def summarize_with_signals(signals_fn, name, params):
    """Run ANY signals(df, params)->(entry, exit) function through the portfolio
    engine. Used by registered strategies AND by AI-generated ones (sandboxed)."""
    slow = int(params.get("slow_ma", 200))
    sl = float(params.get("stop_loss_pct", 0) or 0) / 100.0
    tgt = float(params.get("target_pct", 0) or 0) / 100.0
    mh = int(params.get("max_hold_days", 0) or 0)
    trail = float(params.get("trail_stop_pct", 0) or 0) / 100.0
    cost = float(params.get("cost_pct", 0.1)) / 100.0     # per side
    capital = float(params.get("capital", 1000000) or 1000000)
    max_pos = int(params.get("max_positions", 0) or 0)    # 0 = unlimited (equal-weight among all held)
    s_ts = pd.Timestamp(params["start"]) if params.get("start") else None
    e_ts = pd.Timestamp(params["end"]) if params.get("end") else None

    trades_all = []
    daily = {}
    order = []                                            # universe rank order (for slot priority)
    for sym in datastore.top_universe(int(params.get("universe_size", 50))):
        df = datastore.get_daily(sym)                  # full history -> MA warm-up
        if len(df) < slow + 5:
            continue
        entry, exit_ = signals_fn(df, params)
        trs, contrib = backtest_symbol(df, entry, exit_, sl, tgt, mh, cost, trail)
        for t in trs:
            t["symbol"] = sym
        trades_all.extend(trs)
        daily[sym] = contrib
        order.append(sym)

    # window the daily contributions
    mat = pd.DataFrame(daily)
    if s_ts is not None:
        mat = mat[mat.index >= s_ts]
    if e_ts is not None:
        mat = mat[mat.index <= e_ts]

    taken = None
    if mat.empty:
        port_daily = pd.Series(dtype=float)
    elif max_pos <= 0:
        # unlimited: equal-weight among all held names each day (validated default)
        port_daily = mat.mean(axis=1, skipna=True)
    else:
        # fixed N slots: capital/N per slot, idle slots earn cash (0). On an entry day,
        # fill free slots in universe-rank order; extra signals are skipped (not taken).
        cols = [s for s in order if s in mat.columns]
        held = mat.notna()
        entry_mask = held & ~held.shift(1, fill_value=False)
        active, taken, port = set(), set(), []
        for d in mat.index:
            row = mat.loc[d]
            active = {s for s in active if pd.notna(row[s])}          # drop closed
            free = max_pos - len(active)
            if free > 0:
                for s in cols:
                    if free <= 0:
                        break
                    if entry_mask.loc[d, s] and s not in active:
                        active.add(s); taken.add((s, d)); free -= 1
            port.append(sum(row[s] for s in active) / max_pos if active else 0.0)
        port_daily = pd.Series(port, index=mat.index)
    perf = _perf_from_daily(port_daily, start_capital=capital)

    # trade log = entries inside the window (and actually TAKEN, when slots are capped)
    tw = [t for t in trades_all
          if (s_ts is None or t["entry_date"] >= s_ts)
          and (e_ts is None or t["entry_date"] <= e_ts)
          and (taken is None or (t["symbol"], t["entry_date"]) in taken)]
    out_trades = [{"symbol": t["symbol"],
                   "entry_date": t["entry_date"].strftime("%Y-%m-%d"),
                   "exit_date": t["exit_date"].strftime("%Y-%m-%d"),
                   "entry": t["entry"], "exit": t["exit"],
                   "ret_pct": round(100 * t["ret"], 2), "outcome": t["outcome"]}
                  for t in tw]
    return {"strategy": name, "metrics": metrics(tw),
            "performance": perf, "trades": out_trades}
