"""
Bear Put Spread -- bearish, defined-risk debit spread on the put side.

Buy the farther (higher-strike) Put and sell a nearer (lower-strike) Put to cheapen
it. Pays a net debit; profits if the index falls. StockMock default straddles the
ATM: buy PE at ATM+offset, sell PE at ATM-offset.
"""

META = {
    "key": "bear_put_spread",
    "name": "Bear Put Spread",
    "instrument": "options",
    "description": ("Buy PE at ATM+offset, sell PE at ATM-offset. Bearish debit "
                    "spread with capped risk and reward."),
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
        {"type": "PE", "action": "buy",  "strike": atm + off, "lots": lots},
        {"type": "PE", "action": "sell", "strike": atm - off, "lots": lots},
    ]
