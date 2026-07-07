"""
Strategy Studio -- entry point.

Owns the app shell: page config, the clean-fintech theme, login/auth, and the
top-level navigation (Home / Backtest / AI Assistant). Each screen lives in
views/ and is run through st.navigation, so the whole thing feels like one app
with a real front door rather than a bare form.

Run:  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="Strategy Studio", page_icon="📈", layout="wide")

import auth      # noqa: E402
import branding  # noqa: E402

branding.inject_css()          # style everything, including the login screen
auth.gate()                    # login (DB mode) / shared-password (no DB) / open (local)

# --- signed in: brand + account + navigation --------------------------------
with st.sidebar:
    branding.brand_bar()
auth.sidebar_account()

home = st.Page("views/home.py", title="Home", icon=":material/home:", default=True)
backtest = st.Page("views/backtest.py", title="Backtest", icon=":material/insights:")
assistant = st.Page("views/ai_assistant.py", title="AI Assistant", icon=":material/smart_toy:")

st.navigation([home, backtest, assistant]).run()
