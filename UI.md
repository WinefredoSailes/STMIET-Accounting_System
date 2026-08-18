# STMIET Accounting System — UI Guide

Server-rendered staff application (Django templates + HTMX + Tailwind).
Every screen is a thin layer over the same bounded-context services the
DRF API uses (ADR-036), so what you see here is always what the API would do.

## Quick start

```powershell
# 1. Build the Tailwind stylesheet (once, or keep `npm run dev` running while editing templates)
cd backend\frontend
npm install
npm run build

# 2. Apply migrations, import the chart of accounts, and create your first operator
cd ..\..\backend
python manage.py migrate
python manage.py import_coa   # reads excel-files/COA-STMIET-2026.xlsx (392 accounts)
python manage.py createsuperuser

# 3. Run
python manage.py runserver
# open http://127.0.0.1:8000/ and sign in
```

Optional: seed a realistic January-2026 demo dataset (idempotent; users
checker/acctg/fin/cnr/cashier, password `Demo@2026`):

```powershell
python manage.py seed_demo   # posted AR/RFP/CONSO/CV/transfer/advance + cycles + reports
```

Segments (DHPP/DMIE/OPS) with their COA key digit (0/3/6) and full names are
maintained in Django admin (Foundation → Segments); screens render them from
the database, never from hardcoded strings.

## Modules

### 1. Dashboard (`/`)

- **Fiscal period card** — current open period, or "—" if none.
- **Journal entries card** — totals / posted / draft counts.
- **Month-end close card** — step states for the current period, with a link
  to the close screen.
- **Recent entries** — last 8 journal entries with status badges.

### 2. Journal (`/journal/`)

- **General Journal** (`/journal/general/`) — the posted-entry register in
  the workbook layout (`General_Journal_DHPP…xlsx` PAYMENT RECEIPTS /
  UPON DELIVERY sheets): Date | Cycle | Ref # | Supplier/Customer | PO # |
  Description | CoA | Account Name | Debit | Credit, with a per-entry
  balanced OK / NOT BALANCE flag and total debits/credits/variance at the
  foot. Filter by date range and segment. Party names resolve from the AR/AP
  document masters.
- **List** (`/journal/`) — last 100 entries, newest first; click an entry no.
  for the detail view.
- **Detail** (`/journal/<id>/`) — header facts (date, segment, source doc,
  balance), line grid with debit/credit totals, and actions:
  - **Post** — validates and posts the entry (ADR-004: immutable once
    posted; never force-balanced, ADR-002). Entries **over ₱100,000 require
    the "Approve" checkbox** (ADR-033 approval threshold) — otherwise the
    service rejects the post.
  - **Reverse** — not implemented in v1; corrections are planned as
    reversing entries (ADR-004).
- **New entry** (`/journal/new/`) — header (date, segment, source type /
  number, description) plus an editable line grid. Use **+ Add line** for
  more rows; the balance hint shows Balanced / Difference live. Blank rows
  are skipped. The entry is saved as a **draft** with the next JE number.

### 3. Reports

- **Chart of Accounts** (`/foundation/coa/`) — read-only listing of all
  postable accounts (code, name, segment, type, normal balance) with
  search + segment/type filters; the same 392 accounts imported from
  `COA-STMIET-2026.xlsx`.
- **Cash Flow Statement** (`/reports/cash-flow/`) — generated from weekly
  cycle activities (ADR-031): operating / investing / financing sections,
  NET CHANGE IN CASH, beginning/end balances, ADB adjustments, and the
  identity check (Net Inc = End − Beg + ADB).
- **Trial Balance** (`/reports/trial-balance/`) — signed balances from
  posted GL (ADR-005) as of a date, optionally filtered to one segment.
  Debits and credits shown per account's sign; totals at the foot.
- **Statements** (`/reports/is/`, `/sfp/`, `/cos/`, `/te/`, `/soce/`) —
  pick a period and **Generate** to run the template engine (ADR-035) and
  view the persisted snapshot with per-segment columns (rendered from the
  Segment master) plus GRAND. Identity checks (e.g. SFP Assets =
  Liabilities + Equity) are shown as OK / FAILED.
- **Month-End Close** (`/reports/month-end-close/`) — the four steps:
  **accruals → recon → close → appropriations**. Click **Mark done** on
  each step, then **Close period**. The fiscal period locks when closed
  (posting §17: no back-posting). Closing early is blocked until all four
  steps are done.

### 4. Receivables (AR)

- **AR Aging / Register** (`/ar/aging/`) — aging buckets 0-30 / 31-60 /
  61-90 / 91-120 / 120+ from open invoice balances as of a date, plus the
  per-invoice register (invoice, customer, date, segment, status, age,
  balance) with a total. **Refresh** re-runs the derivation.
- **Customers** (`/ar/customers/`) — customer master (ADR-007): code, name,
  group, segment, pricing tier, contact. **+ New customer** (`/ar/customers/new/`)
  creates the master record.
- **Acknowledgment Receipts** (`/ar/receipts/`) — AR-YYYY-SEQ receipts that
  post on creation (ADR-015), showing method and check number.
  **+ New receipt** (`/ar/receipts/new/`) follows the ACCTG-FOR-005 layout:
  customer, TR date, amount, cash account, payment method (cash / check /
  gcash / others) with check number. Saving allocates the next AR number and
  posts the `cash.collection` JE (Dr Cash | Cr Unearned) immediately.

### 5. Payables (AP)

- **Advances to Employees** (`/ap/advances/`) — the standing-advance ledger
  (ADR-021): employee, kind (officer / salary / reimbursement), segment,
  granted date, amount, liquidated, outstanding, status. Each open row has
  an inline liquidation form (amount + date) that walks the advance toward
  `liquidated` (over-liquidation is rejected).
- **Suppliers** (`/ap/suppliers/`) — vendor master (ADR-024). **+ New supplier**
  (`/ap/suppliers/new/`) adds a vendor with default segment.
- **RFPs** (`/ap/rfps/`) — A#### payment requests (ACCTG-FOR-012 layout)
  with particulars, segment, amount, and workflow status (ADR-018 / ADR-020).
  - **+ New RFP** (`/ap/rfps/new/`) — payee info, date of request, purpose /
    segment, and a distribution-charges line grid (account, segment,
    description, amount) with a running total; the P20,000 advance credit
    defaults and the total amount is validated against the lines (min
    ₱2,500; advance &lt; total).
  - **Detail** (`/ap/rfps/<id>/`) — document view with distribution table,
    TOTAL AMOUNT / ADVANCE CREDIT foot, and the ADR-020 approval chain:
    **Requested by → Checked / Recommending → Accounting Manager →
    Finance Manager → CNR (over ₱100k only)**. Buttons appear per status:
    Submit, then one approve button per role. Different users must hold each
    role (same-person rule, ADR-020). After finance approval the RFP is
    ready for the CONSO batch via the API.
- **Check Vouchers** (`/ap/cv/`) — CV-YYYY-#### (ACCTG-FOR-010 layout:
  payee info, date of request, check issued & no, distribution charges
  table, gross / WHT / net, signature blocks).
  - **+ New check voucher** (`/ap/cv/new/`) — pick an **approved RFP**
    (fin/CNR-approved, no CV yet) — payee, distribution table, and gross
    auto-fill from it; enter check no., bank account, WHT; net is computed.
    Issuing posts the 7.4 JE (Dr AP | Cr Cash + WHT) and allocates the next
    CV number.
  - **Detail** (`/ap/cv/<id>/`) — document view + lifecycle buttons:
    **Sign (CNR) → Release (treasury) → Mark cleared**, tracking signed_by /
    released_by; earlier steps are blocked out of order.
- **CONSO Batches** (`/ap/conso/`) — CONSO-YYYY-## batches (ADR-018, 7.3).
  - **+ New batch** (`/ap/conso/new/`) opens a batch; the detail screen
    (`/ap/conso/<id>/`) shows members with per-RFP status and a running
    total. Add finance-approved RFPs that aren't in a batch yet, then
    **Post batch** — every member RFP's JE posts atomically (Dr charge
    lines | Cr advances + AP balance).

### 6. Cash

- **Bank Accounts** (`/cash/banks/`) — bank master with GL mapping, segment,
  and ADB requirement (ADR-010 / ADR-016). **+ New bank account**
  (`/cash/banks/new/`) picks the GL account and segment.
- **Weekly Cash Cycles** (`/cash/cycles/`) — Tue–Mon cycles with opening /
  closing balances and status (ADR-013 / ADR-028). **+ Generate cycles**
  (`/cash/cycles/generate/`) creates the Tue–Mon cycles for a segment over a
  date range (idempotent for existing weeks).
- **Petty Cash Funds** (`/cash/pcf/`) — the 3 imprest funds (General /
  Maintenance / Technical) with custodian, imprest, GL account, and 85%
  trigger (ADR-027). **+ New fund** (`/cash/pcf/new/`) sets up a fund with
  an unclaimed asset GL account.
- **Bank Reconciliation** (`/cash/recon/`) — per cycle per bank (ADR-026).
  **+ Reconcile** (`/cash/recon/new/`) picks the weekly cycle, then the
  bank; book balance is computed from posted GL up to cycle end; enter the
  bank statement balance and the difference is flagged resolved/open.
- **Daily Collections JE Summary** (`/cash/collections-summary/`) — the
  cashier worksheet per weekly cycle, matching the uploaded
  `DAILY COLLECTION JOURNAL ENTRIES SUMMARY (CYCLE JULY 15-21, 2025)...xlsx`:
  one row per AR receipt (DATE / AR-SI# / outlet / particulars / PO /
  CASH ON HAND DR-CR / per-bank DUE FROM banks columns / AR DR-CR /
  AP DR-CR / TOTAL / REMARKS), day subtotal rows, grand TOTAL, and the
  signature block with TOTAL DEBITS / TOTAL CREDITS / VARIANCE (= 0).
- **Cash Short** (`/cash/short/`) — expected vs actual per cycle
  (ADR-029/030). **+ Record variance** enters expected/actual + cause;
  approval is tracked on the worksheet (a reconciliation only — no JE
  until approved and adjusted).
- **Inter-Account Transfers** (`/cash/transfers/`) — transfer ledger + the
  form (from bank (credit) → to bank (debit), amount, purpose, date);
  posting runs TransferService (Dr Cash-To | Cr Cash-From, purpose
  required — ADR-030) and links the JE.
- **COLLECTIBLES Worksheet** (`/cash/collectibles/`) — per cycle, the two
  departments (Distribution: gross mark-up = client paid − depot paid;
  F&A: net cash position) regenerated from posted cycle activities
  (ADR-029). A worksheet, never a JE.
- **Petty Cash Vouchers** (`/cash/pcf/replenishments/`) — replenishment
  requests in the ACCTG-FOR-002 layout.
  - **+ New petty cash voucher** (`/cash/pcf/replenish/`) — payee name,
    date of request, reference, and a distribution-charges line grid
    (purpose / entity / segment / cost center / GL account / amount) with
    running total. The expenses become the replenishment's liquidation
    breakdown.
  - **Detail** (`/cash/pcf/replenishments/<id>/`) — voucher document view;
    **Post replenishment JE** runs Dr expenses | Cr cash (imprest restored).

### 7. Fixed Assets

- **Assets** (`/assets/`) — FA-YYYY-#### register: category, segment,
  acquisition date, cost, status (ADR-034). Asset numbers link to the detail
  screen.
- **Detail** (`/assets/<id>/`) — cost, accumulated depreciation, net book
  value, and the straight-line schedule. **Post depreciation** runs one
  month's 9.2 JE (Dr expense | Cr accum dep). **Dispose asset** opens the
  9.3 form (disposal date, proceeds, cash account, reason).
- **+ New asset** (`/assets/new/`) — category (useful life), segment,
  acquisition date, cost / residual / fees, funding source (cash / AP /
  loan). Saving assigns FA-YYYY-#### and posts the 9.1 acquisition JE.

## How it works (for developers)

- Long registers (general journal, COA, aging, advances, transfers) are
  paginated at 50 rows/page; filters survive across pages (`?page=` +
  preserved querystring). Totals (journal debits/credits, aging
  outstanding) always cover the whole filtered set, not just the page.
- Amounts render with thousand separators via the `money` filter
  (`apps/ui/templatetags/ui_filters.py`) — no raw `floatformat` on money.
- Layout is responsive: sidebar collapses to an off-canvas menu under
  `lg:` (hamburger in the top bar), tables scroll horizontally, and page
  headers/filter bars stack vertically on small screens.
- `apps/ui/views.py` — thin view layer; mutations call the context services
  (`apps.posting.services`, `apps.reporting.services`, …). Business rules
  never live in the UI app (ADR-009).
- `apps/ui/services.py` — read models (lists, TB rows, statement context,
  month-end close context) so templates stay logic-free.
- `apps/ui/urls.py` — mounted at `/`; API remains under `api/v1/`.
- Templates live in `apps/ui/templates/ui/…`; the stylesheet is built from
  `backend/frontend/src/input.css` with Tailwind (content globs cover
  `apps/**/templates/**`).
- HTMX (1.9.12) is vendored at `backend/static/js/htmx.min.js` for future
  partial updates; JE line grids use a small vanilla-JS snippet.

## Tests

```powershell
cd backend
python -m pytest -q    # 154 tests: API contracts + UI smoke tests + E2E workflow
python manage.py check
```

`apps/ui/tests.py` covers: login flow, every screen rendering, draft JE
creation from the form, posting with and without approval, TB / statement
generation, the full month-end close lifecycle, customer / supplier / bank
creation, AR receipt posting, the RFP create → submit → 4-role approval →
CNR chain (incl. the same-person rule), weekly cycle generation, the full
asset lifecycle (acquire → depreciate → dispose), check voucher creation
(with WHT split) and the sign → release → clear lifecycle, PCF fund setup
and replenishment request → post, bank reconciliation (open + resolved),
cash short record → approve, and the CONSO batch open → add RFP → post
lifecycle (incl. the all-approved gate).

`apps/ui/test_e2e.py` is the end-to-end workflow: customer → AR invoice →
collection JE → RFP chain (incl. CNR escalation) → CONSO post → CV
lifecycle → transfer → advance liquidation → weekly cycles → COLLECTIBLES
→ cash flow statement → renders every register screen (general journal,
cash flow, collectibles, aging, advances, transfers, COA) and re-checks
posted-entry immutability.
