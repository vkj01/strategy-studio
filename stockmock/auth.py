"""
auth.py -- lightweight password gate for the deployed app.

Enforced ONLY when a password is configured (via st.secrets["app_password"] or
the APP_PASSWORD env var) -- so local development stays open, but the public
Streamlit Cloud deployment requires the password. ASCII-only.
"""
import os

import streamlit as st


def _configured_password():
    try:
        pw = st.secrets.get("app_password")           # Streamlit Cloud secret
    except Exception:
        pw = None
    return pw or os.environ.get("APP_PASSWORD")


def gate():
    """Block the page behind a password when one is configured. No-op locally."""
    pw = _configured_password()
    if not pw:
        return                                        # no password set -> open (local dev)
    if st.session_state.get("_authed"):
        return
    st.markdown("## 🔒 Strategy Studio")
    st.caption("This is a private demo. Enter the password to continue.")
    entered = st.text_input("Password", type="password", label_visibility="collapsed",
                            placeholder="Password")
    if entered and entered == pw:
        st.session_state["_authed"] = True
        st.rerun()
    if entered and entered != pw:
        st.error("Incorrect password.")
    st.stop()
