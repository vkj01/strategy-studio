# Strategy Studio — Deploy to Streamlit Community Cloud

This folder is a **self-contained, deploy-ready** copy: the app (`stockmock/`), the
data it needs (`data/*.duckdb` — options + equity), and your run + chat history.
No raw tick data, no API keys committed.

Live link result: `https://<your-app-name>.streamlit.app` — always on, password-gated.

---

## STEP 1 — Push this folder to a new GitHub repo

Create a new **private** repo at https://github.com/new (e.g. `strategy-studio`), then
in a terminal:

```bash
cd "C:\Users\vises\OneDrive\Desktop\AI Backtester\deploy_package"
git init
git add .
git commit -m "Strategy Studio - deploy"
git branch -M main
git remote add origin https://github.com/<YOUR_USERNAME>/strategy-studio.git
git push -u origin main
```
(~37 MB push — fine. Data DuckDBs and conversations are included on purpose.)

## STEP 2 — Create the app on Streamlit Community Cloud

1. Go to **https://share.streamlit.io** and sign in with GitHub.
2. **Create app → Deploy a public app from GitHub**.
3. Fill in:
   - **Repository:** `<YOUR_USERNAME>/strategy-studio`
   - **Branch:** `main`
   - **Main file path:** `stockmock/app.py`
4. Click **Advanced settings**:
   - **Python version:** **3.11** (or 3.12) — matches what we tested; do NOT use 3.13
     (the pinned numpy/pandas need <=3.12).
   - **Secrets:** paste this (TOML), with YOUR values:
     ```toml
     ANTHROPIC_API_KEY = "sk-ant-...your-NEW-key..."
     app_password = "pick-a-demo-password"
     ```
5. **Deploy.** First build takes ~3–6 min. You'll get the live link.

## STEP 3 — Security (do these before sharing the link)

1. **Rotate the Claude key.** The old one was pasted in chat — generate a fresh key at
   https://console.anthropic.com, and use the NEW key in the Secrets above.
2. **Set a spending limit / alert** on the Anthropic account (Billing → Limits), so a
   runaway can't cost much.
3. **Keep `app_password` private** — share it only with your demo audience. The gate
   stops anyone who finds the URL from using your Claude credits.

---

## Notes

- **History:** the run history (`runs.duckdb`) and saved chats (`data/conversations/`)
  ship with the repo, so the deployed app opens WITH your existing history. Anything
  NEW created live during the demo persists only until the app restarts/redeploys
  (Streamlit Cloud storage is ephemeral) — the shipped history always comes back.
- **Changing password / key later:** edit them in the app's **Settings → Secrets** on
  Streamlit Cloud (no redeploy needed).
- **To update the app:** commit + push to the repo; Streamlit Cloud auto-redeploys.
- **Strategy builder (AI writing new strategies):** runs a short-lived subprocess; works
  on Streamlit Cloud. If a cloud sandbox ever blocks it, that one feature degrades
  gracefully (returns an error) without affecting the rest.
