"""
Short ATM% Strangle -- strikes chosen by PERCENT from spot (ATM Percent mode).

StockMock's "Short ATM +/- 1%". Sell a Call `atm_pct`% above spot and a Put the
same % below. Self-scales with the index level (unlike fixed points).
"""

META = {
    "key": "short_atm_pct",
    "name": "Short ATM% Strangle",
    "instrument": "options",
    "description": ("Sell a Call atm_pct%% above spot and a Put the same %% below. "
                    "Strike distance scales with the index level (ATM Percent mode)."),
    "variables": {
        "lots":     {"type": "int",   "label": "Lots",              "default": 1,      "min": 1,     "max": 50},
        "atm_pct":  {"type": "float", "label": "% from ATM",        "default": 1.0,    "min": 0.1,   "max": 10},
        "lot_size": {"type": "int",   "label": "Lot size (Nifty)",  "default": 25,     "min": 1,     "max": 100},
        "entry_time": {"type": "time", "label": "Entry time",       "default": "09:20"},
        "exit_time":  {"type": "time", "label": "Exit time",        "default": "15:15"},
        "capital":  {"type": "int",   "label": "Capital (Rs)",      "default": 100000, "min": 10000, "max": 10000000},
        "start":    {"type": "date",  "label": "From date", "default": None},
        "end":      {"type": "date",  "label": "To date",   "default": None},
    },
}


def legs(ctx, params):
    lots = int(params.get("lots", 1))
    pct = float(params.get("atm_pct", 1.0)) / 100.0
    step = ctx["step"]
    spot = ctx["spot"]
    ce = int(round(spot * (1 + pct) / step) * step)
    pe = int(round(spot * (1 - pct) / step) * step)
    return [
        {"type": "CE", "action": "sell", "strike": ce, "lots": lots},
        {"type": "PE", "action": "sell", "strike": pe, "lots": lots},
    ]
