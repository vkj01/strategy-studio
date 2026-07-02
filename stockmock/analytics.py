"""
analytics.py -- rich, StockMock-class analytics from any backtest result.

Takes a result dict ({metrics, performance{equity_curve}, trades}) and derives
the deeper stats StockMock shows: drawdown in value, recovery days,
return/MDD ratio, expectancy, win/loss streaks + distribution, best/worst
trade, monthly returns, and an underwater (drawdown) series.

Instrument-agnostic -- shared by equity and options. ASCII-only.
"""
import numpy as np
import pandas as pd


def _equity_series(curve):
    if not curve:
        return pd.Series(dtype=float)
    df = pd.DataFrame(curve)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["equity"].sort_index()


def _streaks(trades):
    ts = sorted(trades, key=lambda t: t["exit_date"])
    max_win = max_loss = cur = 0
    cur_sign = 0
    win_dist, loss_dist = {}, {}

    def close(sign, length):
        if length <= 0:
            return
        d = win_dist if sign > 0 else loss_dist
        d[length] = d.get(length, 0) + 1

    for t in ts:
        sign = 1 if t["ret_pct"] > 0 else -1
        if sign == cur_sign:
            cur += 1
        else:
            close(cur_sign, cur)
            cur_sign, cur = sign, 1
        if sign > 0:
            max_win = max(max_win, cur)
        else:
            max_loss = max(max_loss, cur)
    close(cur_sign, cur)
    return {"max_win_streak": max_win, "max_loss_streak": max_loss,
            "win_streak_dist": win_dist, "loss_streak_dist": loss_dist}


def _monthly(equity):
    if equity.empty:
        return []
    m = equity.resample("ME").last()
    ret = m.pct_change()
    if len(ret):
        ret.iloc[0] = m.iloc[0] / equity.iloc[0] - 1.0
    return [{"month": d.strftime("%Y-%m"), "ret_pct": round(100 * v, 2)}
            for d, v in ret.items() if pd.notna(v)]


def _drawdown_series(equity):
    if equity.empty:
        return []
    dd = equity / equity.cummax() - 1.0
    return [{"date": d.strftime("%Y-%m-%d"), "dd_pct": round(100 * v, 2)}
            for d, v in dd.items()]


def _recovery(equity):
    if equity.empty:
        return None
    dd = (equity / equity.cummax() - 1.0).to_numpy()
    ti = int(dd.argmin())
    trough_date = equity.index[ti]
    peak_val = equity.iloc[:ti + 1].max()
    after = equity.iloc[ti:]
    rec = after[after >= peak_val]
    if len(rec):
        return {"days": int((rec.index[0] - trough_date).days), "running": False}
    return {"days": int((equity.index[-1] - trough_date).days), "running": True}


def compute(result, capital=100000.0):
    trades = result["trades"]
    perf = result["performance"]
    m = result["metrics"]
    equity = _equity_series(perf["equity_curve"])
    r = np.array([t["ret_pct"] for t in trades]) if trades else np.array([])
    wins = r[r > 0]; losses = r[r <= 0]
    mdd = perf["max_drawdown_pct"]
    cagr = perf["cagr_pct"]

    out = {
        "n": len(trades),
        "wins": int((r > 0).sum()), "losses": int((r <= 0).sum()),
        "best": round(float(r.max()), 2) if len(r) else 0.0,
        "worst": round(float(r.min()), 2) if len(r) else 0.0,
        "avg_trade": round(float(r.mean()), 2) if len(r) else 0.0,
        "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "expectancy": m.get("exp", 0.0),
        "profit_factor": m.get("pf", 0.0),
        "return_mdd_ratio": round(cagr / abs(mdd), 2) if mdd else None,
        "capital": capital,
        "mdd_value": round(capital * mdd / 100.0),
        "final_value": round(capital * (1 + perf["total_return_pct"] / 100.0)),
    }
    out.update(_streaks(trades))
    out["recovery"] = _recovery(equity)
    out["monthly"] = _monthly(equity)
    out["drawdown_series"] = _drawdown_series(equity)
    return out
