"""
Short CP (Closest Premium) -- sell the CE and PE whose premium is closest to a
target value (e.g. 100). StockMock's "Short CP 100".

Instead of picking strikes by distance from ATM, this picks them by PREMIUM --
so risk/reward is normalised across days regardless of volatility.
"""

META = {
    "key": "short_cp",
    "name": "Short CP (Closest Premium)",
    "instrument": "options",
    "description": ("Sell the Call and Put whose premium is closest to the target "
                    "(e.g. 100). Strike chosen by premium, not distance from ATM."),
    "variables": {
        "lots":           {"type": "int",  "label": "Lots",             "default": 1,      "min": 1,     "max": 50},
        "target_premium": {"type": "float", "label": "Target premium",  "default": 100,    "min": 5,     "max": 500},
        "lot_size":       {"type": "int",  "label": "Lot size (Nifty)", "default": 25,     "min": 1,     "max": 100},
        "entry_time":     {"type": "time", "label": "Entry time",       "default": "09:20"},
        "exit_time":      {"type": "time", "label": "Exit time",        "default": "15:15"},
        "capital":        {"type": "int",  "label": "Capital (Rs)",     "default": 100000, "min": 10000, "max": 10000000},
        "start":          {"type": "date", "label": "From date", "default": None},
        "end":            {"type": "date", "label": "To date",   "default": None},
    },
}


def legs(ctx, params):
    lots = int(params.get("lots", 1))
    target = float(params.get("target_premium", 100))
    ce = ctx["find_by_premium"]("CE", target)
    pe = ctx["find_by_premium"]("PE", target)
    out = []
    if ce is not None:
        out.append({"type": "CE", "action": "sell", "strike": ce, "lots": lots})
    if pe is not None:
        out.append({"type": "PE", "action": "sell", "strike": pe, "lots": lots})
    return out
