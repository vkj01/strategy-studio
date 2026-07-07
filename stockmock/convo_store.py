"""
convo_store.py -- persist AI Assistant conversations to disk so they survive
page refreshes and app restarts (ChatGPT-style: new chat + past-chat list).

Each conversation is one JSON file in data/conversations/ holding its messages
(role, content, cost, and any backtest results). ASCII-only.
"""
import glob
import json
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.abspath(os.path.join(HERE, "..", "data", "conversations"))


def new_id():
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def title(messages):
    """Auto-title from the first user message."""
    for m in messages:
        if m.get("role") == "user" and m.get("content"):
            t = m["content"].strip().replace("\n", " ")
            return (t[:58] + "...") if len(t) > 60 else t
    return "New chat"


def _db():
    """Return the db module if a Postgres DB is configured, else None (file mode --
    only safe for single-user local dev). If a DB URL IS configured but currently
    unreachable, this RAISES instead of silently falling back to the shared local
    file store -- that file store has no per-user scoping at all, so an outage would
    otherwise mix every beta user's conversations together."""
    import db
    if db.ensure():
        return db
    if db.db_available():
        raise RuntimeError("Database is configured but unavailable right now.")
    return None


def save(cid, messages, custom_title=None):
    """Persist the conversation (skips empty ones). custom_title overrides the auto-title."""
    if not messages:
        return
    ttl = custom_title or title(messages)
    d = _db()
    if d:
        d.save_conversation(d.current_user(), cid, ttl, messages)
        return
    os.makedirs(DIR, exist_ok=True)
    data = {"id": cid, "title": ttl,
            "ts": datetime.now().isoformat(timespec="seconds"), "messages": messages}
    with open(os.path.join(DIR, cid + ".json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def list_convos():
    """[{id, title, ts}] newest first, for the current user."""
    d = _db()
    if d:
        return d.list_conversations(d.current_user())
    if not os.path.isdir(DIR):
        return []
    out = []
    for p in glob.glob(os.path.join(DIR, "*.json")):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                dd = json.load(fh)
            out.append({"id": dd["id"], "title": dd.get("title", "chat"),
                        "ts": dd.get("ts", ""), "n": len(dd.get("messages", []))})
        except Exception:
            pass
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out


def load(cid):
    d = _db()
    if d:
        return d.load_conversation(d.current_user(), cid)
    p = os.path.join(DIR, cid + ".json")
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh).get("messages", [])
    except Exception:
        return []


def delete(cid):
    d = _db()
    if d:
        d.delete_conversation(d.current_user(), cid)
        return
    p = os.path.join(DIR, cid + ".json")
    if os.path.exists(p):
        os.remove(p)
