"""
Straddle-Width Strangle -- strikes offset by a MULTIPLE of the straddle premium.

StockMock's "Straddle Width" mode (legs shown as ATM +/- 1*SP). The offset in
points equals `width_mult` x the ATM straddle premium, so the strikes widen
automatically when options are expensive (high volatility).
"""

META = {
    "key": "straddle_width",
    "name": "Straddle-Width Strangle",
    "instrument": "options",
    "description": ("Sell a Call and Put offset from ATM by width_mult x the straddle "
                    "premium. Strikes self-widen with volatility (Straddle Width mode)."),
    "variables": {
        "lots":       {"type": "int",   "label": "Lots",             "default": 1,      "min": 1,     "max": 50},
        "width_mult": {"type": "float", "label": "Width (x straddle premium)", "default": 1.0, "min": 0.1, "max": 5},
        "lot_size":   {"type": "int",   "label": "Lot size (Nifty)", "default": 25,     "min": 1,     "max": 100},
        "entry_time": {"type": "time",  "label": "Entry time",       "default": "09:20"},
        "exit_time":  {"type": "time",  "label": "Exit time",        "default": "15:15"},
        "capital":    {"type": "int",   "label": "Capital (Rs)",     "default": 100000, "min": 10000, "max": 10000000},
        "start":      {"type": "date",  "label": "From date", "default": None},
        "end":        {"type": "date",  "label": "To date",   "default": None},
    },
}


def legs(ctx, params):
    lots = int(params.get("lots", 1))
    mult = float(params.get("width_mult", 1.0))
    step = ctx["step"]
    atm = ctx["atm"]
    off = int(round(mult * ctx["straddle_premium"] / step) * step)
    return [
        {"type": "CE", "action": "sell", "strike": atm + off, "lots": lots},
        {"type": "PE", "action": "sell", "strike": atm - off, "lots": lots},
    ]
