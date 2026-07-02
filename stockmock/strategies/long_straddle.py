"""
Long Straddle -- buy the ATM Call and ATM Put.

The opposite of a short straddle: pays premium up front, profits from a BIG move
in either direction (volatility long). Loses on quiet days.
"""

META = {
    "key": "long_straddle",
    "name": "Long Straddle",
    "instrument": "options",
    "description": ("Buy the ATM Call and ATM Put at entry, sell both at exit. "
                    "Profits from a large move either way. Intraday, weekly expiry."),
    "variables": {
        "lots":       {"type": "int",  "label": "Lots",            "default": 1,      "min": 1,     "max": 50},
        "lot_size":   {"type": "int",  "label": "Lot size (Nifty)", "default": 25,    "min": 1,     "max": 100},
        "entry_time": {"type": "time", "label": "Entry time",       "default": "09:20"},
        "exit_time":  {"type": "time", "label": "Exit time",        "default": "15:15"},
        "capital":    {"type": "int",  "label": "Capital (Rs)",     "default": 100000, "min": 10000, "max": 10000000},
        "start":      {"type": "date", "label": "From date", "default": None},
        "end":        {"type": "date", "label": "To date",   "default": None},
    },
}


def legs(ctx, params):
    lots = int(params.get("lots", 1))
    atm = ctx["atm"]
    return [
        {"type": "CE", "action": "buy", "strike": atm, "lots": lots},
        {"type": "PE", "action": "buy", "strike": atm, "lots": lots},
    ]
