"""
Long Strangle -- buy an OTM Call and an OTM Put.

Cheaper than a long straddle; needs an even bigger move to pay off. Legs sit
`strike_offset` points either side of ATM.
"""

META = {
    "key": "long_strangle",
    "name": "Long Strangle",
    "instrument": "options",
    "description": ("Buy an OTM Call and an OTM Put, `strike_offset` points either "
                    "side of ATM. Sell at exit. Profits from a very large move."),
    "variables": {
        "lots":          {"type": "int", "label": "Lots",             "default": 1,      "min": 1,     "max": 50},
        "strike_offset": {"type": "int", "label": "Offset from ATM (pts)", "default": 200, "min": 50,  "max": 2000},
        "lot_size":      {"type": "int", "label": "Lot size (Nifty)", "default": 25,     "min": 1,     "max": 100},
        "entry_time":    {"type": "time", "label": "Entry time",      "default": "09:20"},
        "exit_time":     {"type": "time", "label": "Exit time",       "default": "15:15"},
        "capital":       {"type": "int", "label": "Capital (Rs)",     "default": 100000, "min": 10000, "max": 10000000},
        "start":         {"type": "date", "label": "From date", "default": None},
        "end":           {"type": "date", "label": "To date",   "default": None},
    },
}


def legs(ctx, params):
    lots = int(params.get("lots", 1))
    step = ctx["step"]
    off = int(round(int(params.get("strike_offset", 200)) / step) * step)
    atm = ctx["atm"]
    return [
        {"type": "CE", "action": "buy", "strike": atm + off, "lots": lots},
        {"type": "PE", "action": "buy", "strike": atm - off, "lots": lots},
    ]
