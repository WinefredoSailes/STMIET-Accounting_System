# Go-Live: Imports Runbook (Render + fresh production Postgres)

Target: **Saturday, Sept 12 2026** — deploy STMIET Accounting System to Render
(Dockerfile image, `config.settings.prod`) against a **fresh production
PostgreSQL**, then load the Sept-1-2026 master data and opening balances.

This Saturday is an **online pilot**: the team accesses the system over the
internet, works through the real daily cycle, and decides to continue on the
paid plan or fall back. The pilot runs on Render's **30-day free tier**; upgrade
to the **Starter plan (~$7/mo)** is a dashboard plan change after go-live — no
redeploy.

Pilot data is loaded **either as real go-live data or as throwaway test
figures** — both paths are supported, see the **Post-pilot decision** section.

Every step is **idempotent** — safe to re-run mid-way. Never run `seed_demo`
or `flush_demo` against production (dev-only tools).

---

## A. Render service setup (one time)

1. **New Web Service** on Render, deployed from the repo's `main` branch,
   using the existing `backend/Dockerfile` (Python 3.13, gunicorn on `:8000`).
2. **Create a Render Postgres instance** and attach it.
3. **Environment variables** (from `config/settings/base.py` + `prod.py`):

   | Variable | Value |
   |---|---|
   | `DJANGO_SETTINGS_MODULE` | `config.settings.prod` |
   | `DATABASE_URL` | Render Postgres **Internal** URL |
   | `SECRET_KEY` | strong, random, unique to prod |
   | `ALLOWED_HOSTS` | render app hostname (e.g. `your-app.onrender.com`) |
   | `REDIS_URL` | optional; no celery worker on day one |

   `prod.py` rejects a non-PostgreSQL `DATABASE_URL` and forces HTTPS/HSTS.
4. **Pre-Deploy Command** (runs on every deploy, idempotent):

   ```sh
   python manage.py migrate && python manage.py collectstatic --noinput
   ```

   Static files are served by WhiteNoise middleware (see
   `config/settings/base.py`); without the `collectstatic` step the UI loads
   without CSS/assets.
5. **No worker/cron on day one.** Depreciation is posted via the Month-End
   Close screen button; `run_scheduler --loop` is a post-go-live follow-up.
6. **Pilot then paid.** New Render accounts get a 30-day free trial — enough
   for the Saturday pilot. Once the team decides to continue, change the web
   service plan to **Starter (~$7/mo)** in the dashboard (no code/deploy
   change). Managed Postgres is billed separately from the web service.

---

## B. Pre-flight checklist (before importing)

- [x] **Finance head confirmation:** no receivables, payables, or inventory
  balances exist before Sept 1 — the opening position is **cash + fixed assets
  only**. (If any do exist, a small TB-style `OPENING-BALANCES.xlsx` is
  required for those accounts; cash alone cannot carry them.)
- [ ] **Decide the pilot data mode:** real go-live data or throwaway test
  figures. This choice is made *before* importing and only changes the
  post-pilot action (continue vs reset).
- [ ] Source workbooks staged (manifest below), `.env` has the external
  `DATABASE_URL`.

---

## C. Import sequence (local machine → production Postgres)

Because `*.xlsx` sources are git-ignored and the container filesystem is
ephemeral, the imports run **from your machine against the Render Postgres**.
Use the same code version that is (about to be) deployed. The whole sequence is
re-runnable from scratch after a throwaway reset (recreate the DB, then run it
again).

1. Stage your shell environment:

   ```powershell
   $env:DJANGO_SETTINGS_MODULE = "config.settings.prod"
   $env:DATABASE_URL = "postgresql://USER:PASS@HOST:PORT/DB"   # Render Postgres EXTERNAL URL
   $env:SECRET_KEY = "anything-non-empty"                       # CLI run; not the real key
   $env:ALLOWED_HOSTS = ""
   ```

   Use a least-privilege credential where possible. Treat the URL as a secret
   (local `.env`, never commit).

2. Run in order, from `backend\`, with the project venv:

   ```powershell
   # 1. Schema (must precede all imports)
   python manage.py migrate

   # 2. Chart of accounts: 185 accounts + 3 segments + SegmentAccountMap
   #    (incl. opening-equity role) + FY2026
   python manage.py import_coa --company STMIET --fiscal-year 2026 `
       --file excel-files/September/CHART-OF-ACCOUNTS_REVISED-SEPT-2026.xlsx

   # 3. Fiscal periods (P9 = September; 13th = year-end adjustment)
   python manage.py seed_fiscal_periods --company STMIET --year 2026 --periods 13

   # 4. Cash: 11 funded banks + 4 PCF custodian funds + custodian users;
   #    --post-opening posts the cash opening JE into P9
   python manage.py import_cash_summary --company STMIET --post-opening `
       --file excel-files/September/CASH-SEPTEMBER-1-2026.xlsx

   # 5. Supplier master (8)
   python manage.py import_suppliers --company STMIET `
       --file excel-files/September/LIST-OF-SUPPLIERS-SEPTEMBER-01-2026.xlsx

   # 6. Customer master (123)
   python manage.py import_customers --company STMIET `
       --file excel-files/customers_20260904_132120.csv

   # 7. Fixed assets (54): balanced opening JEs Dr Asset | Cr Accum Dep | Cr equity
   python manage.py import_fixed_assets --as-of 2026-09-01 `
       --file excel-files/September/SEPTEMBER-1-2026-_-FIXED-ASSETS.xlsx `
       --mapping excel-files/fixed-assets-mapping.json
   ```

   Notes:
   - **The opening balance IS steps 4 + 7** — confirmed cash-only: step 4 posts
     the cash/PCF opening as `OB-SEP1-ALL` (Dr Cash 1,862,959.78 | Cr the
     segment opening-equity plug), and step 7 posts one balanced JE per asset
     (Dr Asset | Cr Accum Dep | Cr opening equity). No separate opening-balances
     import is needed; AR/AP/inventory open at zero.
   - The `import_opening_balances` command still exists (for any future period
     with carried-forward balances) — it posts one balanced JE per segment
     (`OB-<prefix>-<SEG>`/`OB-...-ALL`), auto-plugs imbalances to the segment's
     `opening_equity`, and its `--no-plug` flag makes an imbalance fail loudly.
   - PNB Savings `0.00` is out of scope (no COA account yet).

### Source-file manifest

| File | Used by | Status |
|---|---|---|
| `excel-files/September/CHART-OF-ACCOUNTS_REVISED-SEPT-2026.xlsx` | `import_coa` | present |
| `excel-files/September/CASH-SEPTEMBER-1-2026.xlsx` | `import_cash_summary` | present — **the opening balance** (1,862,959.78) |
| `excel-files/September/LIST-OF-SUPPLIERS-SEPTEMBER-01-2026.xlsx` | `import_suppliers` | present |
| `excel-files/September/SEPTEMBER-1-2026-_-FIXED-ASSETS.xlsx` | `import_fixed_assets` | present — posts its own opening JEs (NBV 18,241,242.71) |
| `excel-files/customers_20260904_132120.csv` | `import_customers` | tracked |
| `excel-files/fixed-assets-mapping.json` | `import_fixed_assets` | tracked |

No `OPENING-BALANCES.xlsx` is required — finance head confirmed
receivables/payables/inventory open at zero.

---

## D. Post-import (once the app is live)

- Create application users and roles via `/settings/users/`:
  - `staff` (Leaslyn/Quibong — prepare RFPs/CVs, release vouchers)
  - `head` (Alywin — checks/approves, CONSO, clears CVs)
  - `coo` (CNR/signing above thresholds)
  with `UserProfile.approval_role` set accordingly. Cash custodian users are
  already seeded by step C.4.

---

## E. Verification gate (do this after C, before declaring go-live)

1. **Opening-position tie-out** — the system Trial Balance as of `2026-09-01`
   shows:
   - **Cash 1,862,959.78** — matches the CASH workbook total; 11 funded banks +
     4 PCF custodian funds, per-account balances equal the `Beginning Balances`
     column.
   - **Fixed assets: cost 22,359,081.01 · accumulated dep 4,117,838.30 · NBV
     18,241,242.71** — matches the FIXED-ASSETS workbook (54 assets).
   - Debits = Credits (the equity side is the segment opening-equity plugs).
2. **Counts** (foundation screens): COA 185 · suppliers 8 · customers 123 ·
   banks 11 · PCF 4 · fixed assets 54.
3. **Opening journal entries** — posting screen: `OB-SEP1-ALL` and the 54 asset
   opening JEs all `POSTED`. `GeneralLedger` for their entries matches the
   workbook totals.
4. **Statements generate** — Income Statement / SFP / CoS / TE / SOCE render
   for September (reporting templates auto-seed on first access — no extra
   step).
5. **Month-end close** — `/reports/month-end-close/` shows the four steps and
   the "Close period" button is disabled until all four are done; marking
   `close`/`appropriations` posts the §13 closing JEs.

---

## F. Post-pilot decision (after the online test)

The pilot data may be **real** or **throwaway** — decide before importing, then
apply the matching lane here.

- **Continue (real data):** keep the DB as production. Upgrade the web service
  to **Starter (~$7/mo)** in the dashboard (no redeploy). The team keeps working
  from the same data that was tested.
- **Reset (throwaway figures):** the local DB was never touched, so a reset is
  zero-risk. Either **delete the service + Postgres** from the Render dashboard
  (later re-create per Section A) or **recreate just the database** (drop/reset
  from the dashboard), then re-run Section C from scratch — every importer is
  idempotent, so a fresh DB imports cleanly in one pass.

---

## Red flags / rollback notes

- **Never** run `seed_demo` or `flush_demo` on production.
- If an import fails mid-run: fix the file and re-run — each importer skips
  what already exists (upsert by code, `entry_no` for JEs, `asset_no`).
- A mistakenly posted OB can be reversed with the normal UI reversal (ADR-005);
  reversing before re-importing avoids `entry_no` collisions.
- If carried-forward balances appear later (e.g., before the Dec-2026 close),
  use `import_opening_balances` with a fresh `--entry-prefix` and `--as-of` —
  it skips only identical `entry_no`s, so duplicate prefixes double-post.
- Scheduler/cron wiring (`run_scheduler --loop`) is a post-go-live follow-up.