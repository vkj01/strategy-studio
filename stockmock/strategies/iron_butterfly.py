"""
Iron Butterfly -- sell the ATM straddle, buy protective OTM wings.

Sell ATM Call + ATM Put (collect premium), buy an OTM Call and OTM Put
`wing` points out for protection. Capped risk version of a short straddle.
"""

META = {
    "key": "iron_butterfly",
    "name": "Iron Butterfly",
    "instrument": "options",
    "description": ("Sell the ATM Call and ATM Put, buy OTM Call and Put `wing` "
                    "points out as protection. Defined-risk premium selling."),
    "variables": {
        "lots":       {"type": "int",  "label": "Lots",             "default": 1,      "min": 1,     "max": 50},
        "wing":       {"type": "int",  "label": "Wing width (pts)",  "default": 200,    "min": 50,    "max": 2000},
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
    wing = int(round(int(params.get("wing", 200)) / step) * step)
    atm = ctx["atm"]
    return [
        {"type": "CE", "action": "sell", "strike": atm, "lots": lots},
        {"type": "PE", "action": "sell", "strike": atm, "lots": lots},
        {"type": "CE", "action": "buy", "strike": atm + wing, "lots": lots},
        {"type": "PE", "action": "buy", "strike": atm - wing, "lots": lots},
    ]
