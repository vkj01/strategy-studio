"""
branding.py -- one place for the Strategy Studio look: the clean-fintech CSS and
small header/card helpers, so every page shares the same polished styling.
Keeps the visual identity consistent and easy to tweak. ASCII-only.
"""
import streamlit as st

APP_NAME = "Strategy Studio"
TAGLINE = "AI-powered stock & options strategy backtesting"

_CSS = """
<style>
/* ---- base ---- */
html, body, [class*="css"] { font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif; }
.block-container { padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1240px; }
:root {
  --brand:#2563EB; --brand2:#0EA5E9; --ink:#0F172A; --muted:#64748B;
  --line:#E6EBF2; --bg-soft:#F1F5FB; --ok:#16A34A; --bad:#DC2626;
}

/* ---- top brand bar ---- */
.ss-brand { display:flex; align-items:center; gap:.6rem; padding:2px 0 14px; }
.ss-logo { width:34px; height:34px; border-radius:9px; color:#fff; font-weight:800;
  display:flex; align-items:center; justify-content:center; font-size:1.05rem;
  background:linear-gradient(135deg,#2563EB,#0EA5E9); box-shadow:0 4px 14px rgba(37,99,235,.28); }
.ss-brand .nm { font-weight:800; font-size:1.15rem; color:var(--ink); letter-spacing:-.2px; }
.ss-brand .tg { color:var(--muted); font-size:.82rem; margin-left:.2rem; }

/* ---- page hero ---- */
.ss-hero { background:linear-gradient(120deg,#EAF1FE 0%, #F3F8FF 60%, #FFFFFF 100%);
  border:1px solid var(--line); border-radius:18px; padding:22px 26px; margin-bottom:20px; }
.ss-hero h1 { margin:0; font-size:1.5rem; color:var(--ink); letter-spacing:-.4px; }
.ss-hero p { margin:.35rem 0 0; color:var(--muted); font-size:.94rem; }

/* ---- action / stat cards ---- */
.ss-card { background:#fff; border:1px solid var(--line); border-radius:16px;
  padding:18px 18px; height:100%; transition:.15s; }
.ss-card:hover { border-color:#CBD9F0; box-shadow:0 8px 24px rgba(15,23,42,.06); }
.ss-card .ic { font-size:1.5rem; }
.ss-card h3 { margin:.5rem 0 .2rem; font-size:1.02rem; color:var(--ink); }
.ss-card p { margin:0; color:var(--muted); font-size:.86rem; line-height:1.35; }

/* ---- buttons ---- */
.stButton>button, .stFormSubmitButton>button {
  border-radius:10px; font-weight:650; border:1px solid var(--line); }
.stButton>button[kind="primary"], .stFormSubmitButton>button[kind="primary"] {
  background:var(--brand); border:0; box-shadow:0 4px 14px rgba(37,99,235,.28); }
.stButton>button[kind="primary"]:hover { background:#1D4ED8; }

/* ---- metrics as cards ---- */
div[data-testid="stMetric"] { background:#fff; border:1px solid var(--line);
  border-radius:12px; padding:12px 16px; }
div[data-testid="stMetricValue"] { font-size:1.28rem; color:var(--ink); }
div[data-testid="stMetricLabel"] { color:var(--muted); }

/* ---- sidebar ---- */
section[data-testid="stSidebar"] { background:#FBFCFE; border-right:1px solid var(--line); }

/* ---- misc ---- */
[data-testid="stExpander"] { border:1px solid var(--line); border-radius:12px; }
hr { margin:1rem 0; border-color:var(--line); }
</style>
"""


def inject_css():
    st.markdown(_CSS, unsafe_allow_html=True)


def brand_bar():
    """Small logo + name bar for the top of the sidebar / pages."""
    st.markdown(
        '<div class="ss-brand"><div class="ss-logo">S</div>'
        '<span class="nm">%s</span></div>' % APP_NAME, unsafe_allow_html=True)


def hero(title, subtitle=""):
    st.markdown('<div class="ss-hero"><h1>%s</h1>%s</div>'
                % (title, ("<p>%s</p>" % subtitle) if subtitle else ""),
                unsafe_allow_html=True)
