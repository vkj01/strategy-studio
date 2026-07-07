"""
Strategy Studio -- StockMock-style backtesting UI (our own design).

Same idea (pick a strategy, fill its variables, backtest, see results) but our
own branding, colours, and layout -- driven entirely by each strategy's
variable schema, so new strategies appear automatically with their own form.

Run:  streamlit run app.py
"""
import datetime as dt

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import analytics
import engine
import options_data
import options_engine
import store
from strategies import registry


def _int_to_date(v):
    """YYYYMMDD int (e.g. 20260330) -> datetime.date."""
    s = str(int(v))
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))

import branding  # noqa: E402
branding.inject_css()
branding.hero("Backtest", "Pick a strategy, set the variables, and test it on real market data.")

_STRIKE_MODES = {"ATM Point": "atm_point", "ATM Percent": "atm_pct",
                 "Straddle Width": "width", "Closest Premium (CP)": "cp",
                 "CP based on Straddle Premium (SP)": "cp_sp"}
_VAL_HELP = {"atm_point": "signed points (e.g. -100, +200)", "atm_pct": "signed % (e.g. -1, +1)",
             "width": "x straddle premium (e.g. 1, -1)", "cp": "target premium (e.g. 100)",
             "cp_sp": "% of straddle premium (e.g. 25)"}


# Predefined options strategies -> builder pre-fills (StockMock model: picking a
# strategy just seeds the same builder). Each leg = (action, type, mode, value).
_MODE_LABEL = {v: k for k, v in _STRIKE_MODES.items()}
PRESETS = {
    "short_straddle": [("sell", "CE", "atm_point", 0), ("sell", "PE", "atm_point", 0)],
    "short_strangle": [("sell", "CE", "atm_point", 200), ("sell", "PE", "atm_point", -200)],
    "long_straddle":  [("buy", "CE", "atm_point", 0), ("buy", "PE", "atm_point", 0)],
    "long_strangle":  [("buy", "CE", "atm_point", 200), ("buy", "PE", "atm_point", -200)],
    "iron_butterfly": [("sell", "CE", "atm_point", 0), ("sell", "PE", "atm_point", 0),
                       ("buy", "CE", "atm_point", 200), ("buy", "PE", "atm_point", -200)],
    "straddle_width": [("sell", "CE", "width", 1), ("sell", "PE", "width", -1)],
    "short_cp":       [("sell", "CE", "cp", 100), ("sell", "PE", "cp", 100)],
    "short_cp_sp":    [("sell", "CE", "cp_sp", 25), ("sell", "PE", "cp_sp", 25)],
    "short_atm_pct":  [("sell", "CE", "atm_pct", 1), ("sell", "PE", "atm_pct", -1)],
    "expiry_day":     [("sell", "CE", "atm_point", 0), ("sell", "PE", "atm_point", 0)],
    "bear_call_spread": [("sell", "CE", "atm_point", -50), ("buy", "CE", "atm_point", 50)],
    "bear_put_spread":  [("buy", "PE", "atm_point", 50), ("sell", "PE", "atm_point", -50)],
    "bull_call_spread": [("buy", "CE", "atm_point", -50), ("sell", "CE", "atm_point", 50)],
    "bull_put_spread":  [("sell", "PE", "atm_point", 50), ("buy", "PE", "atm_point", -50)],
    "iron_condor":    [("sell", "CE", "atm_point", 50), ("buy", "CE", "atm_point", 100),
                       ("sell", "PE", "atm_point", -50), ("buy", "PE", "atm_point", -100)],
}


def render_custom_builder(preset=None, kp="cust"):
    """StockMock-style position builder. `preset` (list of (action,type,mode,value))
    seeds the legs when a predefined strategy is chosen; `kp` keys the widgets so
    switching strategy re-seeds cleanly. Returns (specs, params)."""
    preset = preset or [("sell", "CE", "atm_point", 0), ("sell", "PE", "atm_point", 0)]
    modes = list(_STRIKE_MODES)

    # Leg COUNT stays OUTSIDE the form so the rows redraw the moment you change it.
    # Everything else is in a st.form and only applies on "Run Backtest" -> no lag while typing.
    st.markdown("###### Positions")
    nlegs = st.number_input("Number of legs", 1, 6, len(preset), step=1, key=kp + "_n",
                            help="Add/remove legs here (updates live). All other fields apply when you hit Run.")

    with st.form(kp + "_form", border=False):
        s = st.columns(7)
        # BANKNIFTY has no weeklies -> lock the Expiry dropdown to Monthly for it.
        cur_idx = st.session_state.get(kp + "_idx", "NIFTY")
        exp_opts = ["Monthly"] if cur_idx == "BANKNIFTY" else ["Weekly", "Monthly"]
        if cur_idx == "BANKNIFTY":
            st.session_state[kp + "_exp"] = "Monthly"       # keep the widget value valid
        index = s[0].selectbox("Index", ["NIFTY", "BANKNIFTY", "MIDCPNIFTY"], key=kp + "_idx",
                               help="BANKNIFTY has monthly expiry only (no weeklies).")
        entry = s[1].text_input("Entry time", "09:20", key=kp + "_ent")
        exit_t = s[2].text_input("Exit time", "15:15", key=kp + "_ext")
        lot_size = s[3].number_input("Lot size", 1, 200, 65, step=1, key=kp + "_ls")
        expiry_type = s[4].selectbox("Expiry", exp_opts, key=kp + "_exp")
        square = s[5].selectbox("Square off", ["One Leg", "All Legs"], key=kp + "_sq")
        margin = s[6].number_input("Margin (Rs)", 0, 10000000, 0, step=10000, key=kp + "_mg",
                                   help="Base for return/drawdown %. 0 = auto-estimate "
                                        "(SPAN+exposure). Set your broker/StockMock margin to match.")
        use_fut_atm = st.checkbox("Use Futures as ATM", key=kp + "_ufa",
                                  help="Resolve the ATM off the near-month future price instead of "
                                       "spot (StockMock toggle). Can shift the ATM a step on some days.")

        # per-leg table. Common controls inline; advanced ones tuck into a per-leg popover.
        widths = [0.5, 0.85, 1.4, 0.85, 0.75, 0.9, 0.95, 1.05]
        hdr = st.columns(widths)
        for lbl, col in zip(["Lots", "Action", "Strike mode", "Value", "Type",
                             "SL %", "Target %", "More"], hdr):
            col.markdown("**%s**" % lbl)
        specs = []
        for i in range(int(nlegs)):
            d = preset[i] if i < len(preset) else ("sell", "CE" if i % 2 == 0 else "PE", "atm_point", 0)
            d_act, d_typ, d_mode, d_val = d
            c = st.columns(widths)
            lots = c[0].number_input("l", 1, 50, 1, key="%s_l%d" % (kp, i), label_visibility="collapsed")
            action = c[1].selectbox("a", ["sell", "buy"], index=0 if d_act == "sell" else 1,
                                    key="%s_a%d" % (kp, i), label_visibility="collapsed")
            mode_l = c[2].selectbox("m", modes, index=modes.index(_MODE_LABEL[d_mode]),
                                    key="%s_m%d" % (kp, i), label_visibility="collapsed")
            mode = _STRIKE_MODES[mode_l]
            vstep = 50.0 if mode in ("atm_point", "cp") else 1.0
            value = c[3].number_input("v", value=float(d_val), step=vstep,
                                      key="%s_v%d" % (kp, i), label_visibility="collapsed")
            typ = c[4].selectbox("t", ["CE", "PE"], index=0 if d_typ == "CE" else 1,
                                 key="%s_t%d" % (kp, i), label_visibility="collapsed")
            sl = c[5].number_input("sl", 0.0, 500.0, 0.0, step=5.0, key="%s_s%d" % (kp, i), label_visibility="collapsed")
            tp = c[6].number_input("tp", 0.0, 500.0, 0.0, step=5.0, key="%s_tp%d" % (kp, i), label_visibility="collapsed")
            with c[7].popover("⚙ Edit"):
                st.caption("Leg %d — Trail / Wait&Trade / Re-Entry / Journey" % (i + 1))
                tx = st.number_input("Trail: every X %", 0.0, 500.0, 0.0, step=1.0, key="%s_tx%d" % (kp, i))
                ty = st.number_input("...move SL by Y %", 0.0, 500.0, 0.0, step=1.0, key="%s_ty%d" % (kp, i))
                wt = st.number_input("Wait & Trade %", 0.0, 500.0, 0.0, step=1.0, key="%s_wt%d" % (kp, i),
                                     help="Wait to enter until the option moves this % (sell after a pop, buy after a dip).")
                re_e = st.number_input("Re-Entry after SL (times)", 0, 10, 0, step=1, key="%s_re%d" % (kp, i))
                re_x = st.number_input("Re-Execute after Target (times)", 0, 10, 0, step=1, key="%s_rx%d" % (kp, i))
                j_act = st.selectbox("Journey adj action (blank=off)", ["off", "sell", "buy"], key="%s_ja%d" % (kp, i),
                                     help="Journey: when THIS leg's SL fires, enter an adjustment leg. 'off' = no journey.")
                j_typ = st.selectbox("Journey adj type", ["CE", "PE"], index=0 if d_typ == "CE" else 1, key="%s_jt%d" % (kp, i))
                j_val = st.number_input("Journey adj ATM offset (pts)", -2000.0, 2000.0, 0.0, step=50.0, key="%s_jv%d" % (kp, i))
                j_sl = st.number_input("Journey adj SL %", 0.0, 500.0, 0.0, step=5.0, key="%s_js%d" % (kp, i))
                journey = None if j_act == "off" else {"action": j_act, "type": j_typ, "value": j_val, "sl_pct": j_sl}
            specs.append({"action": action, "type": typ, "mode": mode, "value": value, "lots": lots,
                          "sl_pct": sl, "tp_pct": tp, "trail_x": tx, "trail_y": ty,
                          "wait_pct": wt, "wait_dir": "up" if action == "sell" else "down",
                          "re_entry": int(re_e), "re_execute": int(re_x), "journey": journey})
        st.caption("**Value** depends on each leg's mode -- ATM Point: signed points - ATM Percent: "
                   "signed % - Straddle Width: x straddle premium - CP: target premium - CP-SP: % of SP. "
                   "**More**: per-leg step-trail, Wait & Trade, Re-Entry, Re-Execute, Journey.")

        st.markdown("###### Strategy exits & filters")
        e = st.columns(4)
        tgt_mtm = e[0].number_input("Target Profit (Rs, Total MTM)", 0, 10000000, 0, step=500, key=kp + "_tgt")
        sl_mtm = e[1].number_input("Stop Loss (Rs, Total MTM)", 0, 10000000, 0, step=500, key=kp + "_slm")
        move_cost = e[2].checkbox("Move SL to Cost", key=kp + "_mvc",
                                  help="When one leg's SL is hit, move surviving legs' SL to entry (breakeven).")
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri"]
        days_sel = e[3].multiselect("Trade only on", day_names, default=day_names, key=kp + "_dow")
        weekdays = [day_names.index(x) for x in days_sel]

        ef = st.columns([1.3, 1.5, 3.2])
        expiry_only = ef[0].checkbox("Expiry days only", key=kp + "_exo",
                                     help="Trade only on the weekly-expiry-relative day (see offset).")
        expiry_off = ef[1].number_input("Days before expiry", 0, 4, 0, step=1, key=kp + "_exoff",
                                        help="0 = expiry day itself (DTE 0), 1 = the trading day before, up to 4.")

        rb_cols = st.columns([1.3, 1.2, 1.4, 1.4])
        range_bo = rb_cols[0].checkbox("Range Breakout", key=kp + "_rb",
                                       help="Build the opening spot range over the first N minutes, then enter "
                                            "when spot breaks it (PE on up-break, CE on down-break).")
        rb_minutes = rb_cols[1].number_input("Range minutes", 1, 240, 8, step=1, key=kp + "_rbm",
                                             help="Range = entry to entry+this. StockMock default 09:22->09:30 = 8.")
        no_re = rb_cols[2].checkbox("Cutoff re-entry/journey", key=kp + "_nr",
                                    help="After the cutoff time, stops just close (no re-entry / journey).")
        no_re_t = rb_cols[3].text_input("Cutoff (HH:MM)", "15:00", key=kp + "_nrt")

        st.markdown("###### Protect the Profits (strategy profit-trail)")
        pp = st.columns(4)
        protect_if = pp[0].number_input("Once profit reaches (Rs)", 0, 10000000, 0, step=500, key=kp + "_pif",
                                        help="0 = off. When total MTM profit crosses this, lock a floor.")
        protect_lock = pp[1].number_input("Lock profit (Rs)", 0, 10000000, 0, step=500, key=kp + "_plk")
        protect_every = pp[2].number_input("Then every (Rs)", 0, 10000000, 0, step=500, key=kp + "_pev",
                                           help="Optional trail: for every this-much more profit...")
        protect_add = pp[3].number_input("...raise lock by (Rs)", 0, 10000000, 0, step=500, key=kp + "_pad")

        st.markdown("###### Costs")
        cc = st.columns(4)
        slippage = cc[0].number_input("Slippage % (per fill)", 0.0, 5.0, 0.0, step=0.05, key=kp + "_slp",
                                      help="Against you on every fill (sell lower, buy-back higher). 0.05-0.1% realistic.")
        cost_lot = cc[1].number_input("Cost / lot (Rs, round-trip)", 0, 2000, 0, step=10, key=kp + "_cpl",
                                      help="Flat brokerage + taxes per lot, per leg, round-trip. ~Rs 40-60/lot typical.")

        # tell the user exactly how much history exists for THIS index, and clamp
        # the pickers to it so a wrong range can't be entered by mistake. (Even so,
        # the engine only runs the days that actually exist inside the chosen range.)
        span = options_data.data_span(cur_idx)
        lo = hi = None
        if span:
            lo, hi = _int_to_date(span[0]), _int_to_date(span[1])
            st.caption("Data available for **%s**: **%s -> %s**  (%d trading days). "
                       "Pick within this range."
                       % (cur_idx, lo.strftime("%d %b %Y"), hi.strftime("%d %b %Y"), span[2]))
        limit = st.checkbox("Limit to a date range", key=kp + "_dr")
        dd = st.columns(2)
        from_d = dd[0].date_input("From", value=lo, min_value=lo, max_value=hi, key=kp + "_from")
        to_d = dd[1].date_input("To", value=hi, min_value=lo, max_value=hi, key=kp + "_to")

        run = st.form_submit_button("Run Backtest", type="primary")

    start = from_d.isoformat() if limit else None
    end = to_d.isoformat() if limit else None
    params = {"lot_size": int(lot_size), "entry_time": entry, "exit_time": exit_t,
              "margin": int(margin), "start": start, "end": end,
              "symbol": index, "expiry_type": expiry_type.lower(),
              "square_off": "all" if square == "All Legs" else "one",
              "target_mtm": int(tgt_mtm), "sl_mtm": int(sl_mtm),
              "move_sl_to_cost": bool(move_cost),
              "weekdays": weekdays if len(weekdays) < 5 else None,
              "expiry_only": bool(expiry_only),
              "expiry_offset": int(expiry_off) if expiry_only else None,
              "use_futures_atm": bool(use_fut_atm),
              "range_breakout": bool(range_bo), "rb_minutes": int(rb_minutes),
              "no_reentry_after": (no_re_t or None) if no_re else None,
              "slippage_pct": float(slippage), "cost_per_lot": int(cost_lot),
              "protect_if": int(protect_if), "protect_lock": int(protect_lock),
              "protect_every": int(protect_every), "protect_lock_add": int(protect_add)}
    return specs, params, run




def render_positional_builder(preset=None, kp="pos"):
    """StockMock-style POSITIONAL builder: a leg-based position held across days.
    Trimmed vs the intraday builder -- no per-leg intraday SL/trail/journey/wait;
    instead the whole position exits on total-MTM target/stop, max-hold days, or
    expiry (checked once per day). Returns (specs, params, run)."""
    preset = preset or [("sell", "CE", "atm_point", 0), ("sell", "PE", "atm_point", 0)]
    modes = list(_STRIKE_MODES)
    leg_types = ["CE", "PE", "FUT"]

    st.markdown("###### Positions (entered once, held across days)")
    nlegs = st.number_input("Number of legs", 1, 6, len(preset), step=1, key=kp + "_n",
                            help="FUT legs hold a future overnight -- use point/percent strike modes for those.")

    with st.form(kp + "_form", border=False):
        s = st.columns(6)
        cur_idx = st.session_state.get(kp + "_idx", "NIFTY")
        exp_opts = ["Monthly"] if cur_idx == "BANKNIFTY" else ["Monthly", "Weekly"]
        if cur_idx == "BANKNIFTY":
            st.session_state[kp + "_exp"] = "Monthly"
        index = s[0].selectbox("Index", ["NIFTY", "BANKNIFTY", "MIDCPNIFTY"], key=kp + "_idx",
                               help="BANKNIFTY has monthly expiry only.")
        entry = s[1].text_input("Entry time", "09:20", key=kp + "_ent")
        check = s[2].text_input("Check time", "15:15", key=kp + "_chk",
                                help="Time of day the position is marked each day for the exit checks "
                                     "(one snapshot per day).")
        expiry_type = s[3].selectbox("Expiry", exp_opts, key=kp + "_exp",
                                     help="Positional usually holds the MONTHLY contract.")
        lot_size = s[4].number_input("Lot size", 1, 200, 65, step=1, key=kp + "_ls")
        margin = s[5].number_input("Margin (Rs)", 0, 10000000, 0, step=10000, key=kp + "_mg",
                                   help="Base for return/drawdown %. 0 = auto-estimate FULL overnight "
                                        "margin (no same-day expiry discount).")

        widths = [0.6, 1.0, 1.7, 1.0, 0.9]
        hdr = st.columns(widths)
        for lbl, col in zip(["Lots", "Action", "Strike mode", "Value", "Type"], hdr):
            col.markdown("**%s**" % lbl)
        specs = []
        for i in range(int(nlegs)):
            d = preset[i] if i < len(preset) else ("sell", "CE" if i % 2 == 0 else "PE", "atm_point", 0)
            d_act, d_typ, d_mode, d_val = d
            c = st.columns(widths)
            lots = c[0].number_input("l", 1, 50, 1, key="%s_l%d" % (kp, i), label_visibility="collapsed")
            action = c[1].selectbox("a", ["sell", "buy"], index=0 if d_act == "sell" else 1,
                                    key="%s_a%d" % (kp, i), label_visibility="collapsed")
            mode_l = c[2].selectbox("m", modes, index=modes.index(_MODE_LABEL[d_mode]),
                                    key="%s_m%d" % (kp, i), label_visibility="collapsed")
            mode = _STRIKE_MODES[mode_l]
            vstep = 50.0 if mode in ("atm_point", "cp") else 1.0
            value = c[3].number_input("v", value=float(d_val), step=vstep,
                                      key="%s_v%d" % (kp, i), label_visibility="collapsed")
            typ = c[4].selectbox("t", leg_types, index=leg_types.index(d_typ) if d_typ in leg_types else 0,
                                 key="%s_t%d" % (kp, i), label_visibility="collapsed")
            specs.append({"action": action, "type": typ, "mode": mode, "value": value, "lots": lots})
        st.caption("Legs are entered once and HELD. **Value** depends on each leg's strike mode. "
                   "**FUT** = hold a future (use point/percent modes).")

        st.markdown("###### Exit rules (whole position, checked once per day at Check time)")
        e = st.columns(3)
        max_hold = e[0].number_input("Max hold (trading days)", 0, 60, 0, step=1, key=kp + "_mh",
                                     help="0 = hold until the contract's expiry.")
        tgt = e[1].number_input("Target profit (Rs, total MTM)", 0, 10000000, 0, step=1000, key=kp + "_tgt",
                                help="Exit when combined profit reaches this. 0 = off.")
        sl = e[2].number_input("Stop loss (Rs, total MTM)", 0, 10000000, 0, step=1000, key=kp + "_sl",
                               help="Exit when combined loss reaches this. 0 = off.")

        st.markdown("###### Costs")
        cc = st.columns(2)
        slippage = cc[0].number_input("Slippage % (per fill)", 0.0, 5.0, 0.0, step=0.05, key=kp + "_slp",
                                      help="Against you on entry and exit fills.")
        cost_lot = cc[1].number_input("Cost / lot (Rs, round-trip)", 0, 2000, 0, step=10, key=kp + "_cpl")

        span = options_data.data_span(cur_idx)
        lo = hi = None
        if span:
            lo, hi = _int_to_date(span[0]), _int_to_date(span[1])
            st.caption("Data available for **%s**: **%s -> %s**  (%d trading days). Pick within this range."
                       % (cur_idx, lo.strftime("%d %b %Y"), hi.strftime("%d %b %Y"), span[2]))
        limit = st.checkbox("Limit to a date range", key=kp + "_dr")
        dd = st.columns(2)
        from_d = dd[0].date_input("From", value=lo, min_value=lo, max_value=hi, key=kp + "_from")
        to_d = dd[1].date_input("To", value=hi, min_value=lo, max_value=hi, key=kp + "_to")

        run = st.form_submit_button("Run Backtest", type="primary")

    start = from_d.isoformat() if limit else None
    end = to_d.isoformat() if limit else None
    params = {"lot_size": int(lot_size), "entry_time": entry, "check_time": check,
              "margin": int(margin), "start": start, "end": end,
              "symbol": index, "expiry_type": expiry_type.lower(),
              "max_hold_days": int(max_hold), "target_mtm": int(tgt), "sl_mtm": int(sl),
              "slippage_pct": float(slippage), "cost_per_lot": int(cost_lot)}
    return specs, params, run


# --- strategy selection bar (top, horizontal -- not a left list) --------------
top = st.columns([1.3, 2.2, 3])
with top[0]:
    instrument = st.segmented_control("Instrument", ["Equity", "Options", "Futures", "Positional"],
                                      default="Equity", key="instr") or "Equity"
# Positional reuses the OPTIONS strategy catalogue (same leg shapes -- just held
# across multiple days instead of squared off intraday).
menu_inst = "options" if instrument == "Positional" else instrument.lower()
metas = registry.list_meta(instrument=menu_inst)
leg_based = instrument in ("Options", "Positional")
CUSTOM = "Custom (build your own)"
is_custom = False
with top[1]:
    if metas:
        names = ([CUSTOM] + [m["name"] for m in metas]) if leg_based else [m["name"] for m in metas]
        chosen = st.selectbox("Strategy", names, label_visibility="visible")
        if chosen == CUSTOM:
            meta, is_custom = None, True
        else:
            meta = next(m for m in metas if m["name"] == chosen)
    else:
        meta = None
        st.selectbox("Strategy", ["(none yet)"], disabled=True)
with top[2]:
    if instrument == "Positional":
        st.caption(" ")
        st.caption("Multi-day hold: enter once, hold the same contracts across days, "
                   "exit on target / stop / max-hold days / expiry.")
    elif meta:
        st.caption(" ")
        st.caption(meta["description"])
    elif is_custom:
        st.caption(" ")
        st.caption("Build any multi-leg position: pick legs, strike mode, buy/sell.")

if meta is None and not is_custom:
    st.info("No strategies for this instrument yet.")
    st.stop()


# --- variable form (auto-rendered from the schema) ----------------------------
def render_form(meta):
    params = {}
    plain = [(n, s) for n, s in meta["variables"].items() if s["type"] != "date"]
    st.markdown("##### Variables")
    cols = st.columns(3)
    for i, (name, spec) in enumerate(plain):
        col = cols[i % 3]
        label = spec.get("label", name)
        default = spec.get("default")
        if spec["type"] == "int":
            params[name] = col.number_input(label, value=int(default or 0),
                min_value=int(spec.get("min", 0)), max_value=int(spec.get("max", 10**6)), step=1)
        elif spec["type"] == "float":
            params[name] = col.number_input(label, value=float(default or 0.0),
                min_value=float(spec.get("min", 0)), max_value=float(spec.get("max", 10**6)), step=0.5)
        elif spec["type"] == "select":
            opts = spec["options"]
            params[name] = col.selectbox(label, opts,
                index=opts.index(default) if default in opts else 0)
        elif spec["type"] == "time":
            params[name] = col.text_input(label, value=str(default))

    # date window (handled together, with a toggle)
    if any(s["type"] == "date" for s in meta["variables"].values()):
        lo, hi = _equity_span()
        if lo and hi:
            st.caption("Equity data available: **%s -> %s**. Pick within this range."
                       % (lo.strftime("%d %b %Y"), hi.strftime("%d %b %Y")))
        limit = st.checkbox("Limit to a date range", value=False)
        if limit:
            d1, d2 = st.columns(2)
            params["start"] = d1.date_input("From", value=lo, min_value=lo, max_value=hi).isoformat()
            params["end"] = d2.date_input("To", value=hi, min_value=lo, max_value=hi).isoformat()
        else:
            params["start"] = params["end"] = None
    return params


@st.cache_data(ttl=600, show_spinner=False)
def _equity_span():
    """(from_date, to_date) covered by the equity daily store, for the date hint."""
    try:
        s = engine.datastore.status()
        return (dt.date.fromisoformat(s["from"]), dt.date.fromisoformat(s["to"]))
    except Exception:
        return (None, None)


with st.container(border=True):
    if instrument == "Positional":                           # multi-day hold builder
        preset = None if is_custom else PRESETS.get(meta["key"])
        kp = "pos" if is_custom else ("pos_" + meta["key"])
        specs, params, run = render_positional_builder(preset=preset, kp=kp)
    elif is_custom:
        specs, params, run = render_custom_builder(kp="cust")
    elif meta and meta.get("instrument") == "options":
        # predefined options strategy -> seed the SAME builder (StockMock model)
        specs, params, run = render_custom_builder(preset=PRESETS.get(meta["key"]), kp=meta["key"])
    else:
        specs = None
        params = render_form(meta)                           # equity keeps its schema form
        run = st.button("Run Backtest", type="primary")


# --- results ------------------------------------------------------------------
def _monthly_table(monthly):
    if not monthly:
        st.info("Not enough history for a monthly breakdown.")
        return
    mdf = pd.DataFrame(monthly)
    mdf["year"] = mdf["month"].str[:4]
    mdf["mon"] = mdf["month"].str[5:7].astype(int)
    pivot = mdf.pivot(index="year", columns="mon", values="ret_pct")
    names = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
             7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
    ann = mdf.groupby("year")["ret_pct"].apply(
        lambda s: (np.prod(1 + s / 100.0) - 1) * 100).round(1)
    pivot = pivot.rename(columns=names)
    pivot["Year"] = ann
    mon_cols = [c for c in pivot.columns if c != "Year"]
    try:
        sty = (pivot.style.format("{:.1f}", na_rep="")
               .background_gradient(cmap="RdYlGn", vmin=-8, vmax=8, subset=mon_cols))
        st.dataframe(sty, use_container_width=True)
    except Exception:
        st.dataframe(pivot, use_container_width=True)
    st.caption("Monthly % returns; the **Year** column is the compounded annual return.")


def _monthly_bars(monthly):
    if not monthly:
        return
    mdf = pd.DataFrame(monthly)
    chart = (alt.Chart(mdf).mark_bar().encode(
        x=alt.X("month:N", title=None, axis=alt.Axis(labelAngle=-90)),
        y=alt.Y("ret_pct:Q", title="Monthly %"),
        color=alt.condition(alt.datum.ret_pct >= 0, alt.value("#16A34A"), alt.value("#E74C3C")),
        tooltip=["month", "ret_pct"]).properties(height=240))
    st.altair_chart(chart, use_container_width=True)


def _render_streaks(a):
    ws, ls = a.get("win_streak_dist", {}), a.get("loss_streak_dist", {})
    if not ws and not ls:
        return
    with st.expander("Winning & losing streaks"):
        col1, col2 = st.columns(2)
        col1.markdown("**Winning streaks**")
        if ws:
            col1.dataframe(pd.DataFrame([{"Length": k, "Times": v} for k, v in sorted(ws.items())]),
                           hide_index=True, use_container_width=True)
        col2.markdown("**Losing streaks**")
        if ls:
            col2.dataframe(pd.DataFrame([{"Length": k, "Times": v} for k, v in sorted(ls.items())]),
                           hide_index=True, use_container_width=True)


def render_results(res, params=None, name="strategy"):
    m, p = res["metrics"], res["performance"]
    base = p.get("capital_base") or 100000
    a = analytics.compute(res, capital=base)
    net = base * p["total_return_pct"] / 100.0
    st.markdown("### Results")
    _download_row(res, params, name)             # download at the TOP

    r1 = st.columns(4)
    r1[0].metric("Net P&L", _rs(net))
    r1[1].metric("CAGR", "%.1f%%" % p["cagr_pct"])
    r1[2].metric("Total return", "%.1f%%" % p["total_return_pct"])
    r1[3].metric("Max drawdown", "%.1f%%" % p["max_drawdown_pct"])

    r2 = st.columns(4)
    r2[0].metric("Win rate", "%.1f%%" % m["win"])
    r2[1].metric("Profit factor", ("%.2f" % m["pf"]) if m["pf"] != float("inf") else "inf")
    r2[2].metric("Trades", "%d" % m["n"])
    r2[3].metric("Return / MDD", ("%.2f" % a["return_mdd_ratio"]) if a["return_mdd_ratio"] is not None else "-")

    r3 = st.columns(4)
    r3[0].metric("Expectancy", "%.2f%%" % a["expectancy"])
    r3[1].metric("Avg win", "%.1f%%" % a["avg_win"])
    r3[2].metric("Avg loss", "%.1f%%" % a["avg_loss"])
    r3[3].metric("Max win / loss streak", "%d / %d" % (a["max_win_streak"], a["max_loss_streak"]))

    rec = a["recovery"]
    rec_txt = ("%d days%s" % (rec["days"], " (running)" if rec["running"] else "")) if rec else "-"
    st.caption("Best trade **+%.1f%%** · Worst **%.1f%%** · Wins/Losses **%d / %d** · MDD recovery **%s** · "
               "on **%s** capital: final **%s**, worst dip **%s**"
               % (a["best"], a["worst"], a["wins"], a["losses"], rec_txt,
                  _rs(base), _rs(a["final_value"]), _rs(a["mdd_value"])))

    _render_streaks(a)

    tabs = st.tabs(["Equity curve", "Drawdown", "Monthly returns", "Trade log"])
    with tabs[0]:
        if p["equity_curve"]:
            eq = pd.DataFrame(p["equity_curve"]); eq["date"] = pd.to_datetime(eq["date"])
            st.line_chart(eq.set_index("date"), y="equity", height=340, color="#5B4FE9")
        else:
            st.info("No trades were generated for these variables.")
    with tabs[1]:
        if a["drawdown_series"]:
            dd = pd.DataFrame(a["drawdown_series"]); dd["date"] = pd.to_datetime(dd["date"])
            st.area_chart(dd.set_index("date"), y="dd_pct", height=280, color="#E74C3C")
            st.caption("Underwater curve -- how far below the running peak, in %.")
        else:
            st.info("No drawdown data.")
    with tabs[2]:
        _monthly_bars(a["monthly"])
        _monthly_table(a["monthly"])
    with tabs[3]:
        if res["trades"]:
            st.dataframe(pd.DataFrame(res["trades"]), use_container_width=True, height=380)
        else:
            st.info("No trades.")


def _rs(x):
    return "Rs %s" % "{:,}".format(int(round(x)))


def _download_row(res, params, name):
    """Excel/PDF download buttons at the TOP of the results (StockMock-style). Stable
    keys because results now persist + re-render on every rerun."""
    if not (res.get("trades") and params is not None):
        return
    import report_export
    safe = "".join(ch if ch.isalnum() else "_" for ch in name)[:40] or "strategy"
    c = st.columns([1.1, 1.1, 4])
    try:
        c[0].download_button("Download Excel", report_export.build_excel(res, params, name),
                             file_name="backtest_%s.xlsx" % safe, key="dl_xl",
                             mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             use_container_width=True)
    except Exception as e:
        c[0].caption("Excel export unavailable: %s" % e)
    try:
        c[1].download_button("Download PDF", report_export.build_pdf(res, params, name),
                             file_name="backtest_%s.pdf" % safe, key="dl_pdf",
                             mime="application/pdf", use_container_width=True)
    except Exception as e:
        c[1].caption("PDF export unavailable: %s" % e)


def render_options_results(res, params=None, name="strategy"):
    trades, p, m = res["trades"], res["performance"], res["metrics"]
    base = p.get("capital_base") or 100000
    a = analytics.compute(res, capital=base)
    pnls = [t["pnl"] for t in trades]
    total = sum(pnls)
    avg_day = total / len(pnls) if pnls else 0
    best = max(pnls) if pnls else 0
    worst = min(pnls) if pnls else 0
    rmdd = (p["total_return_pct"] / abs(p["max_drawdown_pct"])) if p["max_drawdown_pct"] else None
    pf = ("%.2f" % m["pf"]) if m["pf"] != float("inf") else "inf"
    win_p = [x for x in pnls if x > 0]
    loss_p = [x for x in pnls if x <= 0]
    avg_win = sum(win_p) / len(win_p) if win_p else 0
    avg_loss = sum(loss_p) / len(loss_p) if loss_p else 0
    est = p.get("margin_est") or base
    dd_rs = p.get("max_drawdown_rs")
    loss_pct = 100.0 - m["win"]

    st.markdown("### Results")
    _download_row(res, params, name)             # download at the TOP (like StockMock)

    # rich, StockMock-style stat grid (16 cards)
    r1 = st.columns(4)
    r1[0].metric("Total P&L", _rs(total))
    r1[1].metric("Total return", "%.2f%%" % p["total_return_pct"])
    r1[2].metric("Win days", "%.0f%% (%d)" % (m["win"], a["wins"]))
    r1[3].metric("Loss days", "%.0f%% (%d)" % (loss_pct, a["losses"]))

    r2 = st.columns(4)
    r2[0].metric("Estimated margin", _rs(est))
    r2[1].metric("Avg P&L / day", _rs(avg_day))
    r2[2].metric("Max profit day", _rs(best))
    r2[3].metric("Max loss day", _rs(worst))

    r3 = st.columns(4)
    r3[0].metric("Avg on win days", _rs(avg_win))
    r3[1].metric("Avg on loss days", _rs(avg_loss))
    r3[2].metric("Max drawdown", "%.2f%%" % p["max_drawdown_pct"])
    r3[3].metric("Max DD (Rs)", _rs(dd_rs) if dd_rs is not None else "-")

    r4 = st.columns(4)
    r4[0].metric("Profit factor", pf)
    r4[1].metric("Return / MDD", ("%.2f" % rmdd) if rmdd else "-")
    r4[2].metric("Max win streak", "%d" % a["max_win_streak"])
    r4[3].metric("Max loss streak", "%d" % a["max_loss_streak"])

    st.caption("Return & drawdown %% are on **%s** margin · expectancy **%.3f%% / day** "
               "· **%d** trading days" % (_rs(est), m["exp"], m["n"]))
    _render_streaks(a)

    tabs = st.tabs(["Cumulative P&L", "Drawdown", "Per-day P&L", "Day of week", "Monthly", "Trade log"])
    with tabs[0]:
        if p["equity_curve"]:
            eq = pd.DataFrame(p["equity_curve"]); eq["date"] = pd.to_datetime(eq["date"])
            st.line_chart(eq.set_index("date"), y="equity", height=320, color="#5B4FE9")
    with tabs[1]:
        if a["drawdown_series"]:
            dd = pd.DataFrame(a["drawdown_series"]); dd["date"] = pd.to_datetime(dd["date"])
            st.area_chart(dd.set_index("date"), y="dd_pct", height=280, color="#E74C3C")
    with tabs[2]:
        if trades:
            df = pd.DataFrame(trades)
            chart = (alt.Chart(df).mark_bar().encode(
                x=alt.X("date:N", title=None, axis=alt.Axis(labelAngle=-90)),
                y=alt.Y("pnl:Q", title="P&L (Rs)"),
                color=alt.condition(alt.datum.pnl >= 0, alt.value("#16A34A"), alt.value("#E74C3C")),
                tooltip=["date", "atm", "pnl", "outcome"]).properties(height=280))
            st.altair_chart(chart, use_container_width=True)
    with tabs[3]:
        if trades:
            df = pd.DataFrame(trades)
            df["dow"] = pd.to_datetime(df["date"]).dt.day_name()
            order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
            dow = df.groupby("dow")["pnl"].sum().reindex(order).dropna()
            st.bar_chart(dow, height=260, color="#5B4FE9")
            st.caption("Total P&L by weekday.")
    with tabs[4]:
        if trades:
            df = pd.DataFrame(trades)
            df["month"] = pd.to_datetime(df["date"]).dt.strftime("%b %Y")
            mon = df.groupby("month", sort=False)["pnl"].agg(["sum", "count"])
            mon.columns = ["P&L (Rs)", "Days"]
            st.bar_chart(mon["P&L (Rs)"], height=240, color="#2563EB")
            st.dataframe(mon.reset_index().rename(columns={"month": "Month"}),
                         use_container_width=True, hide_index=True)
    with tabs[5]:
        if trades:
            st.dataframe(pd.DataFrame(trades), use_container_width=True, height=360)


if run:
    is_opt = instrument == "Options"
    is_fut = instrument == "Futures"
    is_pos = instrument == "Positional"
    with st.spinner("Running backtest on real data..."):
        if is_pos:                               # multi-day hold (custom OR seeded preset)
            name = ("Custom position" if is_custom else meta["name"]) + " (Positional)"
            res = options_engine.summarize_positional(
                options_engine.custom_legs_fn(specs), name, params)
        elif is_opt:                             # custom OR predefined -> one builder path
            name = "Custom position" if is_custom else meta["name"]
            if not is_custom:                    # predefined strategies may pin engine flags
                params = {**meta.get("fixed_params", {}), **params}
            res = options_engine.summarize_with(
                options_engine.custom_legs_fn(specs), name, params)
        elif is_fut:                             # futures -> leg engine (FUT legs)
            name = meta["name"]
            params = {**meta.get("fixed_params", {}), **params}
            res = options_engine.summarize(meta["key"], params)
        else:
            res = engine.summarize(meta["key"], params)
    disp_name = name if (is_opt or is_fut or is_pos) else meta["name"]
    try:
        if is_pos:
            key = "custom" if is_custom else meta["key"]
            store.log_run("positional", key, disp_name, {"legs": specs, **params}, res)
        elif is_opt:
            key = "custom" if is_custom else meta["key"]
            store.log_run("options", key, disp_name, {"legs": specs, **params}, res)
        elif is_fut:
            store.log_run("futures", meta["key"], meta["name"], params, res)
        else:
            store.log_run("equity", meta["key"], meta["name"], params, res)
    except Exception:
        pass                                    # logging must never break a backtest
    # persist so the results survive reruns (e.g. clicking Download) -- StockMock keeps
    # its results on screen; Streamlit reruns would otherwise wipe them.
    st.session_state["bt_result"] = {
        "res": res, "params": params, "name": disp_name,
        "kind": "opt" if (is_opt or is_pos) else ("fut" if is_fut else "eq")}

# always render the last result (from session), not just on the Run click
_bt = st.session_state.get("bt_result")
if _bt:
    if _bt["kind"] in ("opt", "fut"):
        render_options_results(_bt["res"], _bt["params"], _bt["name"])
    else:
        render_results(_bt["res"], _bt["params"], _bt["name"])
else:
    st.caption("Set your variables above and hit **Run Backtest**.")
