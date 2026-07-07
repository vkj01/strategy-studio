"""
Long Futures -- buy the near-month NIFTY future (directional, intraday).

Profits when the index rises. Optional stop-loss / target / step-trailing-stop
(as % of the entry price) and entry/exit times. A single linear FUT leg -- no
strikes. StockMock's Futures segment, Buy side.
"""

META = {
    "key": "long_futures",
    "name": "Long Futures",
    "instrument": "futures",
    "description": ("Buy the near-month NIFTY future. Directional bullish, intraday. "
                    "Optional SL / target / trailing stop (% of entry)."),
    "variables": {
        "lots":       {"type": "int",   "label": "Lots",            "default": 1,      "min": 1,     "max": 50},
        "sl_pct":     {"type": "float", "label": "Stop-loss %",      "default": 0,      "min": 0,     "max": 20},
        "tp_pct":     {"type": "float", "label": "Target %",         "default": 0,      "min": 0,     "max": 20},
        "trail_x":    {"type": "float", "label": "Trail: every X%",  "default": 0,      "min": 0,     "max": 20},
        "trail_y":    {"type": "float", "label": "Trail: move SL Y%","default": 0,      "min": 0,     "max": 20},
        "lot_size":   {"type": "int",   "label": "Lot size (Nifty)", "default": 25,     "min": 1,     "max": 100},
        "entry_time": {"type": "time",  "label": "Entry time",       "default": "09:20"},
        "exit_time":  {"type": "time",  "label": "Exit time",        "default": "15:15"},
        "capital":    {"type": "int",   "label": "Capital (Rs)",     "default": 100000, "min": 10000, "max": 10000000},
        "start":      {"type": "date",  "label": "From date", "default": None},
        "end":        {"type": "date",  "label": "To date",   "default": None},
    },
}


def legs(ctx, params):
    return [{
        "type": "FUT", "action": "buy", "symbol": "NIFTY",
        "lots": int(params.get("lots", 1)),
        "sl_pct": float(params.get("sl_pct", 0) or 0),
        "tp_pct": float(params.get("tp_pct", 0) or 0),
        "trail_x": float(params.get("trail_x", 0) or 0),
        "trail_y": float(params.get("trail_y", 0) or 0),
    }]
