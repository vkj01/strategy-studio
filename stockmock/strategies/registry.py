"""
registry.py -- catalogue of StockMock-style strategies, tagged by instrument.

The frontend reads list_meta(instrument='equity') to build the strategy menu +
the variable forms. The engine reads get(key)['signals'] to run one.
"""
import json
import os

from . import (ma_crossover, rsi_reversion, macd_crossover, supertrend,
               short_straddle, short_strangle, long_straddle, long_strangle,
               iron_butterfly, short_cp, short_cp_sp, short_atm_pct, straddle_width)

_MODULES = (ma_crossover, rsi_reversion, macd_crossover, supertrend,
            short_straddle, short_strangle, long_straddle, long_strangle,
            iron_butterfly, short_cp, short_cp_sp, short_atm_pct, straddle_width)

# equity strategies expose signals(); options strategies expose legs()
STRATEGIES = {m.META["key"]: {"meta": m.META,
                              "signals": getattr(m, "signals", None),
                              "legs": getattr(m, "legs", None)}
              for m in _MODULES}


def get(key):
    return STRATEGIES[key]


def list_meta(instrument=None):
    metas = [s["meta"] for s in STRATEGIES.values()]
    if instrument:
        metas = [m for m in metas if m.get("instrument") == instrument]
    return metas


def defaults(key):
    """Default variable values for a strategy -- the form's initial state."""
    return {name: spec.get("default") for name, spec in get(key)["meta"]["variables"].items()}


def export_json(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "registry.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(list_meta(), fh, indent=2)
    return path
