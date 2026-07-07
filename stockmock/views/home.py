"""
home.py -- the landing page users see after logging in. Gives the app a real
"front door": a welcome, big clear entry points, and their recent activity --
instead of dropping straight into a form. ASCII-only.
"""
import pandas as pd
import streamlit as st

import branding
import store

branding.inject_css()

name = st.session_state.get("user_name") or "there"
branding.hero("Welcome back, %s" % name,
              "Backtest equity, options & futures strategies, chat with the AI analyst, "
              "and optimize your code -- all in one place.")

# --- quick actions -----------------------------------------------------------
st.markdown("##### Quick actions")
cols = st.columns(3)
CARDS = [
    ("Run a Backtest", "Test any strategy (equity / options / futures) on real market data with full risk controls.",
     "views/backtest.py", "Open Backtest"),
    ("Ask the AI", "Plain-English backtests, parameter sweeps, comparisons, and building new strategies from an idea.",
     "views/ai_assistant.py", "Open AI Assistant"),
    ("Optimize your code", "Paste a strategy function -- the AI rewrites it faster and PROVES the results are identical.",
     "views/ai_assistant.py", "Open in AI"),
]
for col, (title, desc, page, link) in zip(cols, CARDS):
    with col:
        with st.container(border=True):
            st.markdown("**%s**" % title)
            st.caption(desc)
            st.page_link(page, label=link, icon=":material/arrow_forward:")

st.write("")

# --- recent activity ---------------------------------------------------------
st.markdown("##### Your recent backtests")


@st.cache_data(ttl=20, show_spinner=False)
def _recent_runs(user_id, limit=8):        # cache per user so a rerun/nav doesn't re-query Neon
    return store.list_runs(limit=limit)


try:
    runs = _recent_runs(st.session_state.get("user_id"), 8)
except Exception:
    runs = []

if not runs:
    st.info("No backtests yet. Head to **Backtest** or the **AI Assistant** to run your first one -- "
            "it'll show up here.")
else:
    rows = []
    for r in runs:
        s = r.get("summary") or {}
        pnl = s.get("total_pnl", s.get("net_pnl_rs"))
        rows.append({"When": r.get("ts"), "Strategy": r.get("strategy"),
                     "Instrument": r.get("instrument"),
                     "P&L (Rs)": pnl, "Win %": s.get("win_pct"),
                     "Max DD %": s.get("max_drawdown_pct")})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
