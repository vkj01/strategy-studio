"""
Supertrend -- ATR-based trend follower, very popular with Indian traders.

Long when price flips above the Supertrend line (trend turns up); exit when it
flips below. Standard recursive band construction on Wilder's ATR.
"""
import numpy as np
import pandas as pd

META = {
    "key": "supertrend",
    "name": "Supertrend",
    "instrument": "equity",
    "description": ("Buy when price flips above the Supertrend line (uptrend); "
                    "sell when it flips below (downtrend). ATR-based."),
    "variables": {
        "universe_size": {"type": "int",   "label": "Number of stocks", "default": 50, "min": 5, "max": 150},
        "atr_period":    {"type": "int",   "label": "ATR period",  "default": 10, "min": 2, "max": 50},
        "multiplier":    {"type": "float", "label": "ATR multiplier", "default": 3.0, "min": 0.5, "max": 10},
        "stop_loss_pct": {"type": "float", "label": "Stop-loss % (0=off)", "default": 0.0, "min": 0, "max": 50},
        "target_pct":    {"type": "float", "label": "Target % (0=off)",    "default": 0.0, "min": 0, "max": 200},
        "max_hold_days": {"type": "int",   "label": "Max hold days (0=off)", "default": 0, "min": 0, "max": 500},
        "trail_stop_pct":{"type": "float", "label": "Trailing stop % (0=off)", "default": 0.0, "min": 0, "max": 50},
        "capital":       {"type": "int",   "label": "Capital (Rs)",       "default": 1000000, "min": 10000, "max": 100000000},
        "max_positions": {"type": "int",   "label": "Max positions (0=all)", "default": 0, "min": 0, "max": 100},
        "cost_pct":      {"type": "float", "label": "Cost per side %",    "default": 0.1, "min": 0, "max": 2},
        "start":         {"type": "date",  "label": "From date", "default": None},
        "end":           {"type": "date",  "label": "To date",   "default": None},
    },
}


def _atr(df, period):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()      # Wilder ATR


def signals(df, params):
    period = int(params.get("atr_period", 10))
    mult = float(params.get("multiplier", 3.0))
    h = df["high"].to_numpy(); l = df["low"].to_numpy(); c = df["close"].to_numpy()
    atr = _atr(df, period).to_numpy()
    n = len(c)
    hl2 = (h + l) / 2.0
    bu = hl2 + mult * atr          # basic upper
    bl = hl2 - mult * atr          # basic lower

    fu = np.full(n, np.nan); fl = np.full(n, np.nan); st = np.full(n, np.nan)
    for i in range(n):
        if i == 0 or np.isnan(fu[i - 1]) or np.isnan(atr[i]):
            fu[i], fl[i], st[i] = bu[i], bl[i], bu[i]           # assume downtrend start
            continue
        fu[i] = bu[i] if (bu[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = bl[i] if (bl[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        if st[i - 1] == fu[i - 1]:                              # was in downtrend
            st[i] = fl[i] if c[i] > fu[i] else fu[i]
        else:                                                  # was in uptrend
            st[i] = fu[i] if c[i] < fl[i] else fl[i]

    up = (st == fl)                                            # uptrend when line = lower band
    prev_up = np.roll(up, 1); prev_up[0] = up[0]
    valid = ~np.isnan(atr)
    entry = valid & up & (~prev_up)                            # flipped to uptrend
    exit_ = valid & (~up) & prev_up                            # flipped to downtrend
    entry[0] = exit_[0] = False
    return entry, exit_
