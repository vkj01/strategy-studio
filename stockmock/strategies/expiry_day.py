"""
Expiry Day Strategy -- a short straddle that only trades on expiry days (DTE 0).

Sell the ATM Call and ATM Put, but ENTER only on the weekly expiry day, when time
decay is fastest. StockMock's "Expiry Day Strategy". Same legs as a short straddle;
the `expiry_only` flag makes the engine skip every non-expiry day.
"""

META = {
    "key": "expiry_day",
    "name": "Expiry Day Strategy",
    "instrument": "options",
    "description": ("Sell the ATM Call and ATM Put, but only on the weekly expiry day "
                    "(DTE 0) when theta decay is fastest. Intraday, buy back at exit."),
    "variables": {
        "lots":         {"type": "int",   "label": "Lots",           "default": 1,      "min": 1,     "max": 50},
        "sl_pct":       {"type": "float", "label": "Per-leg SL %",    "default": 25,     "min": 0,     "max": 100},
        "expiry_offset": {"type": "int",  "label": "Trading days before expiry", "default": 0, "min": 0, "max": 4},
        "lot_size":   {"type": "int",   "label": "Lot size (Nifty)",  "default": 25,     "min": 1,     "max": 100},
        "entry_time": {"type": "time",  "label": "Entry time",        "default": "09:20"},
        "exit_time":  {"type": "time",  "label": "Exit time",         "default": "15:15"},
        "capital":    {"type": "int",   "label": "Capital (Rs)",      "default": 100000, "min": 10000, "max": 10000000},
        "start":      {"type": "date",  "label": "From date", "default": None},
        "end":        {"type": "date",  "label": "To date",   "default": None},
    },
    # engine flag: restrict the day-loop to expiry days (DTE 0).
    "fixed_params": {"expiry_only": True},
}


def legs(ctx, params):
    lots = int(params.get("lots", 1))
    sl = float(params.get("sl_pct", 25) or 0)     # StockMock's Expiry Day default = 25% per-leg SL
    atm = ctx["atm"]
    return [
        {"type": "CE", "action": "sell", "strike": atm, "lots": lots, "sl_pct": sl},
        {"type": "PE", "action": "sell", "strike": atm, "lots": lots, "sl_pct": sl},
    ]
