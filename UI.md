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

### 1b. Executive Dashboard — the 4-zone finance view (ADR-046)

`/` is the management bird's-eye view, derived live from the posted GL
(`apps/ui/services.py::executive_dashboard_context`):

- **Zone A — the big 8:** Revenue YTD, Expenses YTD, Net Income YTD, Cash
  Position, Gross Profit Margin, Net Profit Margin, AR Outstanding and AP
  Outstanding — each with a MoM trend pill, drill-down link, and an icon
  bubble. A segment pill filter (DHPP / DMIE / OPS / All) re-scopes every
  GL-derived number.
- **Zone B — 4 charts** (self-hosted Chart.js): Revenue vs Expenses (12 mo),
  Cash Flow (cash in vs out), Segment Performance (grouped bars), and Expense
  Breakdown (doughnut with center total). KPI math mirrors the statement
  builders (`reporting/services.py`) so dashboard ratios equal the printed
  Income Statement's GPM/NPM.
- **Zone C — aging snapshots:** AR and AP bucket bars (0-30 → 120+) that link
  to the full aging registers.
- **Zone D — operational status:** disbursement pipeline (pending / awaiting
  payment / posted), waiting-on-you approvals, reversal requests, unposted
  documents, and the month-end close checklist.

### Verse of the week

Every page footer and the login screen carry a rotating **ESV Bible verse of
the week** — 52 verses (stewardship/work themes mixed with the gospel) cycle
by ISO week, one per week for the whole year (`apps/ui/verses.py`). ESV®
attribution is shown via the tooltip on the mark.

### Role-based screen access (ADR-047)

Each account carries **checkbox grants** (user management → Screen access)
that decide which modules it can open — enforced everywhere: the sidebar only
lists granted screens, and anything else answers **403**, even a hand-typed
URL, an HTMX fragment, an export or the API.

- **Head** prevails as overall approver and viewer: all screens by default
  (a superadmin may still narrow an account deliberately).
- **Staff** gets the full work set; **Settings** and **User Management**
  belong to the superadmin and the Head.
- The **COO** can be locked to just Dashboard + My Approvals and still signs
  CNR items — Approve/Clear/Reject-with-note live inside the inbox
  (`_safe_next` keeps every redirect same-site).
- Leaving the grid at a role's defaults stores nothing, so the account keeps
  following the role template as it evolves.

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
  each step, then **Close period**. Marking **close** posts the §13 closing
  JEs (revenue/expense → Capital, per segment) and **appropriations** posts
  the reserve JE when the COA carries the reserve accounts (current COA:
  none, so it's a no-op) — the posted entries appear on the page. The fiscal
  period locks when closed (posting §17: no back-posting); closing early is
  blocked until all four steps are done, and a failed close/appropriation
  posting leaves its step undone.

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
    ₱2,500; advance &lt; total). An optional **Master Purchase Order** picker
    (scoped to the chosen vendor, only approved POs with remaining balance)
    links the disbursement to its committing order (ADR-042). Picking a PO
    pre-fills the vendor, segment, and the distribution grid (description +
    amount + the PO line's GL account) over **blank lines only** — manual
    entries are never overwritten. The grid supports **per-line removal**
    (&times;) and **drag-to-reorder** (⋮⋮ handle); re-picking the same PO
    re-populates seamlessly.
  - **Detail** (`/ap/rfps/<id>/`) — document view with distribution table,
    TOTAL AMOUNT / ADVANCE CREDIT foot, and the ADR-020 approval chain:
    **Requested by → Checked / Recommending → Accounting Manager →
    Finance Manager → CNR (over ₱100k only)**. Buttons appear per status:
    Submit, then one approve button per role. Different users must hold each
    role (same-person rule, ADR-020). A linked PO renders as a chip linking
    back to the PO detail page. After finance approval the RFP is
    ready for the CONSO batch via the API.
- **Purchase Orders** (`/ap/pos/`) — `YYYY-SEQ` commitment documents
  (PO_LIMDON layout, ADR-042): vendor, PO date, particulars, and the
  PR/QTY/UNIT/DESCRIPTION/PRICE/AMOUNT line grid with
  DISCOUNT / SUBTOTAL / VAT / OTHER / TOTAL foot. Each line may carry an
  **optional GL account** that the RFP form uses to pre-fill expense lines.
  - **+ New PO** (`/ap/pos/new/`) — vendor, date, line grid, totals, payment
    terms & contract duration, deliver-to block; saved as **prepared**.
  - **Detail** (`/ap/pos/<id>/`) — document view with VENDOR / GRAND TOTAL /
    BILLED / AVAILABLE (amount − reserved − billed) and the approval chain
    (same matrix as the RFP). Submit → head approve (one-click fast-path) →
    optional CNR above ₱100k → **approved**; Head can **Close** an approved PO
    to stop further RFP references. Rejected POs return for **Revise**.
  - **Print** (`/ap/pos/<id>/print/`) — the template layout (header block,
    line table, totals, terms / deliver-to, signature lines) for PDF.
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

### 5b. Billing (Intercompany STPC / Third-Party)

- **Billing Transactions** (`/billing/`) — BI-YYYY-#### billings of two types:
  **Intercompany Billing – STPC** and **Third-Party Billing**.
  - **+ New billing** (`/billing/new/`) — pick the type, a party (shared
    supplier/customer picker; STPC default for intercompany), and optionally a
    **posted RFP as the basis**. Picking an RFP pre-fills the party, segment and
    the **Account Distribution** grid (COA | Account Name | Segment | Cost
    Center | Description | Debit | Credit). Debits must equal credits.
  - **Detail** (`/billing/<id>/`) — document view + lifecycle buttons:
    **Submit → Approve (Accounting & Finance Head) → Post to General Journal**,
    with reject/return-to-draft. Posting builds the JE from the grid; when based
    on an RFP, the RFP number lands in the JE Note/Reference and credit lines on
    **15550 / 15560** record `RFP <no> — billed <amount>` (visible in the
    General Journal's **Note / Reference** column).

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

### 8. Exporting data (every register & every document)

Every register / list screen (COA, customers, suppliers, RFP, CV, POs,
CONSO, advances, banks, cycles, aging AR/AP, reconciliations, cash short,
transfers, collections summary, COLLECTIBLES, assets, fleet fuel, tax
VAT/WHT/calendar/provisions, month-end close, general journal, TB,
statements, cash flow) carries an **Export** dropdown — **XLSX / CSV /
PDF** — rendered by the shared
`apps/ui/templates/ui/partials/export_buttons.html`. The button keeps the
screen's current filters (date ranges, segment, cycle, aging `as_of`,
tax period) so the download matches exactly what the user sees.

Document detail screens go one step further with per-document downloads:
RFP (**ACCTG-FOR-012**), CV (**ACCTG-FOR-010**), PCF vouchers
(**ACCTG-FOR-002**), JE, CONSO, fixed assets, and AR receipt each offer
form-faithful **PDF** plus **XLSX / CSV**. PDFs default to A5 for the
voucher forms (A4 for the JE / CONSO / workpapers) and honor `?paper=`.

All formats flow through the single export engine in
`apps/core/exports.py` (`table_export` + `csv_response` / `pdf_response`):
- **XLSX** — real numeric cells for `money_cols` (signed amounts, no text),
  frozen header, title row, and a **totals row** where the report has one
  (aging, collections, advances, journal).
- **CSV** — RFC 4180 with the same column set.
- **PDF** — landscape table layout with wrapping cells, so wide registers
  (collections summary, 23-column PCF workpaper) never clip.

Both the dropdown (`?format=xlsx`) and the per-document
`/…/<id>/export/<fmt>/` routes return RFC-munged filenames with the
`Content-Disposition: attachment` header.

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
- Templates live in `apps/ui/templates/ui/…` (organized by bounded context:
  `ar/`, `ap/`, `cash/`, `posting/`, `foundation/`, `reporting/`); the
  stylesheet is built from `backend/frontend/src/input.css` with Tailwind
  (content globs cover `apps/**/templates/**`).
- **Reusable partials** in `apps/ui/templates/ui/partials/` (ADR-039):
  `page_header`, `list_card`, `form_card`, `status_badge`, `document_shell`,
  `workflow_actions` (+ `workflow/rfp_actions.html`, `workflow/cv_actions.html`),
  `report_toolbar`, `export_buttons`, `audit_trail`. Screens compose these
  via a custom `{% capture %}` tag (`templatetags/ui_filters.py`) that renders
  a block into a context var for the partial's `…_html` parameter.
- **Static JS modules** in `backend/static/js/`: `base.js` (sidebar, CSRF,
  toast, searchable combobox, report-format redirect, onafterprint close),
  `line-grid.js` (JE/RFP/PCV line totals), `gross-net-calc.js` (gross − WHT = net),
  `toggle-block.js` (show/hide), `template-rows.js` (clone-from-template rows,
  e.g. supplier contacts). Per-screen modules load via `{% block extra_js %}`.
- HTMX (1.9.12) is vendored at `backend/static/js/htmx.min.js`; swapped
  fragments (`_rfp_row`, `_cv_row`, `_asset_rows`, `_coa_rows`,
  `_cash_short_row`) re-bind partial JS via `htmx:afterSwap`.

## Tests

```powershell
cd backend
python -m pytest -q    # 600+ tests: API contracts + UI smoke tests + E2E workflow
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

`apps/ui/test_exports_matrix.py` is the export matrix: every document and
register export × {pdf, xlsx, csv} asserting 200, the right Content-Type,
real magic bytes, `attachment` filenames, and for XLSX that numbers land in
numeric cells — including the empty-database register smoke so a fresh
install can never ship a broken download.

`apps/ui/test_exec_dashboard.py` pins the executive dashboard contract:
all four zones render, the KPI set is complete, the chart JSON blob is valid,
segment filtering flips the figures, and every KPI links to its source screen.

`apps/ui/test_user_management_ui.py` covers user management CRUD — create /
edit / deactivate / reactivate by superadmin and the Accounting & Finance
Head, the head-blocked-from-superadmins rule, self-deactivation blocking, and
the standalone create/edit forms.

`apps/ui/test_frontend_conventions.py` is the architecture guard (ADR-046):
config-driven sidebar, resolvable nav URLs, existing icon symbols, per-screen
filter specs, dual-view table fragments, self-hosted charts and palette
discipline — regressions fail CI instead of drifting.

## Tailwind content sources
- `backend/frontend/tailwind.config.js` scans BOTH `apps/**/templates/**/*.html`
  and `static/js/**/*.js`. This second glob is required: `base.js` (searchable
  combobox, toast) generates its DOM classes at runtime, so classes that only
  appear there (`.h-4`, `.max-h-56`, `.z-50`, ...) would otherwise never be
  emitted in `output.css`. Always add its classes to the JS glob when extending
  the widget, or inline the style as a fallback.
