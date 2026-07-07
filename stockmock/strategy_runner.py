"""
strategy_runner.py -- subprocess entry that runs ONE AI-generated equity strategy
in isolation. Invoked by strategy_sandbox as:
    python strategy_runner.py <code_path> <name> <params_json> [repeats]
Validates + loads signals() in the restricted sandbox, wraps it with output-shape
checks, runs it through the portfolio engine, and prints __RESULT__<json>.

When `repeats` > 1 (code-optimizer benchmarking) it runs the backtest that many
times, accumulates the time spent INSIDE signals() only (excludes engine + process
startup), and reports the average per backtest. It also emits a checksum of the
(entry, exit) signal arrays across all symbols -- two strategies with the same
checksum are provably identical, which is how we prove an "optimized" rewrite
didn't change the results. A parent-side timeout kills this process if it hangs.
ASCII-only.
"""
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    code_path, name, params_json = sys.argv[1], sys.argv[2], sys.argv[3]
    repeats = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    repeats = max(1, repeats)
    with open(code_path, "r", encoding="utf-8") as fh:
        code = fh.read()
    params = json.loads(params_json)

    import numpy as np
    import strategy_sandbox as sb
    import engine

    signals = sb.load_signals(code)                 # AST-validated + restricted exec
    acc = {"sig_ms": 0.0, "hash": None}

    def make_safe(record_hash):
        def safe_signals(df, p):
            t0 = time.perf_counter()
            out = signals(df, p)
            acc["sig_ms"] += (time.perf_counter() - t0) * 1000.0
            if not (isinstance(out, tuple) and len(out) == 2):
                raise ValueError("signals(df, params) must return a tuple (entry, exit)")
            e, x = out
            e = np.asarray(e).astype(bool); x = np.asarray(x).astype(bool)
            if len(e) != len(df) or len(x) != len(df):
                raise ValueError("entry/exit arrays must be the same length as df (%d)" % len(df))
            if record_hash and acc["hash"] is not None:
                acc["hash"].update(np.ascontiguousarray(e).tobytes())
                acc["hash"].update(np.ascontiguousarray(x).tobytes())
            return e, x
        return safe_signals

    res = None
    for i in range(repeats):
        final = (i == repeats - 1)                  # hash only the final clean pass
        if final:
            acc["hash"] = hashlib.md5()
        res = engine.summarize_with_signals(make_safe(final), name or "AI strategy", params)

    res.pop("_trades_full", None)                   # keep payload lean
    res["signals_ms"] = round(acc["sig_ms"] / repeats, 4)
    res["signals_checksum"] = acc["hash"].hexdigest()[:16] if acc["hash"] else ""
    sys.stdout.write("__RESULT__" + json.dumps(res))


if __name__ == "__main__":
    main()
