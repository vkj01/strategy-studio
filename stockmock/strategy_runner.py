"""
strategy_runner.py -- subprocess entry that runs ONE AI-generated equity strategy
in isolation. Invoked by strategy_sandbox.run_generated as:
    python strategy_runner.py <code_path> <name> <params_json>
Validates + loads signals() in the restricted sandbox, wraps it with output-shape
checks, runs it through the portfolio engine, and prints __RESULT__<json>.
A parent-side timeout kills this process if it hangs. ASCII-only.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    code_path, name, params_json = sys.argv[1], sys.argv[2], sys.argv[3]
    with open(code_path, "r", encoding="utf-8") as fh:
        code = fh.read()
    params = json.loads(params_json)

    import numpy as np
    import strategy_sandbox as sb
    import engine

    signals = sb.load_signals(code)                 # AST-validated + restricted exec

    def safe_signals(df, p):
        out = signals(df, p)
        if not (isinstance(out, tuple) and len(out) == 2):
            raise ValueError("signals(df, params) must return a tuple (entry, exit)")
        e, x = out
        e = np.asarray(e).astype(bool); x = np.asarray(x).astype(bool)
        if len(e) != len(df) or len(x) != len(df):
            raise ValueError("entry/exit arrays must be the same length as df (%d)" % len(df))
        return e, x

    res = engine.summarize_with_signals(safe_signals, name or "AI strategy", params)
    # keep payload lean: drop the internal full-trade list if present
    res.pop("_trades_full", None)
    sys.stdout.write("__RESULT__" + json.dumps(res))


if __name__ == "__main__":
    main()
