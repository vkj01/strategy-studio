"""
Iron Condor -- neutral, defined-risk credit strategy (4 legs).

Sell an OTM call spread AND an OTM put spread: collect premium on both wings while
capping risk with farther long options. Profits if the index stays within a range.
Wider profit zone than an Iron Butterfly (whose short strikes sit at the ATM).
Default: short legs `short_offset` from ATM, long wings `wing` beyond them.
"""

META = {
    "key": "iron_condor",
    "name": "Iron Condor",
    "instrument": "options",
    "description": ("Sell OTM call + put spreads (short strikes short_offset from ATM, "
                    "long wings wing beyond). Neutral, range-bound, defined-risk credit."),
    "variables": {
        "lots":         {"type": "int",  "label": "Lots",             "default": 1,      "min": 1,     "max": 50},
        "short_offset": {"type": "int",  "label": "Short strike from ATM (pts)", "default": 50, "min": 50, "max": 2000},
        "wing":         {"type": "int",  "label": "Wing width (pts)",  "default": 50,     "min": 50,    "max": 2000},
        "lot_size":     {"type": "int",  "label": "Lot size (Nifty)",  "default": 25,     "min": 1,     "max": 100},
        "entry_time":   {"type": "time", "label": "Entry time",        "default": "09:20"},
        "exit_time":    {"type": "time", "label": "Exit time",         "default": "15:15"},
        "capital":      {"type": "int",  "label": "Capital (Rs)",      "default": 100000, "min": 10000, "max": 10000000},
        "start":        {"type": "date", "label": "From date", "default": None},
        "end":          {"type": "date", "label": "To date",   "default": None},
    },
}


def legs(ctx, params):
    lots = int(params.get("lots", 1))
    step = ctx["step"]
    so = int(round(int(params.get("short_offset", 50)) / step) * step)
    wing = int(round(int(params.get("wing", 50)) / step) * step)
    atm = ctx["atm"]
    return [
        {"type": "CE", "action": "sell", "strike": atm + so,        "lots": lots},
        {"type": "CE", "action": "buy",  "strike": atm + so + wing, "lots": lots},
        {"type": "PE", "action": "sell", "strike": atm - so,        "lots": lots},
        {"type": "PE", "action": "buy",  "strike": atm - so - wing, "lots": lots},
    ]
