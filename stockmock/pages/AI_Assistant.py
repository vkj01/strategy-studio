"""
AI Assistant page (Streamlit multipage) -- the platform's chat analyst that can
actually RUN backtests. You ask in plain English ("test a short straddle in June
with a 25% SL"); the AI calls the real engine via a tool and shows the results
inline (KPIs + equity curve + Excel/PDF download). ASCII-only.
"""
import pandas as pd
import streamlit as st

import ai_assistant
import convo_store

st.set_page_config(page_title="AI Assistant", page_icon="*", layout="wide")

import auth  # noqa: E402
auth.gate()  # password gate (no-op locally; enforced on the deployed app)

st.markdown("""
<style>
.block-container { max-width: 950px; }
.ai-head { background: linear-gradient(90deg,#2A2350,#4B3FbF); color:#fff;
    padding:16px 22px; border-radius:14px; margin-bottom:14px; }
.ai-head h1 { margin:0; font-size:1.35rem; }
.ai-head p { margin:.2rem 0 0; opacity:.8; font-size:.9rem; }
div[data-testid="stMetricValue"] { font-size: 1.15rem; }
</style>
""", unsafe_allow_html=True)

brain = ai_assistant.active_label("strong") if ai_assistant.llm_available() else "offline (add a key to .env)"
st.markdown('<div class="ai-head"><h1>AI Assistant</h1>'
            '<p>Ask in plain English -- I can run real backtests. Brain: <b>%s</b></p></div>' % brain,
            unsafe_allow_html=True)

if not ai_assistant.llm_available():
    st.warning("No API key configured. Add ANTHROPIC_API_KEY (for tool-use) or GROQ_API_KEY to .env, then reload.")


def _rs(x):
    return "Rs %s" % "{:,}".format(int(round(x)))


# --- DEMO cost meter (remove this block + its two call-sites before the demo) --
_USD_INR = 83.0


def cost_caption(cost):
    if not cost:
        return
    usd = cost.get("usd", 0.0)
    st.caption("💸 **Cost of this answer:** $%.4f  (~Rs %.2f)  ·  %d LLM call(s), "
               "%s in / %s out tokens  ·  %d backtest run(s)"
               % (usd, usd * _USD_INR, cost.get("llm_calls", 0),
                  "{:,}".format(cost.get("in_tokens", 0)), "{:,}".format(cost.get("out_tokens", 0)),
                  cost.get("backtests", 0)))


def render_result(res, label, params, key):
    """Compact result card: KPIs + equity curve + Excel/PDF download."""
    m, p, tr = res["metrics"], res["performance"], res["trades"]
    is_opt = bool(tr) and "pnl" in tr[0]
    with st.container(border=True):
        st.markdown("**%s** — result" % label)
        c = st.columns(4)
        if is_opt:
            c[0].metric("Total P&L", _rs(sum(t["pnl"] for t in tr)))
            c[3].metric("Trades", "%d" % m.get("n", 0))
        else:
            base = p.get("capital_base") or 100000
            c[0].metric("Net P&L", _rs(base * p.get("total_return_pct", 0) / 100.0))
            c[3].metric("CAGR", "%.1f%%" % p.get("cagr_pct", 0))
        c[1].metric("Win %", "%.1f%%" % m.get("win", 0))
        c[2].metric("Max DD", "%.1f%%" % p.get("max_drawdown_pct", 0))
        if p.get("equity_curve"):
            eq = pd.DataFrame(p["equity_curve"]); eq["date"] = pd.to_datetime(eq["date"])
            st.line_chart(eq.set_index("date"), y="equity", height=200, color="#5B4FE9")
        try:
            import report_export
            d1, d2 = st.columns(2)
            d1.download_button("Excel", report_export.build_excel(res, params, label),
                               file_name="bt_%s.xlsx" % key, key="xl_%s" % key,
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               use_container_width=True)
            d2.download_button("PDF", report_export.build_pdf(res, params, label),
                               file_name="bt_%s.pdf" % key, key="pdf_%s" % key,
                               mime="application/pdf", use_container_width=True)
        except Exception as e:
            st.caption("Export unavailable: %s" % e)


if "assistant_chat" not in st.session_state:
    st.session_state.assistant_chat = []
if "convo_id" not in st.session_state:
    st.session_state.convo_id = convo_store.new_id()
if "convo_title" not in st.session_state:
    st.session_state.convo_title = ""


def _save_current():
    convo_store.save(st.session_state.convo_id, st.session_state.assistant_chat,
                     st.session_state.convo_title or None)


# --- sidebar: New conversation + current chat (nameable) + saved chats ---------
with st.sidebar:
    st.markdown("### 💬 Conversations")
    if st.button("➕  New conversation", use_container_width=True):
        _save_current()                                   # keep the one we're leaving
        st.session_state.convo_id = convo_store.new_id()
        st.session_state.assistant_chat = []
        st.session_state.convo_title = ""
        st.rerun()

    if st.session_state.assistant_chat:                   # current chat, pinned at top + renameable
        st.caption("Current chat")
        cur = st.session_state.convo_title or convo_store.title(st.session_state.assistant_chat)
        name = st.text_input("Name this chat", value=cur, key="convo_name_box",
                             label_visibility="collapsed", placeholder="Name this chat...")
        if name and name != cur:
            st.session_state.convo_title = name
            _save_current()
            st.rerun()

    past = [c for c in convo_store.list_convos() if c["id"] != st.session_state.convo_id]
    if past:
        st.caption("Past chats")
        for c in past:
            if st.button(c["title"] or "chat", key="cv_" + c["id"], use_container_width=True):
                _save_current()                           # keep current before switching
                st.session_state.convo_id = c["id"]
                st.session_state.assistant_chat = convo_store.load(c["id"])
                st.session_state.convo_title = c["title"]
                st.rerun()

# replay history (messages + any backtests each one ran)
for mi, msg in enumerate(st.session_state.assistant_chat):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        for ri, r in enumerate(msg.get("results", [])):
            render_result(r["res"], r["label"], r["params"], key="%d_%d" % (mi, ri))
        cost_caption(msg.get("cost"))

prompt = st.chat_input("e.g. \"test a short straddle in June with 25% SL\"  ·  \"backtest MA 50/200 on top 30\"")
if prompt:
    st.session_state.assistant_chat.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        sink = {}
        reply = st.write_stream(ai_assistant.chat_agentic_stream(st.session_state.assistant_chat, sink))
        mi = len(st.session_state.assistant_chat)
        for ri, r in enumerate(sink.get("results", [])):
            render_result(r["res"], r["label"], r["params"], key="%d_%d" % (mi, ri))
        cost_caption(sink.get("cost"))
    st.session_state.assistant_chat.append({"role": "assistant", "content": reply,
                                            "results": sink.get("results", []), "cost": sink.get("cost")})
    _save_current()                               # auto-save (keeps any custom name)
    st.rerun()                                    # refresh the sidebar with this chat

if not st.session_state.assistant_chat:
    st.info("Try: *\"test a short straddle for June 2026 with a 25% stop-loss\"*  ·  "
            "*\"run an iron butterfly and compare to a short strangle\"*  ·  "
            "*\"backtest a 50/200 MA crossover on the top 30 stocks with an 8% stop\"*")
