"""
Moving Average Crossover -- the classic "Golden Cross".

Long when the fast MA crosses ABOVE the slow MA; exit when it crosses back
below (with optional stop-loss / target / max-hold overlays handled by the
engine). The most universally recognised technical strategy.

META.variables is the schema the frontend renders as a form and maps straight
to engine params -- edit here, the UI follows.
"""
import numpy as np

META = {
    "key": "ma_crossover",
    "name": "Moving Average Crossover",
    "instrument": "equity",
    "description": ("Buy when the fast moving average crosses above the slow one "
                    "(golden cross); sell when it crosses back below (death cross)."),
    "variables": {
        "universe_size":  {"type": "int",    "label": "Number of stocks",   "default": 50,  "min": 5, "max": 150},
        "fast_ma":        {"type": "int",    "label": "Fast MA period",     "default": 50,  "min": 2, "max": 200},
        "slow_ma":        {"type": "int",    "label": "Slow MA period",     "default": 200, "min": 5, "max": 400},
        "ma_type":        {"type": "select", "label": "MA type",            "default": "SMA", "options": ["SMA", "EMA"]},
        "stop_loss_pct":  {"type": "float",  "label": "Stop-loss % (0=off)", "default": 0.0, "min": 0, "max": 50},
        "target_pct":     {"type": "float",  "label": "Target % (0=off)",    "default": 0.0, "min": 0, "max": 200},
        "max_hold_days":  {"type": "int",    "label": "Max hold days (0=off)", "default": 0, "min": 0, "max": 500},
        "trail_stop_pct": {"type": "float",  "label": "Trailing stop % (0=off)", "default": 0.0, "min": 0, "max": 50},
        "capital":        {"type": "int",    "label": "Capital (Rs)",        "default": 1000000, "min": 10000, "max": 100000000},
        "max_positions":  {"type": "int",    "label": "Max positions (0=all)", "default": 0, "min": 0, "max": 100},
        "cost_pct":       {"type": "float",  "label": "Cost per side %",     "default": 0.1, "min": 0, "max": 2},
        "start":          {"type": "date",   "label": "From date",           "default": None},
        "end":            {"type": "date",   "label": "To date",             "default": None},
    },
}


def signals(df, params):
    """Return (entry_bool, exit_bool) arrays aligned to df, computed at close."""
    close = df["close"]
    fast = int(params.get("fast_ma", 50))
    slow = int(params.get("slow_ma", 200))
    if params.get("ma_type", "SMA") == "EMA":
        f = close.ewm(span=fast, adjust=False).mean().to_numpy()
        s = close.ewm(span=slow, adjust=False).mean().to_numpy()
    else:
        f = close.rolling(fast).mean().to_numpy()
        s = close.rolling(slow).mean().to_numpy()

    pf = np.roll(f, 1); ps = np.roll(s, 1)
    valid = ~(np.isnan(f) | np.isnan(s) | np.isnan(pf) | np.isnan(ps))
    entry = valid & (f > s) & (pf <= ps)     # golden cross
    exit_ = valid & (f < s) & (pf >= ps)     # death cross
    entry[0] = False; exit_[0] = False
    return entry, exit_
