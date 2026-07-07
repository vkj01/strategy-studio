"""
db.py -- the relational data layer (Neon Postgres for now, any Postgres later).

Holds the per-user relational data: users, AI conversations, and backtest run
records. The bulk market data stays in DuckDB files -- this is only the small,
queryable, multi-user state.

Everything is keyed by user_id so a user only ever sees their own data. The
connection string comes from NEON_DATABASE_URL (in .env locally, st.secrets on
Cloud) -- swap that one value to point at the owner's paid DB later; no code
changes. If it's not set, db_available() is False and the app falls back to the
old file-based stores (convo_store / store). ASCII-only.
"""
import json
import os
import threading

_URL = None
# one connection PER THREAD, not a shared global -- Streamlit runs each session on
# its own thread, and a single shared psycopg2 connection/cursor is not thread-safe
# (concurrent users could interleave on it and see each other's query results).
_LOCAL = threading.local()


def _load_url():
    global _URL
    if _URL is None:
        url = os.environ.get("NEON_DATABASE_URL") or os.environ.get("DATABASE_URL")
        if not url:                                     # Streamlit Cloud: secrets live in st.secrets,
            try:                                        # and this runs BEFORE ai_assistant's bridge,
                import streamlit as st                  # so read them here directly (import-order safe).
                url = st.secrets.get("NEON_DATABASE_URL") or st.secrets.get("DATABASE_URL")
            except Exception:
                url = None
        if not url:                                     # try the project .env files
            here = os.path.dirname(os.path.abspath(__file__))
            for p in (os.path.join(here, ".env"), os.path.join(here, "..", ".env"),
                      os.path.join(here, "..", "AI", ".env")):
                if os.path.exists(p):
                    for line in open(p, "r", encoding="utf-8"):
                        line = line.strip()
                        if line.startswith("NEON_DATABASE_URL=") or line.startswith("DATABASE_URL="):
                            url = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
                if url:
                    break
        _URL = url or ""
    return _URL


def db_available():
    return bool(_load_url())


def _conn():
    """A live autocommit connection, reconnected if dropped (Neon is serverless).
    One per thread -- see _LOCAL above."""
    import psycopg2
    conn = getattr(_LOCAL, "conn", None)
    if conn is not None:
        try:
            if conn.closed == 0:
                return conn
        except Exception:
            pass
    # keepalives so Neon's pooler doesn't drop the idle connection between page
    # loads (a dropped conn would cost a fresh ~900ms Singapore handshake each time).
    conn = psycopg2.connect(_load_url(), keepalives=1, keepalives_idle=30,
                            keepalives_interval=10, keepalives_count=5)
    conn.autocommit = True
    _LOCAL.conn = conn
    return conn


def _exec(sql, params=None, fetch=None):
    """Run a statement with one automatic reconnect on a dropped connection."""
    import psycopg2
    for attempt in (1, 2):
        try:
            cur = _conn().cursor()
            cur.execute(sql, params or ())
            if fetch == "one":
                r = cur.fetchone(); cur.close(); return r
            if fetch == "all":
                r = cur.fetchall(); cur.close(); return r
            cur.close(); return None
        except psycopg2.OperationalError:
            _LOCAL.conn = None
            if attempt == 2:
                raise


# --- schema ------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name          TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT,
    messages   JSONB NOT NULL DEFAULT '[]',
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id     BIGSERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ts         TIMESTAMPTZ DEFAULT now(),
    instrument TEXT,
    strategy   TEXT,
    params     JSONB,
    summary    JSONB,
    source     TEXT
);
CREATE INDEX IF NOT EXISTS ix_convos_user ON conversations(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_runs_user   ON backtest_runs(user_id, run_id DESC);
"""


def init_schema():
    """Create tables if missing + ensure a fallback 'local' user. Runs the whole
    schema in ONE round-trip (psycopg2 sends the multi-statement string at once)."""
    _exec(SCHEMA)                                       # all CREATEs in one round-trip
    _exec("INSERT INTO users (email, password_hash, name) VALUES ('local@demo', 'x', 'Local') "
          "ON CONFLICT (email) DO NOTHING")
    return True


def local_user_id():
    r = _exec("SELECT id FROM users WHERE email='local@demo'", fetch="one")
    return r[0] if r else None


# --- current-user seam (set after login in Step 4; defaults to the local user) --
_INITED = False
_CURRENT_USER = None


def ensure():
    """Create the schema once per process; return True if the DB is usable."""
    global _INITED
    if not db_available():
        return False
    if not _INITED:
        init_schema()
        _INITED = True
    return True


def set_user(uid):
    global _CURRENT_USER
    _CURRENT_USER = uid


def current_user():
    """The logged-in user's id. Inside a LIVE Streamlit session this MUST come from
    st.session_state (per-user, since all sessions share one process) -- and if it's
    not set there, we return None rather than silently falling back to a shared user.
    Falling back inside the running app would let one user's data (backtests, chat
    history) get silently written to / read from another user's (or the shared
    'local@demo') account -- exactly the isolation bug this guards against.
    The module-global/local-user fallback only serves standalone scripts that run
    OUTSIDE a Streamlit session (e.g. migrate_to_neon.py), which call set_user()
    themselves and have no session to read."""
    try:
        import streamlit as st
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is not None:      # we ARE inside a live app session
            return st.session_state.get("user_id")  # None if not logged in -- no fallback
    except Exception:
        pass
    if _CURRENT_USER is not None:
        return _CURRENT_USER
    return local_user_id()


# --- users (auth wiring lands in Step 4) -------------------------------------
def create_user(email, password_hash, name=None):
    r = _exec("INSERT INTO users (email, password_hash, name) VALUES (%s,%s,%s) "
              "ON CONFLICT (email) DO NOTHING RETURNING id", (email, password_hash, name), fetch="one")
    return r[0] if r else get_user_id(email)


def get_user(email):
    return _exec("SELECT id, email, password_hash, name FROM users WHERE email=%s", (email,), fetch="one")


def get_user_id(email):
    r = _exec("SELECT id FROM users WHERE email=%s", (email,), fetch="one")
    return r[0] if r else None


# --- conversations -----------------------------------------------------------
def save_conversation(user_id, cid, title, messages):
    _exec("INSERT INTO conversations (id, user_id, title, messages, updated_at) "
          "VALUES (%s,%s,%s,%s, now()) "
          "ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title, messages=EXCLUDED.messages, "
          "updated_at=now()",
          (cid, user_id, title, json.dumps(messages)))


def list_conversations(user_id):
    rows = _exec("SELECT id, title, updated_at FROM conversations WHERE user_id=%s "
                 "ORDER BY updated_at DESC", (user_id,), fetch="all") or []
    return [{"id": r[0], "title": r[1], "ts": str(r[2])} for r in rows]


def load_conversation(user_id, cid):
    r = _exec("SELECT messages FROM conversations WHERE user_id=%s AND id=%s",
              (user_id, cid), fetch="one")
    if not r:
        return []
    return r[0] if isinstance(r[0], list) else json.loads(r[0])


def delete_conversation(user_id, cid):
    _exec("DELETE FROM conversations WHERE user_id=%s AND id=%s", (user_id, cid))


# --- backtest runs -----------------------------------------------------------
def log_run(user_id, instrument, strategy, params, summary, source="app"):
    _exec("INSERT INTO backtest_runs (user_id, instrument, strategy, params, summary, source) "
          "VALUES (%s,%s,%s,%s,%s,%s)",
          (user_id, instrument, strategy, json.dumps(params), json.dumps(summary), source))


def list_runs(user_id, limit=25):
    rows = _exec("SELECT ts, instrument, strategy, params, summary FROM backtest_runs "
                 "WHERE user_id=%s ORDER BY run_id DESC LIMIT %s", (user_id, limit), fetch="all") or []
    out = []
    for ts, inst, strat, params, summ in rows:
        out.append({"ts": str(ts)[:19], "instrument": inst, "strategy": strat,
                    "params": params if isinstance(params, dict) else json.loads(params or "{}"),
                    "summary": summ if isinstance(summ, dict) else json.loads(summ or "{}")})
    return out
