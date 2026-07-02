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


def save(cid, messages, custom_title=None):
    """Write the conversation (skips empty ones). custom_title overrides the auto-title."""
    if not messages:
        return
    os.makedirs(DIR, exist_ok=True)
    data = {"id": cid, "title": (custom_title or title(messages)),
            "ts": datetime.now().isoformat(timespec="seconds"), "messages": messages}
    with open(os.path.join(DIR, cid + ".json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def list_convos():
    """[{id, title, ts, n}] newest first."""
    if not os.path.isdir(DIR):
        return []
    out = []
    for p in glob.glob(os.path.join(DIR, "*.json")):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            out.append({"id": d["id"], "title": d.get("title", "chat"),
                        "ts": d.get("ts", ""), "n": len(d.get("messages", []))})
        except Exception:
            pass
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out


def load(cid):
    p = os.path.join(DIR, cid + ".json")
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh).get("messages", [])
    except Exception:
        return []


def delete(cid):
    p = os.path.join(DIR, cid + ".json")
    if os.path.exists(p):
        os.remove(p)
