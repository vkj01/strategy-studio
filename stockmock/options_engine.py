"""
options_engine.py -- runs leg-based options strategies on the NSE F&O tick data.

A strategy declares its LEGS relative to the ATM strike (sell/buy, CE/PE, offset).
For each trading day the engine:
  1. reads NIFTY spot at entry time -> ATM strike,
  2. picks the weekly expiry,
  3. prices each leg at entry and exit (StockMock convention: price at HH:MM:00),
  4. computes the day's P&L (fixed lot size).

Output matches the equity result shape ({metrics, performance, trades}) so the
same analytics + UI are reused. ASCII-only.
"""
import numpy as np
import pandas as pd

import options_data as od
from strategies import registry


def _dstr(d):
    return "%04d-%02d-%02d" % (d // 10000, (d // 100) % 100, d % 100)


def find_strike_by_premium(price_fn, atm, step, opt_type, target, max_steps=200):
    """Find the strike whose premium is closest to `target`, scanning either way.

    Premium is monotonic in strike: for a CE it falls going OTM (strike up) and
    rises going ITM (strike down); mirror for a PE. So we look at the ATM premium
    and walk TOWARD the target -- OTM if the ATM premium is above the target,
    ITM if it is below. Walking ITM is what lets Closest-Premium reach the
    higher-premium in-the-money strikes on low-premium (near-expiry) days, which
    is how StockMock behaves. Returns the strike, or None if no data at ATM."""
    atm_px = price_fn(atm, opt_type)
    if atm_px is None:
        return None
    otm = step if opt_type == "CE" else -step   # OTM direction lowers premium
    direction = otm if atm_px > target else -otm
    best, best_diff = atm, abs(atm_px - target)
    strike = atm
    for _ in range(max_steps):
        strike += direction
        px = price_fn(strike, opt_type)
        if px is None:                          # no data further out -> stop
            break
        diff = abs(px - target)
        if diff < best_diff:
            best_diff, best = diff, strike
        # stop once the premium has crossed through the target
        if (atm_px > target and px < target) or (atm_px <= target and px > target):
            break
    return best


def _metrics(trades):
    if not trades:
        return {"n": 0, "win": 0.0, "avgw": 0.0, "avgl": 0.0, "pf": 0.0, "exp": 0.0, "avg_bars": 1.0}
    r = np.array([t["ret_pct"] for t in trades])
    pnl = np.array([t["pnl"] for t in trades])
    wins = pnl[pnl > 0]; losses = pnl[pnl <= 0]
    pf = (wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf")
    rw = r[pnl > 0]; rl = r[pnl <= 0]
    return {"n": len(trades), "win": round(100.0 * (pnl > 0).mean(), 1),
            "avgw": round(float(rw.mean()), 2) if len(rw) else 0.0,
            "avgl": round(float(rl.mean()), 2) if len(rl) else 0.0,
            "pf": round(pf, 2) if pf != float("inf") else float("inf"),
            "exp": round(float(r.mean()), 2), "avg_bars": 1.0}


def _estimate_margin(legs, spot, lot_size, price_fn=None):
    """Rough SPAN+exposure margin for the position (NIFTY index options), used as
    the base for return/drawdown %. Hedge-aware:
      - a NAKED short leg needs ~11% of notional (spot*lot);
      - a short leg capped by a long of the SAME type (a vertical spread) is
        DEFINED-RISK, so its margin ~ spread width (pts) * lot -- far smaller;
      - a naked short CE + short PE (straddle/strangle) gets a ~23% SPAN offset;
      - a two-sided hedged book (iron fly/condor) is margined on its worst side.
    Long-only legs need just their debit (approximated at 3%). Calibrated to NIFTY
    2026 + StockMock's estimator -- an ESTIMATE, overridable via params['margin']."""
    # Futures legs: SPAN+exposure ~ a fixed % of notional per NET lot (buy/sell
    # offset -- a long+short calendar nets down). Add option legs' margin on top.
    futs = [l for l in legs if l.get("type") == "FUT"]
    if futs:
        net = abs(sum((1 if l.get("action", "buy") == "buy" else -1) * int(l.get("lots", 1))
                      for l in futs))
        gross = sum(int(l.get("lots", 1)) for l in futs)
        fut_margin = 0.12 * spot * lot_size * (net if net > 0 else gross)
        opts = [l for l in legs if l.get("type") != "FUT"]
        return round(fut_margin + (_estimate_margin(opts, spot, lot_size, price_fn) if opts else 0), 0)
    shorts = [l for l in legs if l.get("action", "sell") == "sell"]
    longs = [l for l in legs if l.get("action", "sell") == "buy"]
    if not shorts:
        # Long-only: capital required = the premium DEBIT actually paid, which is
        # how StockMock margins a bought position -- not a % of notional. Use the
        # real entry premiums when available; fall back to a rough 3% otherwise.
        if price_fn is not None:
            debit = sum((price_fn(int(l["strike"]), l["type"]) or 0.0)
                        * lot_size * int(l.get("lots", 1)) for l in legs)
            if debit > 0:
                return round(debit, 0)
        units = sum(int(l.get("lots", 1)) for l in legs)
        return round(0.03 * spot * lot_size * units, 0)

    scan = 0.06 * spot                            # ~SPAN price-scan range for NIFTY

    def side_margin(typ):
        s = [l for l in shorts if l["type"] == typ]
        if not s:
            return 0.0
        units = sum(int(l.get("lots", 1)) for l in s)
        naked = 0.11 * spot * lot_size * units
        hedges = [l for l in longs if l["type"] == typ]
        if hedges:
            # A hedged short side (vertical spread) is margined at ~half the naked
            # side's SPAN for typical spreads, rising toward the full naked value as
            # the long wing widens and stops protecting. Calibrated to StockMock
            # June-2026: bear call spreads 100/200/400-wide all ~Rs25k (~0.5x
            # naked side * 0.77). (An estimate -- exact SPAN needs exchange files.)
            sk = s[0]["strike"]
            width = min(abs(int(l["strike"]) - int(sk)) for l in hedges)
            frac = 0.5 + 0.5 * max(0.0, min((width - 400) / (scan * 2.0), 1.0))
            return naked * 0.77 * frac
        return naked                              # naked short

    m_ce, m_pe = side_margin("CE"), side_margin("PE")
    if m_ce > 0 and m_pe > 0:                     # two-sided short book
        if not longs:
            return round((m_ce + m_pe) * 0.77, 0)   # naked straddle/strangle SPAN benefit
        # Hedged both sides (iron fly / condor). StockMock does NOT collapse this to
        # the tiny defined-risk width -- it margins at ~0.49x the NAKED straddle for
        # typical (tight) wings, rising toward the naked value as the wings widen and
        # stop protecting. Calibrated to SM June-2026: 100/200/300-wide fly all ~Rs49k
        # (~0.49x naked ~Rs100k, flat under 300pt); CP~5 far hedge ~0.57x (~Rs1.5L).
        def _naked(typ):
            u = sum(int(l.get("lots", 1)) for l in shorts if l["type"] == typ)
            return 0.11 * spot * lot_size * u
        naked_straddle = (_naked("CE") + _naked("PE")) * 0.77
        widths = [abs(int(l["strike"]) - int(s["strike"]))
                  for s in shorts for l in longs if l["type"] == s["type"]]
        width = min(widths) if widths else 0
        frac = 0.49 + 0.51 * max(0.0, min((width - 300) / (scan * 1.1), 1.0))
        return round(naked_straddle * frac, 0)
    return round(m_ce + m_pe, 0)


def _perf(trades, base):
    """Equity + %-metrics on a fixed `base` (margin). Matches StockMock:
    total return % = total P&L / base; max drawdown % = worst peak-to-trough of
    cumulative P&L (in Rs) / base."""
    if not trades:
        return {"equity_curve": [], "final_equity": base, "total_return_pct": 0.0,
                "max_drawdown_pct": 0.0, "max_drawdown_rs": 0.0, "cagr_pct": 0.0}
    ts = sorted(trades, key=lambda t: t["exit_date"])
    cum = 0.0; peak = 0.0; max_dd_rs = 0.0
    curve = []
    for t in ts:
        cum += t["pnl"]
        peak = max(peak, cum)
        if cum - peak < max_dd_rs:
            max_dd_rs = cum - peak                # <= 0, in Rs
        curve.append({"date": t["exit_date"], "equity": round(base + cum, 2)})
    first = pd.Timestamp(ts[0]["exit_date"]); last = pd.Timestamp(ts[-1]["exit_date"])
    years = max((last - first).days / 365.25, 1e-9)
    final = base + cum
    cagr = (final / base) ** (1 / years) - 1 if final > 0 and base > 0 else -1.0
    return {"equity_curve": curve, "final_equity": round(final, 2),
            "total_return_pct": round(100.0 * cum / base, 2) if base else 0.0,
            "max_drawdown_pct": round(100.0 * max_dd_rs / base, 2) if base else 0.0,
            "max_drawdown_rs": round(max_dd_rs, 0),
            "cagr_pct": round(100.0 * cagr, 2)}


def resolve_strike(ctx, mode, value, opt_type):
    """Resolve a leg's strike from a strike-selection mode + value.
       atm_point: value = signed points; atm_pct: signed %; width: signed x SP;
       cp: target premium; cp_sp: % of straddle premium."""
    atm, spot, step = ctx["atm"], ctx["spot"], ctx["step"]
    if mode == "atm_point":
        return int(atm + round(value / step) * step)
    if mode == "atm_pct":
        return int(round(spot * (1 + value / 100.0) / step) * step)
    if mode == "width":
        return int(atm + round(value * ctx["straddle_premium"] / step) * step)
    if mode == "cp":
        return ctx["find_by_premium"](opt_type, float(value))
    if mode == "cp_sp":
        return ctx["find_by_premium"](opt_type, ctx["straddle_premium"] * value / 100.0)
    return atm


def custom_legs_fn(specs):
    """Build a legs() fn from UI leg specs. A leg carries its own exit rules:
    sl_pct, tp_pct, and a StockMock-style step-trail (trail_x/trail_y)."""
    def legs(ctx, params):
        out = []
        for s in specs:
            strike = resolve_strike(ctx, s["mode"], float(s.get("value", 0)), s["type"])
            if strike is not None:
                out.append({"type": s["type"], "action": s["action"],
                            "strike": int(strike), "lots": int(s.get("lots", 1)),
                            "sl_pct": float(s.get("sl_pct", 0) or 0),
                            "tp_pct": float(s.get("tp_pct", 0) or 0),
                            "trail_x": float(s.get("trail_x", 0) or 0),
                            "trail_y": float(s.get("trail_y", 0) or 0),
                            "wait_pct": float(s.get("wait_pct", 0) or 0),
                            "wait_dir": str(s.get("wait_dir", "up")),
                            "re_entry": int(s.get("re_entry", 0) or 0),
                            "re_execute": int(s.get("re_execute", 0) or 0),
                            "journey": s.get("journey")})
        return out
    return legs


def _hhmm_add(t, mins):
    tot = int(t[:2]) * 60 + int(t[3:5]) + mins
    return "%02d:%02d" % (tot // 60, tot % 60)


def _minute_grid(a, b):
    """['HH:MM', ...] every minute from a to b inclusive (drives the day loop, so
    legs added mid-day -- Journey adjustments -- are still processed)."""
    cur, end = int(a[:2]) * 60 + int(a[3:5]), int(b[:2]) * 60 + int(b[3:5])
    out = []
    while cur <= end:
        out.append("%02d:%02d" % (cur // 60, cur % 60))
        cur += 1
    return out


def range_breakout_entry(date, entry_t, exit_t, rb_minutes):
    """StockMock Range Breakout: build the NIFTY spot range over the first
    `rb_minutes` from entry_t, then return the first minute after that window
    where spot breaks above the range high or below the low. None -> no trade."""
    ser = [(t, p) for (t, p) in od.spot_series(date) if entry_t <= t <= exit_t]
    if not ser:
        return None
    win_end = _hhmm_add(entry_t, int(rb_minutes))
    rng = [p for (t, p) in ser if t <= win_end]
    if not rng:
        return None
    hi, lo = max(rng), min(rng)
    for t, p in ser:
        if t <= win_end:
            continue
        if p > hi or p < lo:
            return t
    return None


def _sim_day(date, expiry, legs, entry_t, exit_t, lot_size, params):
    """Minute-by-minute simulation of the WHOLE position for one day. All the
    StockMock-style features hang off this:
      - per-leg SL % / Target % (on 1-min high/low)
      - per-leg step-trail: every trail_x% favorable move shifts SL by trail_y%
      - per-leg Wait & Trade: delay a leg's entry until its premium moves wait_pct%
        in the wait_dir; the leg trades from that minute (skipped if never hit)
      - per-leg Re-Entry (re_entry): after an SL, re-open the same leg up to N times
      - per-leg Re-Execute (re_execute): after a Target, re-open up to N times
      - Move SL to Cost: when one leg's SL fires, survivors' SL jumps to entry
      - Square Off All: first trigger closes the rest at that minute
      - Strategy Target / Stop in Total MTM (Rs), marked each minute
    A leg can fill several times a day (re-entry), so this returns ONE row per FILL:
    [[leg, entry_px, exit_px, exit_t, reason], ...] or None. Marks use the 1-min
    candle open; SL/target triggers use the 1-min high/low."""
    strat_tp = float(params.get("target_mtm", 0) or 0)      # Rs, whole strategy
    strat_sl = float(params.get("sl_mtm", 0) or 0)          # Rs, whole strategy
    sq_all = str(params.get("square_off", "one")) == "all"
    move_cost = bool(params.get("move_sl_to_cost", False))
    no_reentry = str(params.get("no_reentry_after") or "")  # HH:MM; "" = never blocks
    # Protect The Profits: once MTM peak >= p_if, lock a profit floor p_lock; every
    # p_every of further peak profit raises the floor by p_add. Exit if MTM falls to the floor.
    p_if = float(params.get("protect_if", 0) or 0)
    p_lock = float(params.get("protect_lock", 0) or 0)
    p_every = float(params.get("protect_every", 0) or 0)
    p_add = float(params.get("protect_lock_add", 0) or 0)
    protect_on = p_if > 0
    peak = 0.0
    day_cap = None                                          # set to +/-threshold on a strategy stop/target/protect
    n = len(legs)
    idx = str(params.get("symbol", "NIFTY")).upper()        # index for option/spot lookups

    # Range Breakout: build the spot range over [entry_t, entry_t+rb_minutes], then
    # each leg enters on its directional break -- PE when spot breaks ABOVE the high,
    # CE when it breaks BELOW the low (StockMock convention). A side that never breaks
    # simply doesn't trade. Limited by our 1-min spot (StockMock uses ticks).
    rb = bool(params.get("range_breakout"))
    rb_hi = rb_lo = None
    rb_ready = ""
    spot_min = {}
    if rb:
        sser = [(t, p) for (t, p) in od.spot_series(date, idx) if entry_t <= t <= exit_t]
        spot_min = dict(sser)
        rb_ready = _hhmm_add(entry_t, int(params.get("rb_minutes", 8)))
        rng = [p for (t, p) in sser if t <= rb_ready]
        if rng:
            rb_hi, rb_lo = max(rng), min(rng)

    def _ref_series(leg):
        """Entry price + 1-min OHLC series for a leg -- a future (type 'FUT') is
        priced from the near-month futures series; an option from its contract."""
        if leg.get("type") == "FUT":
            sym = leg.get("symbol", "NIFTY")
            ref = od.future_price_at(date, entry_t, sym)
            raw = od.future_series(date, sym)
        else:
            ref = od.option_price_at(date, expiry, leg["strike"], leg["type"], entry_t, idx)
            raw = od.option_series(date, expiry, leg["strike"], leg["type"], idx)
        return ref, raw

    st, series = [], []
    for leg in legs:
        ref, raw = _ref_series(leg)
        if ref is None:
            return None
        s = {t: (o, h, l) for (t, o, h, l) in raw if entry_t <= t <= exit_t}
        series.append(s)
        st.append({
            "leg": leg, "is_sell": leg["action"] == "sell",
            "lots": int(leg.get("lots", 1)), "ref": ref,
            "sl": float(leg.get("sl_pct", 0) or 0) / 100.0,
            "tp": float(leg.get("tp_pct", 0) or 0) / 100.0,
            "tx": float(leg.get("trail_x", 0) or 0),
            "ty": float(leg.get("trail_y", 0) or 0),
            "wait": float(leg.get("wait_pct", 0) or 0) / 100.0,
            "wdir": str(leg.get("wait_dir", "up")),
            "re_sl": int(leg.get("re_entry", 0) or 0),
            "re_tp": int(leg.get("re_execute", 0) or 0),
            "started": False, "open": False, "entry": None,
            "best": ref, "mark": ref, "sl_lvl": None, "tp_lvl": None,
            "journey": leg.get("journey"), "journey_fired": False,
            "pending": None,                                # armed re-entry: {kind, level}
            "rb_dir": ("up" if leg["type"] == "PE" else "down") if rb else None,
            "fills": []})                                   # (entry, exit, exit_t, reason)

    def activate(i, e):
        s = st[i]
        s["started"] = True; s["open"] = True; s["entry"] = e
        s["best"] = e; s["mark"] = e
        sl, tp, sell = s["sl"], s["tp"], s["is_sell"]
        s["sl_lvl"] = (e * (1 + sl) if sell else e * (1 - sl)) if sl else None
        s["tp_lvl"] = (e * (1 - tp) if sell else e * (1 + tp)) if tp else None

    for i in range(len(st)):                                      # enter now unless waiting (W&T) or range-breakout
        if st[i]["wait"] <= 0 and st[i]["rb_dir"] is None:
            activate(i, st[i]["ref"])

    def close(i, px, t, reason):
        st[i]["fills"].append((st[i]["entry"], px, t, reason))
        st[i]["open"] = False

    def close_all(t, reason):
        for i in range(len(st)):
            if st[i]["open"]:
                close(i, st[i]["mark"], t, reason)

    def mtm_bounds(t):
        """Intra-minute (worst, best) combined MTM in Rs. StockMock triggers a
        strategy stop/target on the worst/best tick WITHIN the minute, not the
        candle open -- so we bound it with the 1-min high/low. The move is
        underlying-DIRECTIONAL: either spot went up (CE at its high, PE at its
        low) or down (CE low, PE high) within the minute. We can't credit both
        legs' favorable extreme at once (a straddle can't have both premiums dip
        on the same tick), so BOTH bounds come from these two directional
        scenarios: worst = min(up, down), best = max(up, down). Realized (closed
        fills) is fixed and added to both."""
        realized = up = down = 0.0
        for i in range(len(st)):
            s = st[i]
            sign = 1.0 if s["is_sell"] else -1.0
            for en, ex, _tt, _rn in s["fills"]:
                realized += sign * (en - ex) * s["lots"] * lot_size
            if not s["open"]:
                continue
            v = series[i].get(t)
            hi = lo = s["mark"] if v is None else None
            if v is not None:
                _o, hi, lo = v
            # a future moves WITH spot, so it behaves like a CE for the up/down bound
            up_side = s["leg"]["type"] in ("CE", "FUT")
            p_up, p_dn = (hi, lo) if up_side else (lo, hi)   # spot up vs down
            q = s["lots"] * lot_size
            up += sign * (s["entry"] - p_up) * q
            down += sign * (s["entry"] - p_dn) * q
        return realized + min(up, down), realized + max(up, down)

    def spawn_journey(parent_i, t):
        """Journey: on the parent leg's SL, enter a configurable adjustment leg
        (action/type/ATM-offset/SL) resolved at the trigger minute."""
        j = st[parent_i]["journey"]
        sp = od.spot_at(date, t, idx)
        if sp is None:
            return
        stp = od.index_step(idx)
        atm = od.atm_strike(sp, stp)
        strike = int(atm + round(float(j.get("value", 0)) / stp) * stp)
        e = od.option_price_at(date, expiry, strike, j["type"], t, idx)
        if e is None:
            return
        leg = {"type": j["type"], "action": j.get("action", "sell"), "strike": strike,
               "lots": st[parent_i]["lots"], "sl_pct": float(j.get("sl_pct", 0) or 0),
               "tp_pct": 0, "trail_x": 0, "trail_y": 0, "wait_pct": 0,
               "re_entry": 0, "re_execute": 0, "journey": None}
        legs.append(leg)
        series.append({tt: (o, h, l) for (tt, o, h, l) in
                       od.option_series(date, expiry, strike, j["type"], idx) if t <= tt <= exit_t})
        sl = leg["sl_pct"] / 100.0
        st.append({
            "leg": leg, "is_sell": leg["action"] == "sell", "lots": leg["lots"], "ref": e,
            "sl": sl, "tp": 0.0, "tx": 0.0, "ty": 0.0, "wait": 0.0, "wdir": "up",
            "re_sl": 0, "re_tp": 0, "started": False, "open": False, "entry": None,
            "best": e, "mark": e, "sl_lvl": None, "tp_lvl": None,
            "journey": None, "journey_fired": True, "pending": None,
            "rb_dir": None, "fills": []})
        activate(len(st) - 1, e)

    minutes = _minute_grid(entry_t, exit_t)

    for t in minutes:
        for i in range(len(st)):                                  # refresh marks
            if st[i]["started"] and st[i]["open"]:
                v = series[i].get(t)
                if v is not None:
                    st[i]["mark"] = v[0]

        for i in range(len(st)):                                  # Wait & Trade entries
            s = st[i]
            if s["started"] or s["wait"] <= 0:                    # only legs with a real W&T %
                continue
            v = series[i].get(t)
            if v is None:
                continue
            o, h, l = v
            up, dn = s["ref"] * (1 + s["wait"]), s["ref"] * (1 - s["wait"])
            if s["wdir"] == "up" and h >= up:
                activate(i, up)
            elif s["wdir"] == "down" and l <= dn:
                activate(i, dn)

        if rb and rb_hi is not None and t > rb_ready:       # Range Breakout entries
            sp = spot_min.get(t)
            if sp is not None:
                for i in range(len(st)):
                    s = st[i]
                    if s["started"] or s["rb_dir"] is None:
                        continue
                    if (s["rb_dir"] == "up" and sp > rb_hi) or (s["rb_dir"] == "down" and sp < rb_lo):
                        v = series[i].get(t)
                        activate(i, v[0] if v is not None else s["mark"])

        for i in range(len(st)):                            # Re-Entry(SL)/Re-Execute(TP): fill when premium RETURNS to original entry
            s = st[i]
            pend = s["pending"]
            if pend is None or s["open"] or not s["started"]:
                continue
            v = series[i].get(t)
            if v is None:
                continue
            o = v[0]
            lvl = pend["level"]
            if pend["kind"] == "sl":                         # sold higher then came back / bought lower then came back
                back = (o <= lvl) if s["is_sell"] else (o >= lvl)
            else:                                           # re-execute after a target
                back = (o >= lvl) if s["is_sell"] else (o <= lvl)
            if back and not (no_reentry and t >= no_reentry):
                s["re_sl" if pend["kind"] == "sl" else "re_tp"] -= 1
                s["pending"] = None
                activate(i, o)                              # re-enter at the market (candle open)

        just = []
        for i in range(len(st)):
            s = st[i]
            if not (s["started"] and s["open"]):
                continue
            v = series[i].get(t)
            if v is None:
                continue
            o, h, l = v
            if s["tx"] > 0 and s["ty"] > 0:                 # step-trail the SL
                if s["is_sell"]:
                    s["best"] = min(s["best"], l)
                    fav = (s["entry"] - s["best"]) / s["entry"] * 100.0
                    steps = int(fav // s["tx"]) if fav > 0 else 0
                    base = s["entry"] * (1 + s["sl"]) if s["sl"] else s["entry"]
                    lvl = base - steps * (s["ty"] / 100.0) * s["entry"]
                    s["sl_lvl"] = lvl if s["sl_lvl"] is None else min(s["sl_lvl"], lvl)
                else:
                    s["best"] = max(s["best"], h)
                    fav = (s["best"] - s["entry"]) / s["entry"] * 100.0
                    steps = int(fav // s["tx"]) if fav > 0 else 0
                    base = s["entry"] * (1 - s["sl"]) if s["sl"] else s["entry"]
                    lvl = base + steps * (s["ty"] / 100.0) * s["entry"]
                    s["sl_lvl"] = lvl if s["sl_lvl"] is None else max(s["sl_lvl"], lvl)
            if s["sl_lvl"] is not None and (
                    (s["is_sell"] and h >= s["sl_lvl"]) or ((not s["is_sell"]) and l <= s["sl_lvl"])):
                close(i, s["sl_lvl"], t, "sl"); just.append((i, "sl")); continue
            if s["tp_lvl"] is not None and (
                    (s["is_sell"] and l <= s["tp_lvl"]) or ((not s["is_sell"]) and h >= s["tp_lvl"])):
                close(i, s["tp_lvl"], t, "target"); just.append((i, "target")); continue

        if just:
            if sq_all and any(st[i]["open"] for i in range(len(st))):
                close_all(t, "square_off"); break
            if move_cost and any(r == "sl" for _i, r in just):
                for i in range(len(st)):                          # survivors -> breakeven
                    if st[i]["started"] and st[i]["open"]:
                        st[i]["sl_lvl"] = st[i]["entry"]
            for i, reason in just:                          # ARM Re-Entry(SL)/Re-Execute(TP): re-fill later when premium returns to entry
                if reason == "sl" and st[i]["re_sl"] > 0 and st[i]["pending"] is None:
                    st[i]["pending"] = {"kind": "sl", "level": st[i]["fills"][-1][0]}
                elif reason == "target" and st[i]["re_tp"] > 0 and st[i]["pending"] is None:
                    st[i]["pending"] = {"kind": "tp", "level": st[i]["fills"][-1][0]}
            for i, reason in just:                          # Journey: adjust on SL (immediate)
                if (reason == "sl" and st[i]["journey"] and not st[i]["journey_fired"]
                        and not (no_reentry and t >= no_reentry)):
                    st[i]["journey_fired"] = True
                    spawn_journey(i, t)

        if strat_tp > 0 or strat_sl > 0 or protect_on:     # whole-strategy MTM
            worst, best = mtm_bounds(t)
            if strat_sl > 0 and worst <= -strat_sl:
                close_all(t, "strat_sl"); day_cap = -strat_sl; break   # book at threshold
            if strat_tp > 0 and best >= strat_tp:
                close_all(t, "strat_target"); day_cap = strat_tp; break
            if protect_on:                                  # Protect The Profits (profit trail)
                peak = max(peak, best)
                if peak >= p_if:
                    locked = p_lock + (int((peak - p_if) // p_every) * p_add if p_every > 0 else 0.0)
                    if worst <= locked:
                        close_all(t, "protect"); day_cap = locked; break

        if (not any(st[i]["open"] for i in range(len(st)))
                and not any(not st[i]["started"] for i in range(len(st)))
                and not any(st[i]["pending"] for i in range(len(st)))):
            break

    for i in range(len(st)):                                      # survivors exit at time
        if st[i]["started"] and st[i]["open"]:
            lg = legs[i]
            if lg.get("type") == "FUT":
                px = od.future_price_at(date, exit_t, lg.get("symbol", "NIFTY"))
            else:
                px = od.option_price_at(date, expiry, lg["strike"], lg["type"], exit_t, idx)
            close(i, px if px is not None else st[i]["mark"], exit_t, "time")

    res = [[st[i]["leg"], en, ex, tt, rn]
           for i in range(len(st)) for (en, ex, tt, rn) in st[i]["fills"]]
    if not res:
        return None
    return res, day_cap


def summarize(strategy_key, params):
    strat = registry.get(strategy_key)
    # a strategy may pin engine-level flags (e.g. Expiry Day -> expiry_only); the
    # user's params still win if they set the same key explicitly.
    fixed = strat["meta"].get("fixed_params")
    if fixed:
        params = {**fixed, **params}
    return summarize_with(strat["legs"], strat["meta"]["name"], params)


def summarize_with(legs_fn, name, params):
    lot_size = int(params.get("lot_size", 25))
    entry_t = str(params.get("entry_time", "09:20"))
    exit_t = str(params.get("exit_time", "15:15"))
    capital = float(params.get("capital", 100000))
    margin_override = float(params.get("margin", 0) or 0)   # 0 = auto-estimate
    margin_est = None
    slip = float(params.get("slippage_pct", 0) or 0) / 100.0  # per fill side, % of premium
    cost_lot = float(params.get("cost_per_lot", 0) or 0)      # Rs round-trip per lot per leg-fill
    symbol = str(params.get("symbol", "NIFTY")).upper()       # index: NIFTY / BANKNIFTY / MIDCPNIFTY
    expiry_type = str(params.get("expiry_type", "weekly"))    # weekly | monthly
    step = od.index_step(symbol)

    all_days = od.available_days(symbol)                    # full list (for expiry offsets)
    days = list(all_days)
    if params.get("start"):
        s = int(str(params["start"]).replace("-", "")); days = [d for d in days if d >= s]
    if params.get("end"):
        e = int(str(params["end"]).replace("-", "")); days = [d for d in days if d <= e]
    wd = params.get("weekdays")                              # e.g. {0,1,2,3,4} Mon-Fri
    if wd:
        wd = set(wd)
        days = [d for d in days if pd.Timestamp(_dstr(d)).weekday() in wd]
    # Expiry-relative day filter: keep only days that sit `expiry_offset` TRADING days
    # before their week's expiry (0 = the expiry day itself, DTE 0). Enabled by
    # expiry_only or by passing expiry_offset. `d` is YYYYMMDD, weekly_expiry returns
    # YYMMDD, so we map each expiry back to its full trading day for the position math.
    if params.get("expiry_only") or params.get("expiry_offset") is not None:
        eo = int(params.get("expiry_offset", 0) or 0)
        posf = {d: i for i, d in enumerate(all_days)}
        exp_full = {}                                       # YYMMDD expiry -> full YYYYMMDD day
        for d in all_days:
            exp_full[int(str(d)[2:])] = d
        def _keep(d):
            e = od.expiry_for(d, symbol, expiry_type)
            if e is None:
                return False
            E = exp_full.get(int(e))
            return E is not None and (posf[E] - posf[d]) == eo
        days = [d for d in days if _keep(d)]

    trades = []
    for d in days:
        expiry = od.expiry_for(d, symbol, expiry_type)
        if expiry is None:
            continue
        # Strikes always resolve at entry_t (09:22). Range Breakout only delays each
        # leg's EXECUTION to its spot-break, handled per-leg inside _sim_day.
        spot = od.spot_at(d, entry_t, symbol)
        if spot is None:
            continue
        # "Use Futures as ATM": resolve the ATM off the near-month future instead of
        # spot (StockMock toggle). The future trades at a small premium to spot, so
        # this can shift the ATM strike by a step on some days.
        atm_ref = spot
        if params.get("use_futures_atm"):
            fp = od.future_price_at(d, entry_t, params.get("fut_symbol", symbol))
            if fp is not None:
                atm_ref = fp
        atm = od.atm_strike(atm_ref, step)

        def price_fn(strike, typ, D=d, E=expiry, S=symbol):
            return od.option_price_at(D, E, strike, typ, entry_t, S)

        atm_ce = price_fn(atm, "CE") or 0.0
        atm_pe = price_fn(atm, "PE") or 0.0
        ctx = {"atm": atm, "spot": spot, "step": step,
               "premium": price_fn,
               "straddle_premium": atm_ce + atm_pe,
               "find_by_premium": (lambda typ, target, pf=price_fn, a=atm, st=step:
                                   find_strike_by_premium(pf, a, st, typ, target))}

        legs = legs_fn(ctx, params)
        if not legs:
            continue
        if margin_est is None:
            margin_est = _estimate_margin(legs, spot, lot_size, price_fn)
        out = _sim_day(d, expiry, legs, entry_t, exit_t, lot_size, params)
        if not out:
            continue
        exits, day_cap = out
        # brokerage/taxes: flat Rs per lot, per leg-fill (round-trip)
        brokerage = cost_lot * sum(leg.get("lots", 1) for leg, *_ in exits)
        if day_cap is not None:                              # strategy stop/target booked at the MTM threshold
            pnl = float(day_cap) - brokerage
        else:
            pnl_pts = 0.0
            for leg, e_px, x_px, x_time, reason in exits:
                is_sell = leg["action"] == "sell"
                # slippage always fills against you: sell lower / buy back higher (and vice-versa)
                ee = e_px * (1 - slip) if is_sell else e_px * (1 + slip)
                xe = x_px * (1 + slip) if is_sell else x_px * (1 - slip)
                sign = 1.0 if is_sell else -1.0
                pnl_pts += sign * (ee - xe) * leg.get("lots", 1)
            pnl = pnl_pts * lot_size - brokerage
        ds = _dstr(d)
        trades.append({"symbol": symbol, "date": ds, "entry_date": ds, "exit_date": ds,
                       "atm": atm, "expiry": expiry, "pnl": round(pnl, 0),
                       "outcome": "win" if pnl > 0 else "loss"})

    # On the expiry day SPAN margin roughly halves (positions expire same session,
    # so far less overnight risk). StockMock reports this "On Expiry" margin, ~0.49x
    # the normal estimate -- apply it for expiry-only strategies. (calibrated: naked
    # straddle June 2026 = Rs48,498 on-expiry vs ~Rs98,622 normal.)
    if params.get("expiry_only") and margin_est:
        margin_est = round(margin_est * 0.49, 0)
    # base for all % = margin (StockMock convention): user override, else estimate.
    base = margin_override if margin_override > 0 else (margin_est or capital)
    for t in trades:
        t["ret"] = t["pnl"] / base if base else 0.0
        t["ret_pct"] = round(100.0 * t["ret"], 3)

    out = [{"date": t["date"], "entry_date": t["entry_date"], "exit_date": t["exit_date"],
            "expiry": t["expiry"], "atm": t["atm"], "pnl": t["pnl"],
            "ret_pct": t["ret_pct"], "outcome": t["outcome"]}
           for t in trades]
    perf = _perf(trades, base)
    perf["capital_base"] = round(base, 0)
    perf["margin_est"] = round(margin_est or 0, 0)
    return {"strategy": name, "metrics": _metrics(trades),
            "performance": perf, "trades": out, "_trades_full": trades}


# ============================================================================
# POSITIONAL (multi-day) engine -- a SEPARATE path from the intraday one above.
# Enter a leg-based position ONCE, hold the SAME contracts across trading days,
# and exit when a rule fires (total-MTM target / stop, max hold days, or expiry).
# Exits are checked on ONE snapshot per day (at check_time) -- cheap over long
# holds, close to how positional traders actually monitor. Overnight risk means
# NO same-day expiry margin discount (we use the full _estimate_margin). Positions
# are sequential (non-overlapping): the next one opens the trading day after the
# last exits, so a monthly hold naturally rolls to the next month. ASCII-only.
# ============================================================================
def _price_leg(date, expiry, leg, hhmm, symbol):
    """Price one leg (option or FUT) at a given day+time, or None if no data."""
    if leg.get("type") == "FUT":
        return od.future_price_at(date, hhmm, leg.get("symbol", symbol))
    return od.option_price_at(date, expiry, leg["strike"], leg["type"], hhmm, symbol)


def summarize_positional(legs_fn, name, params):
    """Multi-day hold of a leg-based position. See the section header above."""
    lot_size = int(params.get("lot_size", 25))
    entry_t = str(params.get("entry_time", "09:20"))
    check_t = str(params.get("check_time", params.get("exit_time", "15:15")))
    capital = float(params.get("capital", 100000))
    margin_override = float(params.get("margin", 0) or 0)
    slip = float(params.get("slippage_pct", 0) or 0) / 100.0
    cost_lot = float(params.get("cost_per_lot", 0) or 0)
    symbol = str(params.get("symbol", "NIFTY")).upper()
    expiry_type = str(params.get("expiry_type", "monthly"))
    step = od.index_step(symbol)
    max_hold = int(params.get("max_hold_days", 0) or 0)     # 0 = hold till expiry
    tgt_mtm = float(params.get("target_mtm", 0) or 0)        # Rs, whole position
    sl_mtm = float(params.get("sl_mtm", 0) or 0)             # Rs, whole position

    days = list(od.available_days(symbol))
    if params.get("start"):
        s = int(str(params["start"]).replace("-", "")); days = [d for d in days if d >= s]
    if params.get("end"):
        e = int(str(params["end"]).replace("-", "")); days = [d for d in days if d <= e]
    N = len(days)

    trades = []
    margin_est = None
    i = 0
    while i < N:
        d = days[i]
        expiry = od.expiry_for(d, symbol, expiry_type)
        if expiry is None:
            i += 1; continue
        # need at least one night: skip entry on the expiry day itself (0-day hold),
        # roll to the next day (which picks the next expiry).
        if int(str(d)[2:]) >= int(expiry):
            i += 1; continue
        spot = od.spot_at(d, entry_t, symbol)
        if spot is None:
            i += 1; continue
        atm_ref = spot
        if params.get("use_futures_atm"):
            fp = od.future_price_at(d, entry_t, params.get("fut_symbol", symbol))
            if fp is not None:
                atm_ref = fp
        atm = od.atm_strike(atm_ref, step)

        def entry_price_fn(strike, typ, D=d, E=expiry, S=symbol):
            return od.option_price_at(D, E, strike, typ, entry_t, S)

        atm_ce = entry_price_fn(atm, "CE") or 0.0
        atm_pe = entry_price_fn(atm, "PE") or 0.0
        ctx = {"atm": atm, "spot": spot, "step": step, "premium": entry_price_fn,
               "straddle_premium": atm_ce + atm_pe,
               "find_by_premium": (lambda typ, target, pf=entry_price_fn, a=atm, stp=step:
                                   find_strike_by_premium(pf, a, stp, typ, target))}
        legs = legs_fn(ctx, params)
        if not legs:
            i += 1; continue

        entries, ok = [], True
        for leg in legs:
            epx = _price_leg(d, expiry, leg, entry_t, symbol)
            if epx is None:
                ok = False; break
            entries.append(epx)
        if not ok:
            i += 1; continue
        if margin_est is None:                              # FULL overnight margin (no expiry discount)
            margin_est = _estimate_margin(legs, spot, lot_size, entry_price_fn)

        # hold forward, one snapshot per day at check_t, until an exit rule fires.
        # We only ever price days at/before this contract's expiry; the "expiry"
        # exit fires on the LAST trading day <= expiry (which need not equal the
        # stored expiry date -- it may be a holiday), never on a post-expiry day.
        last_px = list(entries)
        exit_day, exit_px, reason, held = None, None, None, 0
        j = i
        while j < N:
            cd = days[j]
            if int(str(cd)[2:]) > int(expiry):              # safety: never price past expiry
                break
            cur = []
            for k, leg in enumerate(legs):
                px = _price_leg(cd, expiry, leg, check_t, symbol)
                cur.append(px if px is not None else last_px[k])  # carry forward if a day is missing
            last_px = cur
            mtm = 0.0
            for k, leg in enumerate(legs):
                sign = 1.0 if leg.get("action", "sell") == "sell" else -1.0
                mtm += sign * (entries[k] - cur[k]) * int(leg.get("lots", 1)) * lot_size
            held = j - i                                    # 0 on entry day
            next_rolls_past = (j + 1 < N) and (int(str(days[j + 1])[2:]) > int(expiry))
            data_ends = (j + 1 >= N)
            if tgt_mtm and mtm >= tgt_mtm:
                reason = "target"
            elif sl_mtm and mtm <= -sl_mtm:
                reason = "stop"
            elif max_hold and held >= max_hold:
                reason = "max_days"
            elif next_rolls_past:                           # last day at/before expiry
                reason = "expiry"
            elif data_ends:                                 # dataset ends mid-hold
                reason = "data_end"
            if reason:
                exit_day, exit_px = cd, cur
                break
            j += 1
        if exit_day is None:                                # shouldn't happen; safety net
            exit_day, exit_px, reason = days[min(j, N - 1)], last_px, "data_end"

        pnl_pts = 0.0
        for k, leg in enumerate(legs):
            is_sell = leg.get("action", "sell") == "sell"
            ee = entries[k] * (1 - slip) if is_sell else entries[k] * (1 + slip)
            xe = exit_px[k] * (1 + slip) if is_sell else exit_px[k] * (1 - slip)
            sign = 1.0 if is_sell else -1.0
            pnl_pts += sign * (ee - xe) * int(leg.get("lots", 1))
        brokerage = cost_lot * sum(int(leg.get("lots", 1)) for leg in legs)
        pnl = pnl_pts * lot_size - brokerage
        ed, xd = _dstr(d), _dstr(exit_day)
        trades.append({"symbol": symbol, "date": xd, "entry_date": ed, "exit_date": xd,
                       "atm": atm, "expiry": expiry, "pnl": round(pnl, 0),
                       "hold_days": held, "reason": reason,
                       "outcome": "win" if pnl > 0 else "loss"})
        # next position opens the trading day AFTER this one exits (sequential, no overlap)
        i = days.index(exit_day) + 1

    base = margin_override if margin_override > 0 else (margin_est or capital)
    for t in trades:
        t["ret"] = t["pnl"] / base if base else 0.0
        t["ret_pct"] = round(100.0 * t["ret"], 3)
    out = [{"date": t["date"], "entry_date": t["entry_date"], "exit_date": t["exit_date"],
            "expiry": t["expiry"], "atm": t["atm"], "pnl": t["pnl"], "ret_pct": t["ret_pct"],
            "hold_days": t["hold_days"], "reason": t["reason"], "outcome": t["outcome"]}
           for t in trades]
    perf = _perf(trades, base)
    perf["capital_base"] = round(base, 0)
    perf["margin_est"] = round(margin_est or 0, 0)
    return {"strategy": name, "metrics": _metrics(trades),
            "performance": perf, "trades": out, "_trades_full": trades}
