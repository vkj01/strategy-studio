"""
Short CP as % of Straddle Premium -- StockMock's "Short CP As 25%SP".

SP (straddle premium) = ATM Call premium + ATM Put premium at entry.
Target = sp_pct% of SP. Sell the CE and PE whose premium is closest to that
target. Self-scaling: strikes widen automatically when volatility is high.
"""

META = {
    "key": "short_cp_sp",
    "name": "Short CP as % of Straddle Premium",
    "instrument": "options",
    "description": ("Sell the Call and Put whose premium is closest to a percentage "
                    "of the ATM straddle premium (e.g. 25%). Self-scaling with volatility."),
    "variables": {
        "lots":     {"type": "int",   "label": "Lots",              "default": 1,      "min": 1,     "max": 50},
        "sp_pct":   {"type": "float", "label": "% of straddle premium", "default": 25, "min": 5,     "max": 100},
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
    pct = float(params.get("sp_pct", 25)) / 100.0
    target = ctx["straddle_premium"] * pct
    ce = ctx["find_by_premium"]("CE", target)
    pe = ctx["find_by_premium"]("PE", target)
    out = []
    if ce is not None:
        out.append({"type": "CE", "action": "sell", "strike": ce, "lots": lots})
    if pe is not None:
        out.append({"type": "PE", "action": "sell", "strike": pe, "lots": lots})
    return out
