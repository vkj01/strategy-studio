# Data provisioning (not part of the git repo)

The app needs these files at runtime. They are gitignored (see `.gitignore`) --
never commit them, `data/options.duckdb` is 98MB and sits right at GitHub's
100MB hard file-size cap even today; it will only grow as more history is added.

| File | Size (now) | Built by |
|---|---|---|
| `data/options.duckdb` | 98 MB | `preprocess_options.py` + `preprocess_futures.py` |
| `data/market.duckdb`  | 7.8 MB | `datastore.py` (equity daily loader) |
| `data/runs.duckdb`    | small, grows | created automatically (local-dev fallback store; unused once `NEON_DATABASE_URL` is set) |
| `data/conversations/` | small, grows | created automatically (local-dev fallback store; unused once DB is set) |

## Getting the two DuckDB files onto a deploy target

Do NOT `git add` them. Options, in order of what we're actually doing:

1. **Streamlit Cloud (interim beta):** upload directly via the Cloud file browser,
   or have the app download them from private cloud storage on first boot (a
   `startup.py` step reading from an R2/S3 bucket into `data/`). Streamlit Cloud's
   filesystem is ephemeral across redeploys, so a boot-time fetch is required
   either way if you go this route.
2. **Owner's VPS (target for real beta):** `scp`/`rsync` the files once during
   deploy; they persist on disk across app restarts (no ephemeral filesystem).
3. **Cloudflare R2** (already the plan for object storage -- see project memory
   `project_backtester_infra_plan.md`): push both files there, pull them down as
   part of the deploy/boot script. This is the long-term answer once the owner's
   server is up, and also solves versioning as more data gets added.

Whichever path: after copying, verify with `python -c "import options_data as od;
print(od.data_span('NIFTY'))"` -- it should print the expected date range, not
an error.
