"""
migrate_to_neon.py -- one-time: copy the existing file-based conversations
(data/conversations/*.json) and backtest run-history (data/runs.duckdb) into the
Neon Postgres tables, under the local user. Idempotent: it clears the local
user's rows first, so re-running just re-syncs. ASCII-only.
"""
import glob
import json
import os

import duckdb

import db

HERE = os.path.dirname(os.path.abspath(__file__))
CONV_DIR = os.path.abspath(os.path.join(HERE, "..", "data", "conversations"))
RUNS_DB = os.path.abspath(os.path.join(HERE, "..", "data", "runs.duckdb"))


def run():
    if not db.ensure():
        print("No NEON_DATABASE_URL configured -- nothing to migrate.")
        return
    uid = db.local_user_id()
    # fresh start for the local user (removes any test rows), then re-import
    db._exec("DELETE FROM conversations WHERE user_id=%s", (uid,))
    db._exec("DELETE FROM backtest_runs WHERE user_id=%s", (uid,))

    nconv = 0
    for p in sorted(glob.glob(os.path.join(CONV_DIR, "*.json"))):
        try:
            d = json.load(open(p, "r", encoding="utf-8"))
            db.save_conversation(uid, d["id"], d.get("title"), d.get("messages", []))
            nconv += 1
        except Exception as e:
            print("  skip conversation %s: %s" % (os.path.basename(p), e))

    nruns = 0
    if os.path.exists(RUNS_DB):
        con = duckdb.connect(RUNS_DB, read_only=True)
        try:
            rows = con.execute(
                "SELECT ts, instrument, strategy_name, params, summary, source "
                "FROM backtest_runs ORDER BY run_id").fetchall()
            for ts, inst, strat, params, summ, source in rows:
                try:
                    db.log_run(uid, inst, strat, json.loads(params), json.loads(summ),
                               source or "migrated")
                    nruns += 1
                except Exception as e:
                    print("  skip run: %s" % e)
        finally:
            con.close()

    print("Migrated %d conversations and %d runs into Neon (user id %s)." % (nconv, nruns, uid))


if __name__ == "__main__":
    run()
