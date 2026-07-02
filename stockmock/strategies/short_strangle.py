"""
Short Strangle -- sell an OTM Call and an OTM Put (wider than a straddle).

Lower premium than a straddle but a wider break-even -- profits if the index
stays inside the two strikes. Legs sit `strike_offset` points either side of ATM.
"""

META = {
    "key": "short_strangle",
    "name": "Short Strangle",
    "instrument": "options",
    "description": ("Sell an OTM Call and an OTM Put, `strike_offset` points either "
                    "side of ATM. Buy back at exit. Intraday, weekly expiry."),
    "variables": {
        "lots":         {"type": "int",  "label": "Lots",             "default": 1,      "min": 1,     "max": 50},
        "strike_offset": {"type": "int", "label": "Offset from ATM (pts)", "default": 200, "min": 50,  "max": 2000},
        "lot_size":     {"type": "int",  "label": "Lot size (Nifty)", "default": 25,     "min": 1,     "max": 100},
        "entry_time":   {"type": "time", "label": "Entry time",       "default": "09:20"},
        "exit_time":    {"type": "time", "label": "Exit time",        "default": "15:15"},
        "capital":      {"type": "int",  "label": "Capital (Rs)",     "default": 100000, "min": 10000, "max": 10000000},
        "start":        {"type": "date", "label": "From date", "default": None},
        "end":          {"type": "date", "label": "To date",   "default": None},
    },
}


def legs(ctx, params):
    lots = int(params.get("lots", 1))
    step = ctx["step"]
    off = int(round(int(params.get("strike_offset", 200)) / step) * step)
    atm = ctx["atm"]
    return [
        {"type": "CE", "action": "sell", "strike": atm + off, "lots": lots},
        {"type": "PE", "action": "sell", "strike": atm - off, "lots": lots},
    ]
