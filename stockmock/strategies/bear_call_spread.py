"""
Bear Call Spread -- bearish, defined-risk credit spread on the call side.

Sell the nearer Call and buy a farther Call as protection. Collects a net credit;
profits if the index stays flat or falls. StockMock default straddles the ATM:
sell CE at ATM-offset, buy CE at ATM+offset (a 2*offset-wide spread).
"""

META = {
    "key": "bear_call_spread",
    "name": "Bear Call Spread",
    "instrument": "options",
    "description": ("Sell CE at ATM-offset, buy CE at ATM+offset. Bearish/neutral "
                    "credit spread with capped risk and reward."),
    "variables": {
        "lots":       {"type": "int",  "label": "Lots",             "default": 1,      "min": 1,     "max": 50},
        "offset":     {"type": "int",  "label": "Offset from ATM (pts)", "default": 50, "min": 50,   "max": 1000},
        "lot_size":   {"type": "int",  "label": "Lot size (Nifty)",  "default": 25,     "min": 1,     "max": 100},
        "entry_time": {"type": "time", "label": "Entry time",        "default": "09:20"},
        "exit_time":  {"type": "time", "label": "Exit time",         "default": "15:15"},
        "capital":    {"type": "int",  "label": "Capital (Rs)",      "default": 100000, "min": 10000, "max": 10000000},
        "start":      {"type": "date", "label": "From date", "default": None},
        "end":        {"type": "date", "label": "To date",   "default": None},
    },
}


def legs(ctx, params):
    lots = int(params.get("lots", 1))
    step = ctx["step"]
    off = int(round(int(params.get("offset", 50)) / step) * step)
    atm = ctx["atm"]
    return [
        {"type": "CE", "action": "sell", "strike": atm - off, "lots": lots},
        {"type": "CE", "action": "buy",  "strike": atm + off, "lots": lots},
    ]
