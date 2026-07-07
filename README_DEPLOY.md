# Strategy Studio — Deploy to Streamlit Community Cloud (multi-user beta)

Self-contained, deploy-ready copy: the app (`stockmock/`) + the market data it needs
(`data/options.duckdb` 97.5 MB, `data/market.duckdb` 8 MB). **No raw ticks, no API keys,
no user data committed** — per-user backtests + AI chats now live in the **Neon** database.

Live result: `https://<your-app>.streamlit.app` — always on, **account login**, per-user isolated.

> This repo is already wired to **github.com/vkj01/strategy-studio**, which your existing
> Streamlit Cloud app deploys from. So updating = push here → it auto-redeploys.

---

## STEP 1 — Push the refreshed code + data

```bash
cd "C:\Users\vises\OneDrive\Desktop\AI Backtester\deploy_package"
git push origin main
```
(~100 MB push the first time because `options.duckdb` grew to 97.5 MB — GitHub allows up
to 100 MB per file, so we're just under. If it ever crosses 100 MB, switch to Git LFS or a
boot-time download.)

## STEP 2 — Set the Secrets on Streamlit Cloud

In the app's **Settings → Secrets**, paste this TOML with YOUR values:

```toml
ANTHROPIC_API_KEY = "sk-ant-...your-NEW-key..."
NEON_DATABASE_URL = "postgresql://neondb_owner:...@ep-...aws.neon.tech/neondb?sslmode=require&channel_binding=require"
```

- **`NEON_DATABASE_URL` is REQUIRED** for the multi-user beta. Without it the app drops to
  single-user file mode and the test accounts below won't work.
- **Do NOT set `SIGNUP_INVITE_CODE` and do NOT set `OPEN_SIGNUP`.** Signup then default-DENIES,
  so nobody can self-register — only the pre-created test accounts (below) can log in. That's
  what you want for a controlled beta. (To later allow self-signup: set `SIGNUP_INVITE_CODE`
  to a code you share, or `OPEN_SIGNUP = "1"` for fully open.)
- Python version (Advanced settings): **3.11 or 3.12** — NOT 3.13 (pinned numpy/pandas need <=3.12).
- Main file path: **`stockmock/app.py`** · Branch: **`main`**.

Streamlit Cloud auto-redeploys on push; secrets apply without a redeploy.

## STEP 3 — Test accounts (already created in Neon)

Hand these to your testers. They live in the Neon DB, so they work the moment Neon is wired:

| Email | Password |
|---|---|
| tester1@studio.beta | Falcon-Test-91 |
| tester2@studio.beta | Otter-Test-52 |
| tester3@studio.beta | Raven-Test-38 |

Each tester sees ONLY their own backtests + AI chats. Ask them to change nothing but explore:
run backtests (equity / options / futures / **positional**), chat with the AI, download Excels.

## STEP 4 — Security before sharing the link

1. **Rotate the Anthropic key** — generate a fresh one at https://console.anthropic.com and use
   it in Secrets (any key ever pasted in chat should be considered exposed).
2. **Set an Anthropic spend limit / alert** (Billing → Limits) so a runaway can't cost much.
3. The Neon URL carries the DB password — keep it ONLY in Streamlit Secrets, never in the repo.
   You can rotate it any time from the Neon dashboard.

---

## Notes

- **Per-user data** (backtests, AI chats) persists in Neon across redeploys. The app's local
  disk is ephemeral on Streamlit Cloud, but nothing important is written there anymore.
- **Positional (multi-day) backtests** are live but NOT yet StockMock-validated to the rupee —
  the app/AI flags them as preliminary. Validate before trusting those numbers.
- **To update the app later:** commit + push here; Streamlit Cloud auto-redeploys.
- **AI strategy-builder** runs a short-lived sandboxed subprocess (memory + output capped); works
  on Streamlit Cloud, degrades gracefully if a cloud sandbox ever blocks it.
