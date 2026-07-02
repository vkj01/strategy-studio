"""
Short Straddle -- the classic intraday options-selling strategy.

Each day: SELL the ATM Call + SELL the ATM Put at the entry time, buy both back
at the exit time. Profits from time decay on quiet days; loses on big moves.
Validated against StockMock (exact ATM strikes, exits to the paisa).

Options strategies declare LEGS (relative to ATM); the options engine prices
them from the real NSE F&O tick data.
"""

META = {
    "key": "short_straddle",
    "name": "Short Straddle",
    "instrument": "options",
    "description": ("Sell the ATM Call and ATM Put at entry, buy both back at exit. "
                    "Intraday, weekly expiry -- earns option time-decay."),
    "variables": {
        "lots":       {"type": "int",  "label": "Lots",            "default": 1,      "min": 1,     "max": 50},
        "lot_size":   {"type": "int",  "label": "Lot size (Nifty)", "default": 25,    "min": 1,     "max": 100},
        "entry_time": {"type": "time", "label": "Entry time",       "default": "09:20"},
        "exit_time":  {"type": "time", "label": "Exit time",        "default": "15:15"},
        "capital":    {"type": "int",  "label": "Capital (Rs)",     "default": 100000, "min": 10000, "max": 10000000},
        "start":      {"type": "date", "label": "From date", "default": None},
        "end":        {"type": "date", "label": "To date",   "default": None},
    },
}


def legs(ctx, params):
    lots = int(params.get("lots", 1))
    atm = ctx["atm"]
    return [
        {"type": "CE", "action": "sell", "strike": atm, "lots": lots},
        {"type": "PE", "action": "sell", "strike": atm, "lots": lots},
    ]
