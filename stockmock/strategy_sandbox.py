"""
strategy_sandbox.py -- run AI-written EQUITY strategy code SAFELY.

An AI-generated strategy is a single function:
    signals(df, params) -> (entry, exit)
where df has columns open/high/low/close indexed by date, and entry/exit are
boolean arrays/Series aligned to df's rows (True on the bar whose CLOSE gives
the signal; the engine acts next-open, so there's no lookahead).

Defense in layers (same shape as AI/sandbox.py):
  1. AST validation  -- reject imports, dunder access, dangerous builtins.
  2. Restricted exec -- code sees only np / pd + a small safe builtin set.
  3. Subprocess + timeout -- the backtest runs in a killable child process.
Prototype-grade isolation (good for a local demo; the same shape we'd harden
for multi-tenant production). ASCII-only.
"""
import ast
import builtins
import json
import os
import subprocess
import sys
import threading
from datetime import datetime

try:
    import resource                # POSIX only -- available on the Linux deploy target
except ImportError:
    resource = None                # Windows dev machine: memory cap becomes a no-op

HERE = os.path.dirname(os.path.abspath(__file__))
GEN_DIR = os.path.join(HERE, "generated_strategies")
RUNNER = os.path.join(HERE, "strategy_runner.py")

_MEM_LIMIT_BYTES = 1024 * 1024 * 1024      # 1 GB virtual memory per sandboxed run
_MAX_OUTPUT_BYTES = 2 * 1024 * 1024        # 2 MB cap on captured stdout/stderr each


def _limit_child_resources():
    """preexec_fn (POSIX only): cap the child's virtual memory so a runaway
    allocation (e.g. np.zeros(10**9)) gets killed instead of OOM-ing the whole
    Streamlit process -- which would take down every user's session, not just
    the one that submitted the bad code."""
    try:
        resource.setrlimit(resource.RLIMIT_AS, (_MEM_LIMIT_BYTES, _MEM_LIMIT_BYTES))
    except Exception:
        pass


class SandboxError(Exception):
    pass


# Note: 'exit'/'quit' are intentionally NOT forbidden -- they're natural variable
# names for the (entry, exit) contract and aren't in SAFE_BUILTINS anyway.
FORBIDDEN_NAMES = {
    "open", "eval", "exec", "compile", "__import__", "input",
    "globals", "locals", "vars", "getattr", "setattr", "delattr", "memoryview",
    "breakpoint", "help", "copyright", "credits", "license", "object", "type",
}


def validate_code(code):
    """Raise SandboxError if unsafe/malformed; else return code. Must define signals()."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise SandboxError("syntax error: %s" % e)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise SandboxError("imports are not allowed (np and pd are provided)")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise SandboxError("dunder attribute access is not allowed: %s" % node.attr)
        if isinstance(node, ast.Name):
            if node.id.startswith("__"):
                raise SandboxError("dunder name is not allowed: %s" % node.id)
            if node.id in FORBIDDEN_NAMES:
                raise SandboxError("use of '%s' is not allowed" % node.id)
    funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    if "signals" not in funcs:
        raise SandboxError("code must define a function named 'signals(df, params)'")
    return code


_SAFE_BUILTIN_NAMES = [
    "range", "len", "min", "max", "abs", "float", "int", "bool", "enumerate",
    "zip", "sorted", "sum", "list", "dict", "tuple", "set", "round", "isinstance",
    "str", "map", "filter", "any", "all", "reversed", "slice", "print", "True", "False", "None",
]
SAFE_BUILTINS = {n: getattr(builtins, n, None) for n in _SAFE_BUILTIN_NAMES}


def load_signals(code):
    """Validate + exec in a restricted namespace; return the signals() function."""
    validate_code(code)
    import numpy as np
    import pandas as pd
    ns = {"__builtins__": SAFE_BUILTINS, "np": np, "pd": pd}
    exec(compile(code, "<ai_strategy>", "exec"), ns)
    fn = ns.get("signals")
    if not callable(fn):
        raise SandboxError("no callable signals() found")
    return fn


def save_generated(code, tag="strategy"):
    os.makedirs(GEN_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(GEN_DIR, "gen_%s_%s.py" % (ts, "".join(c if c.isalnum() else "_" for c in tag)[:30]))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(code)
    return path


def run_generated(code, name, params, timeout=60, repeats=1):
    """Validate, save, and run the generated strategy in an isolated subprocess.
    `repeats` > 1 benchmarks signals() timing (for the code-optimizer). The result
    dict carries signals_ms + signals_checksum. Returns {'result', 'path'}.

    Bounded on three axes so a runaway AI-generated strategy can't take the whole
    app down: wall-clock timeout, captured-output size (a huge print loop would
    otherwise buffer unbounded in the parent before we ever get to truncate it),
    and -- on the Linux deploy target -- virtual memory via RLIMIT_AS."""
    validate_code(code)                                   # fail fast, in-process
    path = save_generated(code, tag=name)
    cmd = [sys.executable, RUNNER, path, name, json.dumps(params), str(int(repeats))]
    preexec = _limit_child_resources if resource is not None else None
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, cwd=HERE, preexec_fn=preexec)

    outbuf, errbuf, killed = [], [], {"reason": None}

    def _kill(reason):
        if killed["reason"] is None:
            killed["reason"] = reason
            try:
                proc.kill()
            except Exception:
                pass

    def _reader(stream, buf):
        total = 0
        for chunk in iter(lambda: stream.read(4096), ""):
            buf.append(chunk)
            total += len(chunk)
            if total > _MAX_OUTPUT_BYTES:
                buf.append("\n...[output truncated -- exceeded %d bytes]" % _MAX_OUTPUT_BYTES)
                _kill("output")
                break

    t_out = threading.Thread(target=_reader, args=(proc.stdout, outbuf), daemon=True)
    t_err = threading.Thread(target=_reader, args=(proc.stderr, errbuf), daemon=True)
    t_out.start(); t_err.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill("timeout")
        proc.wait(timeout=5)
    t_out.join(timeout=5); t_err.join(timeout=5)

    out, err = "".join(outbuf), "".join(errbuf)
    if killed["reason"] == "timeout":
        raise SandboxError("strategy timed out after %ds (possible infinite loop)" % timeout)
    if killed["reason"] == "output":
        raise SandboxError("strategy produced too much output (possible runaway loop) -- killed.")
    if proc.returncode != 0:
        raise SandboxError("execution failed:\n%s" % (err[-1500:] or "(no stderr)"))
    for line in out.splitlines():
        if line.startswith("__RESULT__"):
            return {"result": json.loads(line[len("__RESULT__"):]), "path": path}
    raise SandboxError("no result produced.\nstdout tail:\n%s" % out[-800:])
