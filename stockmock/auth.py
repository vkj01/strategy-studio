"""
auth.py -- email/password accounts for the multi-user beta.

Each user signs up / logs in; on success their user id is stored in the Streamlit
SESSION (per-user, since all sessions share one process) and pushed to db so every
conversation + backtest + AI context is scoped to only that user.

Passwords are hashed with PBKDF2-SHA256 (salted, 200k iterations) -- never stored
in plain text. Signup can be gated by an invite code (SIGNUP_INVITE_CODE secret /
env): set it for a controlled beta, leave it unset for open signup.

If no database is configured (local dev without NEON_DATABASE_URL), this falls
back to the old shared-password gate so nothing breaks. ASCII-only.
"""
import hashlib
import hmac
import os

import streamlit as st

import db


# --- password hashing --------------------------------------------------------
def hash_password(pw, salt=None, iters=200_000):
    salt = salt or os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), iters).hex()
    return "pbkdf2$%d$%s$%s" % (iters, salt, h)


def verify_password(pw, stored):
    try:
        _, iters, salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(iters)).hex()
        return hmac.compare_digest(calc, h)
    except Exception:
        return False


def _secret(name):
    try:
        v = st.secrets.get(name)
    except Exception:
        v = None
    return v or os.environ.get(name)


# --- fallback: old shared password (only when there's no DB) ------------------
def _legacy_gate():
    pw = _secret("APP_PASSWORD")
    if not pw:
        return                                          # open (local dev)
    if st.session_state.get("_authed"):
        return
    st.markdown("## Strategy Studio")
    st.caption("This is a private demo. Enter the password to continue.")
    entered = st.text_input("Password", type="password", label_visibility="collapsed",
                            placeholder="Password")
    if entered and entered == pw:
        st.session_state["_authed"] = True
        st.rerun()
    if entered and entered != pw:
        st.error("Incorrect password.")
    st.stop()


# --- account auth ------------------------------------------------------------
def _login_ui():
    st.markdown("## Strategy Studio")
    st.caption("Sign in to your account, or create one to start backtesting.")
    tab_login, tab_signup = st.tabs(["Log in", "Sign up"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email").strip().lower()
            pw = st.text_input("Password", type="password")
            ok = st.form_submit_button("Log in", type="primary", use_container_width=True)
        if ok:
            row = db.get_user(email) if email else None
            if row and verify_password(pw, row[2]):
                _sign_in(row[0], row[1], row[3])
            else:
                st.error("Wrong email or password.")

    with tab_signup:
        # Default-DENY: signup requires an invite code unless the deployer explicitly
        # opts into open registration (OPEN_SIGNUP=1). Forgetting to set
        # SIGNUP_INVITE_CODE used to mean "anyone can sign up" -- on a public beta
        # URL that's unmetered LLM/compute spend from strangers.
        invite_code = _secret("SIGNUP_INVITE_CODE")
        open_signup = str(_secret("OPEN_SIGNUP") or "").lower() in ("1", "true", "yes")
        invite_needed = not open_signup
        with st.form("signup_form"):
            name = st.text_input("Name")
            email2 = st.text_input("Email ").strip().lower()
            pw2 = st.text_input("Password ", type="password", help="At least 6 characters.")
            invite = st.text_input("Invite code", help="Ask the admin for this.") if invite_needed else ""
            ok2 = st.form_submit_button("Create account", type="primary", use_container_width=True)
        if ok2:
            if invite_needed and (not invite_code or invite.strip() != str(invite_code)):
                st.error("Invalid invite code.")
            elif not email2 or "@" not in email2:
                st.error("Enter a valid email.")
            elif len(pw2) < 6:
                st.error("Password must be at least 6 characters.")
            elif db.get_user(email2):
                st.error("An account with that email already exists -- log in instead.")
            else:
                uid = db.create_user(email2, hash_password(pw2), name.strip() or None)
                _sign_in(uid, email2, name.strip() or None)

    st.stop()


def _sign_in(uid, email, name):
    st.session_state["user_id"] = uid
    st.session_state["user_email"] = email
    st.session_state["user_name"] = name or email
    db.set_user(uid)
    st.rerun()


def gate():
    """Require a logged-in account (DB mode); fall back to the shared-password gate
    only when no database is configured."""
    if not db.ensure():
        return _legacy_gate()
    if st.session_state.get("user_id"):
        db.set_user(st.session_state["user_id"])        # keep the module fallback in sync
        return
    _login_ui()


def current_email():
    return st.session_state.get("user_email")


def logout():
    for k in ("user_id", "user_email", "user_name"):
        st.session_state.pop(k, None)
    st.rerun()


def sidebar_account():
    """Small 'signed in as ... / Log out' block in the sidebar (call after gate())."""
    if not st.session_state.get("user_id"):
        return
    with st.sidebar:
        who = st.session_state.get("user_name") or st.session_state.get("user_email")
        st.caption("Signed in as **%s**" % who)
        if st.button("Log out", key="_logout_btn", use_container_width=True):
            logout()
        st.divider()
