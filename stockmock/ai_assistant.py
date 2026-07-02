"""
ai_assistant.py -- the platform's AI research assistant (brain).

Step 1: a context-aware conversationalist. It knows every strategy on the
platform (equity + options) and their variables, and answers questions / discusses
ideas. Later steps add: run backtests from chat, run-history awareness, and
strategy code generation.

Provider-agnostic via call_llm (Groq free now; Anthropic when a key is added to
.env). ASCII-only.
"""
import os

from strategies import registry


# --- keys: read .env from the project (checks a few sensible locations) ------
def _load_dotenv():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, ".env"),
              os.path.join(here, "..", ".env"),
              os.path.join(here, "..", "AI", ".env")):
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _load_streamlit_secrets():
    """On Streamlit Cloud there's no .env -- pull API keys from st.secrets into the
    environment so call_llm (which reads os.environ) works. Safe outside Streamlit."""
    try:
        import streamlit as st
        for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
            if not os.environ.get(k) and k in st.secrets:
                os.environ[k] = str(st.secrets[k])
    except Exception:
        pass


_load_dotenv()
_load_streamlit_secrets()

# --- providers (config-only; swap models/providers here) ---------------------
PROVIDERS = {
    "groq": {"key": "GROQ_API_KEY", "kind": "openai",
             "base_url": "https://api.groq.com/openai/v1",
             "cheap": "llama-3.1-8b-instant", "strong": "llama-3.3-70b-versatile"},
    "anthropic": {"key": "ANTHROPIC_API_KEY", "kind": "anthropic", "base_url": None,
                  "cheap": "claude-haiku-4-5", "strong": "claude-opus-4-8"},
    "openai": {"key": "OPENAI_API_KEY", "kind": "openai", "base_url": None,
               "cheap": "gpt-4o-mini", "strong": "gpt-4o"},
}
PREFERENCE = {"cheap": ["groq", "anthropic", "openai"],
              "strong": ["anthropic", "openai", "groq"]}


def _pick(tier):
    for name in PREFERENCE[tier]:
        cfg = PROVIDERS[name]
        if os.environ.get(cfg["key"]):
            return name, cfg
    return None


def llm_available():
    return any(os.environ.get(p["key"]) for p in PROVIDERS.values())


def active_label(tier="strong"):
    picked = _pick(tier)
    return "%s (%s)" % (picked[0], picked[1][tier]) if picked else "offline"


def call_llm(prompt, tier="strong", system=None, max_tokens=1200):
    picked = _pick(tier)
    if not picked:
        raise RuntimeError("No LLM provider configured (add a key to .env).")
    _, cfg = picked
    model = cfg[tier]
    if cfg["kind"] == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ[cfg["key"]])
        kwargs = dict(model=model, max_tokens=max_tokens,
                      messages=[{"role": "user", "content": prompt}])
        if system:
            kwargs["system"] = [{"type": "text", "text": system,
                                 "cache_control": {"type": "ephemeral"}}]
        resp = client.messages.create(**kwargs)
        return "".join(b.text for b in resp.content if b.type == "text")
    from openai import OpenAI
    client = OpenAI(api_key=os.environ[cfg["key"]], base_url=cfg["base_url"])
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    resp = client.chat.completions.create(model=model, max_tokens=max_tokens, messages=msgs)
    return resp.choices[0].message.content or ""


# --- platform awareness ------------------------------------------------------
def platform_context():
    lines = []
    for label, inst in (("EQUITY", "equity"), ("OPTIONS", "options")):
        lines.append("%s strategies:" % label)
        for m in registry.list_meta(inst):
            vs = ", ".join(m["variables"].keys())
            lines.append("  - %s (key=%s): %s [variables: %s]"
                         % (m["name"], m["key"], m["description"], vs))
    return "\n".join(lines)


SYSTEM = """You are the AI research analyst built into "Strategy Studio", a
stock & options strategy BACKTESTING platform. You help the user understand and
use the platform: explain the available strategies and their variables, discuss
trading ideas honestly, and help them decide what to test.

Be concise, practical, and honest. You have three tools:
  - run_backtest: run one backtest (preset strategy or custom options legs).
  - sweep_backtest: grid-search params to find the best combo (ranked).
  - build_strategy: write + run a NEW custom EQUITY strategy (signals(df,params)) when the
    presets don't cover the idea. np/pd only, no imports, vectorized, no infinite loops.

*** ABSOLUTE RULE -- NEVER FABRICATE NUMBERS ***
Every backtest metric you state (P&L, return, win rate, drawdown, CAGR, trades) MUST come from
a tool call you made IN THIS TURN. You may NOT recall, estimate, reconstruct, or "remember"
precise numbers from earlier in the chat or from the run-history context and present them as
results. The run-history summary is BACKGROUND ONLY -- never quote its figures as if you ran
them. If you need a number you have not produced with a tool this turn -- ESPECIALLY a
comparison baseline (e.g. "the no-stop version") -- you MUST run the tool to get it. When in
doubt, RUN IT. If you truly cannot run something, say so plainly; do not fill the gap with a
plausible-looking number.

When the user asks to run / test / optimize / compare / build, CALL the right tool(s), then
explain the REAL results. Pick sensible defaults for anything unspecified (options entry
09:20 / exit 15:15, lot 65, square-off one leg; equity top-50) and STATE your assumptions.

Being ECONOMICAL means: don't run the EXACT same call twice, and keep sweep grids small and
purposeful. It does NOT mean skipping a needed run and guessing -- a fresh, correct number is
always worth one tool call. To COMPARE A vs B, you must have run BOTH this turn (or B is
genuinely unchanged from a run you already did this turn); never compare a fresh run against a
half-remembered one.
After results, be a candid analyst -- flag weak win rates, large drawdowns, small samples,
and overfitting risk rather than cheerleading.

APPLES-TO-APPLES + FULL DISCLOSURE (critical): Always STATE the full parameter set you
actually used -- including any values carried over from earlier runs (capital, max_positions,
costs, universe). Do NOT silently inherit unrelated settings from a previous run. When you
COMPARE a new run to a prior one, change ONLY the one variable under study and keep EVERY
other parameter identical to that baseline; if the baseline used different settings (e.g. it
had no position cap but your new run does), either re-run the baseline to match, or explicitly
say the comparison changed more than one thing. NEVER attribute a result difference to one knob
when another knob also changed.

IMPORTANT on drawdown/return percentages: every percentage divides by that position's OWN
margin/capital (given as margin_or_capital_rs). So when you COMPARE DIFFERENT structures --
e.g. a naked straddle (big margin) vs a hedged/defined-risk one like an iron butterfly or
cheap-wing fly (much smaller margin) -- the hedged one will show a BIGGER drawdown percent
even when its RUPEE drawdown (max_drawdown_rs) is actually SMALLER. Do NOT call the hedged
position "worse drawdown" from the percentage alone. Compare drawdown in RUPEES
(max_drawdown_rs) for a fair, apples-to-apples read, and briefly explain the margin-base
effect when it matters.

Here are the strategies currently on the platform:
%s"""


def _history_context():
    try:
        import store
        return store.recent_context(limit=6)
    except Exception:
        return "The user has not run any backtests yet."


def _system_blocks():
    """Two system blocks so cost stays low across a conversation:
      - block 1 (CACHED): static instructions + strategy list -- unchanged all
        session, so it's a cheap cache-read every turn;
      - block 2 (fresh): the user's recent run-history, which changes each time a
        backtest runs (keeping it OUT of the cached block avoids re-billing the
        whole prompt at full price whenever a new run is logged).
    """
    return [
        {"type": "text", "text": SYSTEM % platform_context(), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "The user's recent backtest runs (most recent first):\n" + _history_context()},
    ]


def chat(history):
    """Context-aware reply to the conversation so far. history = [{role, content}]."""
    if not llm_available():
        return ("The assistant isn't configured yet -- add an API key (Groq is free, "
                "or Anthropic) to .env and reload.")
    system = SYSTEM % platform_context() + "\n\nThe user's recent runs:\n" + _history_context()
    convo = "\n".join("%s: %s" % ("USER" if m["role"] == "user" else "ASSISTANT", m["content"])
                      for m in history[-20:])
    try:
        return call_llm(convo + "\n\nASSISTANT:", tier="strong", system=system, max_tokens=900)
    except Exception as e:
        return "AI error: %s" % e


# ============================================================================
# AGENTIC LAYER -- the AI actually RUNS backtests via a tool (Claude tool-use)
# ============================================================================
import json  # noqa: E402

_OPT_KEYS = ("short_straddle", "short_strangle", "long_straddle", "long_strangle",
             "iron_butterfly", "short_cp", "short_cp_sp", "short_atm_pct", "straddle_width")
_EQ_KEYS = ("ma_crossover", "rsi_reversion", "macd_crossover", "supertrend")

# --- GUARDRAILS (bound compute + LLM spend + runaway code) -------------------
_SWEEP_CAP = 60        # max grid combinations per sweep call
_TURN_BT_CAP = 200     # max total engine backtests per user message (across all tool calls)
# (LLM calls are bounded by chat_agentic max_rounds=4; generated code by a 60s subprocess kill.)

RUN_TOOL = {
    "name": "run_backtest",
    "description": (
        "Run a REAL backtest on the platform's historical data and get the results. "
        "Call this whenever the user asks to test / run / backtest / try a strategy. "
        "Options data = NIFTY weekly, ~30-Mar to 30-Jun 2026 (56 trading days); lot size 65. "
        "Equity data = ~150 NSE stocks daily, 2019-2026. Do NOT invent numbers -- always "
        "call this tool to get real results, then explain them honestly."),
    "input_schema": {
        "type": "object",
        "properties": {
            "instrument": {"type": "string", "enum": ["options", "equity"]},
            "strategy": {"type": "string", "description":
                         "Registry key. options: " + ", ".join(_OPT_KEYS) + ". equity: "
                         + ", ".join(_EQ_KEYS) + ". Omit and give 'legs' for a custom options position."},
            "legs": {"type": "array", "description":
                     "Custom options legs (instead of a preset). Per-leg extras: trail_x/trail_y "
                     "(step-trail: every trail_x% favorable move shifts SL by trail_y%), wait_pct "
                     "(Wait & Trade: enter only after premium moves this %), re_entry (times to "
                     "re-enter after SL, refilling when premium returns to entry), re_execute (times "
                     "after target), journey {action,type,value,sl_pct} (on this leg's SL, sell a fresh "
                     "ATM leg -- 'adjust on stop').",
                     "items": {"type": "object", "properties": {
                         "action": {"type": "string", "enum": ["sell", "buy"]},
                         "type": {"type": "string", "enum": ["CE", "PE"]},
                         "mode": {"type": "string", "enum": ["atm_point", "atm_pct", "width", "cp", "cp_sp"]},
                         "value": {"type": "number"}, "lots": {"type": "integer"},
                         "sl_pct": {"type": "number"}, "tp_pct": {"type": "number"},
                         "trail_x": {"type": "number"}, "trail_y": {"type": "number"},
                         "wait_pct": {"type": "number"},
                         "re_entry": {"type": "integer"}, "re_execute": {"type": "integer"},
                         "journey": {"type": "object"}},
                         "required": ["action", "type"]}},
            "params": {"type": "object", "description":
                       "Engine params. OPTIONS: entry_time, exit_time (HH:MM), start, end (YYYY-MM-DD), "
                       "lot_size (65), square_off ('one'|'all'), sl_mtm, target_mtm (Rs, whole strategy), "
                       "move_sl_to_cost (bool), slippage_pct, cost_per_lot. "
                       "EQUITY: universe_size, fast_ma/slow_ma/ma_type (or rsi_period/oversold/exit_level, "
                       "macd_fast/macd_slow/macd_signal, atr_period/multiplier), stop_loss_pct, target_pct, "
                       "trail_stop_pct, max_hold_days, capital, max_positions, cost_pct, start, end."}},
        "required": ["instrument"]}}

SWEEP_TOOL = {
    "name": "sweep_backtest",
    "description": (
        "Grid-search / optimize: run MANY backtests over a grid of parameter values and "
        "return them RANKED, to find the best combination. Use this when the user asks to "
        "optimize / find the best / compare a range / sweep a parameter (e.g. 'what's the best "
        "stop-loss', 'find the best strike offset', 'which lot count'). Same instrument/strategy/"
        "legs as run_backtest, plus a 'grid'. Keep the grid modest (<=60 total combinations)."),
    "input_schema": {
        "type": "object",
        "properties": {
            "instrument": {"type": "string", "enum": ["options", "equity"]},
            "strategy": {"type": "string", "description": "Registry key (or omit and give 'legs' for custom options)."},
            "legs": {"type": "array", "description": "Custom options legs (same shape as run_backtest).",
                     "items": {"type": "object"}},
            "base_params": {"type": "object", "description": "Fixed params for every run (same keys as run_backtest params)."},
            "grid": {"type": "object", "description":
                     "Map of param -> list of values to sweep, e.g. {\"sl_pct\":[15,25,35,50]} or "
                     "{\"target_mtm\":[3000,5000,8000]} or {\"fast_ma\":[20,50],\"slow_ma\":[100,200]}. "
                     "Keys sl_pct/tp_pct/trail_x/trail_y/wait_pct apply to ALL legs (options)."},
            "rank_by": {"type": "string", "enum": ["total_pnl", "return", "return_mdd", "win"],
                        "description": "How to rank. Default total_pnl."},
            "top": {"type": "integer", "description": "How many top rows to return (default 5)."}},
        "required": ["instrument", "grid"]}}

BUILD_TOOL = {
    "name": "build_strategy",
    "description": (
        "Write and run a NEW custom EQUITY strategy that the presets don't cover. Provide Python "
        "code defining `signals(df, params)` -> (entry, exit). `df` has columns open/high/low/close "
        "indexed by date; `entry`/`exit` are boolean arrays aligned to df's rows (True on the bar "
        "whose CLOSE triggers -- the engine enters next open, so no lookahead). ONLY numpy (np) and "
        "pandas (pd) are available -- NO imports, no file/OS access. Vectorize; NEVER write infinite "
        "loops (the runner is killed after 60s). Use only for genuinely custom indicator logic beyond "
        "ma_crossover/rsi_reversion/macd_crossover/supertrend."),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description":
                     "def signals(df, params):  # np, pd only, no imports\\n    ...\\n    return entry, exit"},
            "name": {"type": "string", "description": "Short name for the strategy."},
            "params": {"type": "object", "description":
                       "Engine params: universe_size, stop_loss_pct, target_pct, trail_stop_pct, "
                       "max_hold_days, capital, max_positions, cost_pct, start, end. Your code may also "
                       "read its own knobs from params.get(...)."}},
        "required": ["code"]}}


def build_strategy_tool(args):
    """Sandbox + run an AI-written signals() strategy. Returns (summary, res, label, params)."""
    import strategy_sandbox as sb
    code = args.get("code") or ""
    name = args.get("name") or "AI strategy"
    params = dict(args.get("params") or {})
    out = sb.run_generated(code, name, params, timeout=60)   # subprocess + 60s kill
    res = out["result"]
    try:
        import store
        store.log_run("equity", "ai_generated", name, params, res)
    except Exception:
        pass
    return _result_summary(res), res, name, params


def _result_summary(res):
    """Compact numbers for the model to narrate (never the giant trade list)."""
    m, p, tr = res["metrics"], res["performance"], res["trades"]
    is_opt = bool(tr) and "pnl" in tr[0]
    s = {"strategy": res.get("strategy"), "trades": m.get("n"), "win_pct": m.get("win"),
         "total_return_pct": p.get("total_return_pct"), "max_drawdown_pct": p.get("max_drawdown_pct")}
    if is_opt:                                       # options -> Rs P&L (CAGR meaningless on a short window)
        s["total_pnl_rs"] = int(sum(t["pnl"] for t in tr))
    else:                                            # equity -> Rs net + CAGR
        if p.get("cagr_pct") is not None:
            s["cagr_pct"] = p["cagr_pct"]
        if p.get("capital_base"):
            s["net_pnl_rs"] = int(p["capital_base"] * p.get("total_return_pct", 0) / 100.0)
    # base + Rs drawdown so DD can be compared fairly across different margins
    base = p.get("margin_est") or p.get("capital_base")
    if base:
        s["margin_or_capital_rs"] = int(base)
    dd = p.get("max_drawdown_pct")
    if p.get("max_drawdown_rs") is not None:
        s["max_drawdown_rs"] = int(p["max_drawdown_rs"])
    elif base and dd is not None:
        s["max_drawdown_rs"] = int(base * dd / 100.0)
    return s


_LEG_KEYS = ("sl_pct", "tp_pct", "trail_x", "trail_y", "wait_pct")   # grid keys that apply per-leg

# Options presets as leg specs -- so a per-leg sweep (e.g. sl_pct) on a preset can be
# expanded to real legs and actually apply (otherwise the override is silently ignored).
_PRESET_LEGS = {
    "short_straddle": [("sell", "CE", "atm_point", 0), ("sell", "PE", "atm_point", 0)],
    "short_strangle": [("sell", "CE", "atm_point", 200), ("sell", "PE", "atm_point", -200)],
    "long_straddle": [("buy", "CE", "atm_point", 0), ("buy", "PE", "atm_point", 0)],
    "long_strangle": [("buy", "CE", "atm_point", 200), ("buy", "PE", "atm_point", -200)],
    "iron_butterfly": [("sell", "CE", "atm_point", 0), ("sell", "PE", "atm_point", 0),
                       ("buy", "CE", "atm_point", 200), ("buy", "PE", "atm_point", -200)],
    "straddle_width": [("sell", "CE", "width", 1), ("sell", "PE", "width", -1)],
    "short_cp": [("sell", "CE", "cp", 100), ("sell", "PE", "cp", 100)],
    "short_cp_sp": [("sell", "CE", "cp_sp", 25), ("sell", "PE", "cp_sp", 25)],
    "short_atm_pct": [("sell", "CE", "atm_pct", 1), ("sell", "PE", "atm_pct", -1)],
}


def _preset_to_legs(key):
    return [{"action": a, "type": t, "mode": m, "value": v} for (a, t, m, v) in _PRESET_LEGS.get(key, [])]


def _run_core(inst, strategy, legs, params):
    """Run one backtest. Returns (summary, res, name, key, log_params). No logging."""
    import options_engine
    import engine as eq_engine
    params = dict(params)
    if inst == "options":
        params.setdefault("lot_size", 65)
        params.setdefault("entry_time", "09:20")
        params.setdefault("exit_time", "15:15")
        params.setdefault("square_off", "one")
        if legs:                                    # custom position
            specs = [{"action": l.get("action", "sell"), "type": l.get("type", "CE"),
                      "mode": l.get("mode", "atm_point"), "value": float(l.get("value", 0)),
                      "lots": int(l.get("lots", 1)), "sl_pct": float(l.get("sl_pct", 0) or 0),
                      "tp_pct": float(l.get("tp_pct", 0) or 0),
                      "trail_x": float(l.get("trail_x", 0) or 0), "trail_y": float(l.get("trail_y", 0) or 0),
                      "wait_pct": float(l.get("wait_pct", 0) or 0),
                      "wait_dir": l.get("wait_dir", "up" if l.get("action", "sell") == "sell" else "down"),
                      "re_entry": int(l.get("re_entry", 0) or 0),
                      "re_execute": int(l.get("re_execute", 0) or 0),
                      "journey": l.get("journey")} for l in legs]
            name, key = "Custom position", "custom"
            res = options_engine.summarize_with(options_engine.custom_legs_fn(specs), name, params)
            log_params = {"legs": specs, **params}
        else:
            key = strategy or "short_straddle"
            if key not in _OPT_KEYS:
                raise ValueError("unknown options strategy '%s'" % key)
            res = options_engine.summarize(key, params)
            name = registry.get(key)["meta"]["name"]
            log_params = params
    elif inst == "equity":
        key = strategy or "ma_crossover"
        if key not in _EQ_KEYS:
            raise ValueError("unknown equity strategy '%s'" % key)
        res = eq_engine.summarize(key, params)
        name = registry.get(key)["meta"]["name"]
        log_params = params
    else:
        raise ValueError("instrument must be 'options' or 'equity'")
    return _result_summary(res), res, name, key, log_params


def run_backtest_tool(args):
    """Execute one backtest. Returns (summary_dict, full_result, label, params)."""
    inst = args.get("instrument")
    params = dict(args.get("params") or {})
    summary, res, name, key, log_params = _run_core(inst, args.get("strategy"), args.get("legs"), params)
    try:
        import store
        store.log_run(inst, key, name, log_params, res)
    except Exception:
        pass
    return summary, res, name, params


def _score(summary, rank_by):
    """Rank score from a summary dict; higher = better."""
    pnl = summary.get("total_pnl_rs", summary.get("net_pnl_rs"))
    ret = summary.get("total_return_pct")
    dd = summary.get("max_drawdown_pct")
    if rank_by == "win":
        return summary.get("win_pct") or -1e18
    if rank_by == "return":
        return ret if ret is not None else -1e18
    if rank_by == "return_mdd":
        return (ret / abs(dd)) if (ret is not None and dd) else (ret if ret is not None else -1e18)
    return pnl if pnl is not None else (ret if ret is not None else -1e18)   # default: P&L


def sweep_backtest_tool(args, cap=_SWEEP_CAP):
    """Grid-search backtests to find the best params. args: instrument, strategy|legs,
    base_params, grid {param:[values]}, rank_by, top. Returns (meta, best_res, best_label,
    best_params). Grid keys in _LEG_KEYS are applied to ALL legs (options)."""
    import itertools
    inst = args.get("instrument")
    strategy = args.get("strategy")
    legs = args.get("legs")
    base = dict(args.get("base_params") or args.get("params") or {})
    grid = args.get("grid") or {}
    rank_by = args.get("rank_by", "total_pnl")
    top = int(args.get("top", 5) or 5)
    # Sweeping a PER-LEG key on a preset (no legs) would silently no-op -- expand the
    # preset to real legs so the override actually applies.
    if not legs and strategy in _PRESET_LEGS and any(k in _LEG_KEYS for k in grid):
        legs = _preset_to_legs(strategy)
        strategy = None
    keys = list(grid)
    combos = list(itertools.product(*[grid[k] for k in keys])) if keys else [()]
    dropped = max(0, len(combos) - cap)
    combos = combos[:cap]

    rows = []
    best = None
    best_score = None
    for combo in combos:
        cd = dict(zip(keys, combo))
        params = dict(base)
        leg_over = {}
        for k, v in cd.items():
            if k in _LEG_KEYS:
                leg_over[k] = v
            else:
                params[k] = v
        these_legs = [dict(leg, **leg_over) for leg in legs] if legs else None
        try:
            summary, res, name, key, _ = _run_core(inst, strategy, these_legs, params)
        except Exception as e:
            rows.append({**cd, "error": str(e)})
            continue
        sc = _score(summary, rank_by)
        rows.append({**cd, "score": round(sc, 2) if isinstance(sc, float) else sc,
                     "pnl_rs": summary.get("total_pnl_rs", summary.get("net_pnl_rs")),
                     "return_pct": summary.get("total_return_pct"),
                     "win_pct": summary.get("win_pct"), "max_dd_pct": summary.get("max_drawdown_pct")})
        if best_score is None or (sc is not None and sc > best_score):
            best_score, best = sc, (res, name, params, cd)

    rows = [r for r in rows if "error" not in r]
    rows.sort(key=lambda r: (r.get("score") if r.get("score") is not None else -1e18), reverse=True)
    meta = {"ranked_by": rank_by, "tested": len(combos), "dropped_over_cap": dropped,
            "top": rows[:top], "best": (best[3] if best else None)}
    if best:
        res, name, params, cd = best
        try:
            import store
            store.log_run(inst, "sweep", name, params, res)
        except Exception:
            pass
        return meta, res, "%s (best of %d)" % (name, len(combos)), params
    return meta, None, "sweep", base


# --- cost meter (DEMO helper -- shows $/Rs per question; remove before demo) --
# Per-1M-token USD rates. Cache write = 1.25x input, cache read = 0.1x input.
_PRICES = {"claude-opus-4-8": (5.0, 25.0), "claude-opus-4-7": (5.0, 25.0),
           "claude-sonnet-4-6": (3.0, 15.0), "claude-haiku-4-5": (1.0, 5.0),
           "claude-fable-5": (10.0, 50.0)}
_USD_INR = 83.0


def _cost_from_usage(u, model):
    """USD cost for one API response's usage object."""
    pin, pout = _PRICES.get(model, (5.0, 25.0))
    inp = getattr(u, "input_tokens", 0) or 0
    out = getattr(u, "output_tokens", 0) or 0
    cw = getattr(u, "cache_creation_input_tokens", 0) or 0
    cr = getattr(u, "cache_read_input_tokens", 0) or 0
    usd = (inp * pin + out * pout + cw * pin * 1.25 + cr * pin * 0.10) / 1e6
    return usd, inp + cw + cr, out


def chat_agentic(history, max_rounds=4):
    """Tool-use chat: the model can call run_backtest to get REAL results. Returns
    {reply, results:[{label,res,params}], cost}. Falls back to text chat if the
    active strong provider isn't Anthropic (tool-use path is Anthropic here)."""
    picked = _pick("strong")
    if not picked or picked[0] != "anthropic":
        return {"reply": chat(history), "results": [], "cost": None}   # text-only fallback

    import anthropic
    _, cfg = picked
    client = anthropic.Anthropic(api_key=os.environ[cfg["key"]])
    system = _system_blocks()
    msgs = [{"role": m["role"], "content": m["content"]} for m in history[-20:]]
    results = []
    bt_used = [0]                       # GUARDRAIL: total engine backtests this turn
    cost = {"usd": 0.0, "in_tokens": 0, "out_tokens": 0, "llm_calls": 0, "backtests": 0}

    def _meter(usage):
        usd, ins, outs = _cost_from_usage(usage, cfg["strong"])
        cost["usd"] += usd; cost["in_tokens"] += ins; cost["out_tokens"] += outs
        cost["llm_calls"] += 1

    def _estimate_cost(name, inp):
        if name == "sweep_backtest":
            import itertools
            g = inp.get("grid") or {}
            n = 1
            for v in g.values():
                n *= max(1, len(v) if isinstance(v, list) else 1)
            return min(n, _SWEEP_CAP)
        return 1

    def _dispatch(name, inp):
        cost = _estimate_cost(name, inp)
        if bt_used[0] + cost > _TURN_BT_CAP:
            raise RuntimeError("backtest budget for this message reached (%d runs). "
                               "Ask the user to narrow the request or run fewer combos." % _TURN_BT_CAP)
        bt_used[0] += cost
        if name == "sweep_backtest":
            return sweep_backtest_tool(inp)
        if name == "build_strategy":
            return build_strategy_tool(inp)
        return run_backtest_tool(inp)

    try:
        for _ in range(max_rounds):
            resp = client.messages.create(model=cfg["strong"], max_tokens=1600, system=system,
                                          tools=[RUN_TOOL, SWEEP_TOOL, BUILD_TOOL], messages=msgs)
            _meter(resp.usage)
            if resp.stop_reason == "tool_use":
                msgs.append({"role": "assistant", "content": resp.content})
                tool_out = []
                for b in resp.content:
                    if b.type == "tool_use":
                        try:
                            summary, res, label, params = _dispatch(b.name, b.input)
                            if res is not None:
                                results.append({"label": label, "res": res, "params": params})
                            tool_out.append({"type": "tool_result", "tool_use_id": b.id,
                                             "content": json.dumps(summary)})
                        except Exception as e:
                            tool_out.append({"type": "tool_result", "tool_use_id": b.id,
                                             "content": "error: %s" % e, "is_error": True})
                msgs.append({"role": "user", "content": tool_out})
                continue
            reply = "".join(b.text for b in resp.content if b.type == "text")
            cost["backtests"] = bt_used[0]
            return {"reply": reply, "results": results, "cost": cost}
        cost["backtests"] = bt_used[0]
        return {"reply": "I ran several steps but stopped at the %d-round safety cap. "
                "Here are the results so far -- ask me to continue if needed." % max_rounds,
                "results": results, "cost": cost}
    except Exception as e:
        cost["backtests"] = bt_used[0]
        return {"reply": "AI error: %s" % e, "results": results, "cost": cost}


def chat_agentic_stream(history, sink, max_rounds=4):
    """Streaming generator: yields text as the model writes it (for st.write_stream).
    Runs the same tool loop; after it finishes, fills `sink` with results + cost so
    the caller can render result cards + the cost line. Falls back to a single
    non-streamed chunk if the strong provider isn't Anthropic."""
    picked = _pick("strong")
    if not picked or picked[0] != "anthropic":
        sink["results"] = []; sink["cost"] = None
        yield chat(history)
        return

    import anthropic
    _, cfg = picked
    client = anthropic.Anthropic(api_key=os.environ[cfg["key"]])
    system = _system_blocks()
    msgs = [{"role": m["role"], "content": m["content"]} for m in history[-20:]]
    results = []
    bt_used = [0]
    cost = {"usd": 0.0, "in_tokens": 0, "out_tokens": 0, "llm_calls": 0, "backtests": 0}

    def _meter(usage):
        usd, ins, outs = _cost_from_usage(usage, cfg["strong"])
        cost["usd"] += usd; cost["in_tokens"] += ins; cost["out_tokens"] += outs
        cost["llm_calls"] += 1

    def _estimate_cost(name, inp):
        if name == "sweep_backtest":
            import itertools  # noqa: F401
            g = inp.get("grid") or {}
            n = 1
            for v in g.values():
                n *= max(1, len(v) if isinstance(v, list) else 1)
            return min(n, _SWEEP_CAP)
        return 1

    def _dispatch(name, inp):
        c = _estimate_cost(name, inp)
        if bt_used[0] + c > _TURN_BT_CAP:
            raise RuntimeError("backtest budget for this message reached (%d runs). Narrow the request." % _TURN_BT_CAP)
        bt_used[0] += c
        if name == "sweep_backtest":
            return sweep_backtest_tool(inp)
        if name == "build_strategy":
            return build_strategy_tool(inp)
        return run_backtest_tool(inp)

    try:
        for _ in range(max_rounds):
            with client.messages.stream(model=cfg["strong"], max_tokens=1600, system=system,
                                        tools=[RUN_TOOL, SWEEP_TOOL, BUILD_TOOL], messages=msgs) as stream:
                for text in stream.text_stream:
                    yield text
                final = stream.get_final_message()
            _meter(final.usage)
            if final.stop_reason == "tool_use":
                msgs.append({"role": "assistant", "content": final.content})
                tool_out = []
                for b in final.content:
                    if b.type == "tool_use":
                        try:
                            summary, res, label, params = _dispatch(b.name, b.input)
                            if res is not None:
                                results.append({"label": label, "res": res, "params": params})
                            tool_out.append({"type": "tool_result", "tool_use_id": b.id,
                                             "content": json.dumps(summary)})
                        except Exception as e:
                            tool_out.append({"type": "tool_result", "tool_use_id": b.id,
                                             "content": "error: %s" % e, "is_error": True})
                msgs.append({"role": "user", "content": tool_out})
                continue
            break
    except Exception as e:
        yield "\n\n_(AI error: %s)_" % e
    cost["backtests"] = bt_used[0]
    sink["results"] = results
    sink["cost"] = cost
