# Go-Live: Imports Runbook (Render + fresh production Postgres)

Target: **Saturday, Sept 12 2026** — deploy STMIET Accounting System to Render
(Dockerfile image, `config.settings.prod`) against a **fresh production
PostgreSQL**, then load the real Sept-1-2026 master data and opening balances.

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

---

## B. One-time import sequence (local machine → production Postgres)

Because `*.xlsx` sources are git-ignored and the container filesystem is
ephemeral, the imports run **once from your machine against the Render
Postgres**. Use the same code version that is (about to be) deployed.

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

   # 8. Full opening balances (AR / AP / inventory / capital) — into P9
   python manage.py import_opening_balances --company STMIET --as-of 2026-09-01 `
       --entry-prefix OB-SEP1 `
       --file excel-files/September/OPENING-BALANCES.xlsx
   ```

   Notes:
   - Step 8 posts `OB-SEP1-DHPP`, `OB-SEP1-DMIE`, `OB-SEP1-OPS`, `OB-SEP1-ALL`
     (shared). It auto-plugs any imbalance to the segment's `opening_equity`
     account; add `--no-plug` to fail loudly instead of plugging.
   - **Never re-run step 8 with a different `--entry-prefix`/`--as-of`** — the
     importer skips only identical `entry_no`s, so a new prefix posts a second
     opening set. On an existing DB, verify markers (`OB-2026-*`, `OB-SEP1-ALL`)
     instead of re-running.
   - PNB Savings `0.00` is out of scope (no COA account yet).

### Source-file manifest

| File | Used by | Status |
|---|---|---|
| `excel-files/September/CHART-OF-ACCOUNTS_REVISED-SEPT-2026.xlsx` | `import_coa` | present |
| `excel-files/September/CASH-SEPTEMBER-1-2026.xlsx` | `import_cash_summary` | present |
| `excel-files/September/LIST-OF-SUPPLIERS-SEPTEMBER-01-2026.xlsx` | `import_suppliers` | place before B |
| `excel-files/September/SEPTEMBER-1-2026-_-FIXED-ASSETS.xlsx` | `import_fixed_assets` | place before B |
| `excel-files/September/OPENING-BALANCES.xlsx` (columns `COA \| NORMAL BALANCE \| ACCOUNT TITLES \| SEGMENT \| OPENING DR \| OPENING CR`; derive from `excel-files/TRIAL-BALANCE.xlsx`) | `import_opening_balances` | place before B |
| `excel-files/customers_20260904_132120.csv` | `import_customers` | tracked |
| `excel-files/fixed-assets-mapping.json` | `import_fixed_assets` | tracked |

---

## C. Post-import (once the app is live)

- Create application users and roles via `/settings/users/`:
  - `staff` (Leaslyn/Quibong — prepare RFPs/CVs, release vouchers)
  - `head` (Alywin — checks/approves, CONSO, clears CVs)
  - `coo` (CNR/signing above thresholds)
  with `UserProfile.approval_role` set accordingly. Cash custodian users are
  already seeded by step B.4.

---

## D. Verification gate (do this after B, before declaring go-live)

1. **Trial balance tie-out** — `/reports/trial-balance/` as of `2026-09-01`
   equals `excel-files/TRIAL-BALANCE.xlsx` (reporting tests assert the TB
   mirror). Confirm Debits = Credits and no plug accounts materialize
   unexpectedly.
2. **Counts** (foundation screens): COA 185 · suppliers 8 · customers 123 ·
   banks 11 · PCF 4 · fixed assets 54.
3. **Opening journal entries** — posting screen: `OB-SEP1-*` and the 54 asset
   opening JEs all `POSTED`. `GeneralLedger` for their entries matches the
   workbook.
4. **Statements generate** — Income Statement / SFP / CoS / TE / SOCE render
   for September (reporting templates auto-seed on first access — no extra
   step).
5. **Month-end close** — `/reports/month-end-close/` shows the four steps and
   the "Close period" button is disabled until all four are done; marking
   `close`/`appropriations` posts the §13 closing JEs.

---

## Red flags / rollback notes

- **Never** run `seed_demo` or `flush_demo` on production.
- If an import fails mid-run: fix the file and re-run — each importer skips
  what already exists (upsert by code, `entry_no` for JEs, `asset_no`).
- A mistakenly posted OB can be reversed with the normal UI reversal (ADR-005);
  reversing before re-importing avoids `entry_no` collisions.
- FY2027 (for the Dec-2026 close roll-over) and the scheduler/cron wiring are
  out of scope for this runbook.