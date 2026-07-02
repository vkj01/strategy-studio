"""
MACD Crossover -- the classic momentum strategy.

Buy when the MACD line crosses above its signal line; exit when it crosses back
below. MACD = EMA(fast) - EMA(slow); signal = EMA(MACD, signal_period).
"""
import numpy as np

META = {
    "key": "macd_crossover",
    "name": "MACD Crossover",
    "instrument": "equity",
    "description": ("Buy when the MACD line crosses above its signal line "
                    "(momentum turning up); sell when it crosses back below."),
    "variables": {
        "universe_size": {"type": "int",   "label": "Number of stocks", "default": 50, "min": 5, "max": 150},
        "macd_fast":     {"type": "int",   "label": "Fast EMA",   "default": 12, "min": 2, "max": 100},
        "macd_slow":     {"type": "int",   "label": "Slow EMA",   "default": 26, "min": 5, "max": 200},
        "macd_signal":   {"type": "int",   "label": "Signal EMA", "default": 9,  "min": 2, "max": 50},
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


def signals(df, params):
    fast = int(params.get("macd_fast", 12))
    slow = int(params.get("macd_slow", 26))
    sig = int(params.get("macd_signal", 9))
    c = df["close"]
    macd = c.ewm(span=fast, adjust=False).mean() - c.ewm(span=slow, adjust=False).mean()
    signal = macd.ewm(span=sig, adjust=False).mean()
    m = macd.to_numpy(); s = signal.to_numpy()
    pm = np.roll(m, 1); ps = np.roll(s, 1)
    valid = ~(np.isnan(m) | np.isnan(s) | np.isnan(pm) | np.isnan(ps))
    entry = valid & (m > s) & (pm <= ps)
    exit_ = valid & (m < s) & (pm >= ps)
    entry[0] = exit_[0] = False
    return entry, exit_
