# STMIET Accounting ERP — Project Context (Pitch-Ready)

> Single entry-point document for sales, demos, onboarding, and scoping.
> Detail specs live in: `ARCHITECTURE.md`, `DOMAIN_MODEL.md`, `POSTING_RULES.md`,
> `SUBSIDIARY-LEDGERS-AND-MASTER-DATA.md`, `BUILD-PLAN.md`, `USERGUIDE.md`,
> `UAT-GUIDE.md`, `UI.md`, `adr/`, `workshop-outputs/`.
> Status date: **29 Sept 2026**. Stage: **LIVE in production on Render —
> real users (accounting head + staff) working daily, live CI/CD via Render
> GitHub auto-deploys** (was: UAT-ready daily cash cycle).

---

## 1. What this system is (one paragraph)

A **custom Django ERP (not just basic accounting)** built for **Seven-Trent Machineries
Industrial Equipment Trading (sole proprietorship, E. Bagatua)**. It replaces
**40+ disconnected Excel files** with one audited system covering GL, AR, AP,
cash/treasury, inventory, fleet, fixed assets, billing, payroll-feed, tax, and
financial statements — segmented by **DHPP (fuel hauling), DMIE (industrial
equipment), OPS (operations)**. Server-rendered staff app (Django + HTMX +
Tailwind), REST API alongside it, PostgreSQL in production.

**Is it a customer ERP already? Yes.** It has masters, transactional ledgers,
approval workflows, posting engine, period close, executive dashboard, and
exports — i.e. an operational ERP scoped to this business, not a generic
bookkeeping tool.

---

## 2. Where it runs today

| Environment | Details |
|---|---|
| Local dev | `backend/manage.py runserver` → `http://127.0.0.1:8000/`, SQLite (`db.sqlite3`, ~2.5 MB), Tailwind build in `backend/frontend` (`npm install; npm run build`) |
| Prod **LIVE** | **Render Blueprint** (`render.yaml`): Docker web service `stmiet-accounting` + managed PostgreSQL 18 (`stmiet_accounting`). Real accounting head + staff in daily use. **CI/CD live:** push to `main` on GitHub (`WinefredoSailes/STMIET-Accounting_System`) → Render auto-deploys from Blueprint; `entrypoint.sh` runs `migrate --run-sync` + `collectstatic` then gunicorn; `/health/` gates blue-green swap (200 only when process + DB reply, else 503 — zero-downtime deploys). Prod-hardened: avatar persistence via `MEDIA_ROOT=/var/data/media` disk, favicon/robots probes answered, prod-log-driven fixes shipped (picker gating, statement export 500s, avatar 404s). |
| Media | Local `media/` in dev; `/var/data/media` persistent disk on Render (avatars). S3 document storage **not wired yet**. |
| Queue/cache | Redis/Celery **deferred** — `REDIS_URL` read but unused; no broker/tasks in code yet. |
| Auth | Session auth for UI; JWT + RBAC for `api/v1/`; role checkbox grants (see §6). |

Seed/demo: `python manage.py seed_demo` (idempotent Jan-2026 dataset, users
checker/acctg/fin/cnr/cashier, password `Demo@2026`). UAT uses real Sept-2026
masters (see §8).

---

## 3. Architecture (why it looks this way)

- **Modular monolith (ADR-009/010).** One Django project, one DB. AR ↔ GL ↔
  inventory are too tightly coupled for premature microservices. Split only on
  independent deployability/team ownership.
- **Event-driven posting (ADR-004).** Ops modules emit events
  (`sales.invoice_posted`, `cash.receipt.collected`, `payroll.run_completed`,
  `asset.depreciation_booked`, …) → `PostingService` matches `PostingRule` →
  creates balanced `JournalEntry` → updates `GeneralLedger`.
- **Immutable journal (ADR-005) + no force-balance (ADR-002).**
  POSTED entries are never edited; corrections are reversal + new JE.
  Debits must equal credits or posting is rejected.
- **Segment-tagged everything (ADR-011).** Every JE/transaction carries
  DHPP (`00`) / DMIE (`03`) / OPS (`06`). STPC (sister co.) currently shares
  DHPP accounts with a tag — **no dedicated STPC suffix** (known gap).
- **Unified document experience (ADR-043).** Every approval-tracked document
  shares one shape: service `create → submit → approve → reject → revise`,
  head approval = only GL gate, `ActionLog` per transition, one detail-shell UI
  (`document_shell` + timeline + `workflow_actions` + audit trail), list screens
  from `filter_specs` + `filter_bar`, exports honour filters.

Tech: Django 5.x + DRF, PostgreSQL (+JSONB), Redis deferred, HTMX 1.9.12
vendored, Tailwind, Chart.js self-hosted, WhiteNoise static, gunicorn + nginx
pattern in docs.

---

## 4. Modules: features, flows, and build status

### 4.1 Foundation / GL — ✅ built (Phase 1)
Models: `Company, Segment, FiscalYear, FiscalPeriod, Account (185 active, 5-digit),
JournalEntry + lines, PostingRule + lines, GeneralLedger`.
Features: COA import from Excel, TB (monthly + YTD, per segment), fiscal close
(no back-posting to closed periods), voucher/sequence registry
(AR-YYYY-SEQ, RFP A#### + gap tracking, CV-YYYY-####, BI-YYYY-####, FA-YYYY-####).
Flow: event → rule match → draft JE → approve (if > ₱100k) → post → GL balances.

### 4.2 AR (Order-to-Cash) — ✅ built (Phase 2)
Models: `Customer (123), SalesInvoice, CollectionReceipt, OfficialReceipt,
CashReceiptJournal, CreditNote, ReceiptAllocation, CycleLedger`.
Flow:
1. **Acknowledgment Receipt → New** (ACCTG-FOR-005): customer, date, amount,
   cash account, method (cash/check/gcash/others) → auto AR number → posts
   `cash.collection` JE immediately (Dr Cash | Cr Unearned 21000/21016/21023,
   or Cr AR 120xx when applying to prior AR).
2. Appears in **AR Aging / Register** (buckets 0-30/31-60/61-90/91-120/120+)
   + **Daily Collections Summary** + bank recon.
3. Cycle settlement is a **COLLECTIBLES-derived report (no JE)**; cash
   short/excess is a worksheet until approved.
Business rules: three-tier cycle pricing (Regular/Patron/Volume + per-cycle
snapshots); prepayment-first (client often pays before price confirmed —
unapplied → price confirm → applied → netted → carried forward); 120+ legacy
per-client macro sheets replaced by register.

### 4.3 AP (Procure-to-Pay) — ✅ built core (Phase 3); PR/RR/SI ⚠️ deferred
Models: `Supplier (8), PurchaseOrder + POLine, RFP, CONSO batch + items,
CheckVoucher, DisbursementVoucher, AdvanceToEmployee + liquidation`.
**RFP → CONSO → CV is the wired daily-cycle path.** PR / Receiving / Supplier
Invoice screens are **out of scope for UAT** (payable is entered at the RFP).
**PO (commitment, ADR-042) — ✅ built:** YYYY-SEQ, vendor/date/particulars,
PR/QTY/UNIT/DESCRIPTION/PRICE/AMOUNT grid, DISCOUNT/SUBTOTAL/VAT/OTHER/TOTAL,
optional per-line GL account feeding RFP pre-fill, payment terms + deliver-to.
PO never posts to GL; RFPs reserve then bill against it
(`AVAILABLE = total − reserved − billed`); Head can Close it.
**RFP canonical JE (RESOLUTION #5):**
`Dr Expense/Inventory/Asset {TOTAL} | Cr Advances-to-Employees 12070–76 {20,000} | Cr AP {TOTAL − 20,000}`.
Min **₱2,500** (below → petty cash). Balanced Dr = Cr enforced.

### 4.4 Cash & Bank (Treasury) — ✅ built (Phase 4)
`BankAccount (11 funded), PettyCashFund (4 custodians), BankReconciliation,
CashShort, InterAccountTransfer, WeeklyCycle, DailyCollections, COLLECTIBLES`.
- Weekly cycles **Tue→Mon**, idempotent generation, opening/closing balances.
- Recon per cycle per bank (book from posted GL vs statement; resolved/open).
- PCF: 85% drawdown trigger; below-₱2,500 expenses via PCV (ACCTG-FOR-002).
- Transfers: always **Dr Cash-To | Cr Cash-From**, purpose required, no amount
  threshold, head approval posts the JE.
- Cash Flow Statement generated from cycles with identity check
  (Net Inc = End − Beg + ADB).

### 4.5 Inventory — ✅ models + bridge design; fuel-log feed ⚠️ later wiring
`Product, ProductCategory, Warehouse (Dohinob/San Pedro/Office),
StockTransaction (GR/GI/TR/ADJ/SR), InventoryBalance (moving average),
PhysicalCount, InventoryValuation`.
Posting families §5.1–5.3 (advances vs AP paths; write-off Dr 632xx | Cr 130xx).
Phase 5 plan: API/webhook bridge from live Django inventory system +
reconciliation job + idempotent event dedupe. Fuel Inventory module exists but
**deactivated behind feature flag**.

### 4.6 Fleet — ✅ register built; live fuel-log feed ⚠️ later
`Vehicle, VehicleType, Trip, FuelConsumption, MaintenanceRecord,
VehicleAssignment`. UAT fleet report reads the fleet master only (8 fuel
tankers, boom truck ISUZU ELF JAR 7137, Big Horn YCS 373, E-Bike). Vehicles link
to `Asset` (17000–18650).

### 4.7 Fixed Assets — ✅ built (Phase 7)
`Asset (54), AssetCategory, DepreciationEntry, AssetDisposal`.
Straight-line monthly (`Dr 50110/616xx | Cr Accum Dep 17xxx`), disposal with
gain/loss (`Dr Cash + Accum Dep | Cr Asset + gain/loss 43070-96`; loss account
62000 in revised COA), fully-depreciated-still-in-use flag, Asset↔Vehicle link.

### 4.8 Billing (Intercompany STPC / Third-Party) — ✅ built
`BillingDocument (BI-YYYY-####, stpc | third_party, RFP basis,
draft → submitted → approved → posted) + BillingLine
(COA | Account Name | Segment | Cost Center | Description | Debit | Credit)`.
JE built from grid; RFP number in JE Note/Reference; 15550/15560 credit lines
record `RFP <no> — billed <amount>` (POSTING_RULES §18).

### 4.9 Payroll — ⚠️ skeleton + tax WHT only (Phase 6 future)
`Employee, PayrollPeriod, PayrollRun, PayrollItem (basic/OT/allowances/bonus/
13th + SSS/PHIC/HDMF EE+ER + WHT + gross/net), GovernmentRemittance`.
UAT scope is skeleton; feed contract is file-based v1 (SUMMARY + JE LINES
sheets → validate → preview → Alywin review → post), API `POST /payroll-feed`
is v2. Govt remittance itself routes via AP (RFP → AP-Others → CV → cash).

### 4.10 Reporting — ✅ built (Phase 8)
TB, IS (segment cols + GPM/Expense Ratio/NPM + 10% R&M & tithing appropriations),
SFP (Assets = Liab + Equity machine-checked), CoS by segment (+ liters rows),
Total Expenses (CGSE), SOCE (machine-checked), Weekly Collections, AR/AP Aging,
Inventory Valuation, Fleet Fuel, **Executive Dashboard (4 zones)**. Month-end
close: accruals → recon → close → appropriations; close posts §13 JEs and locks
the period.

### 4.11 Tax & Compliance — ✅ screens + services built (Phase 9/10)
See §7. UI at `/reports/tax/` (dashboard, `/vat/`, `/wht/`, `/provision/`,
`/calendar/`). 8 tax-app tests passing.

---

## 5. Approval workflows (exact, demo these)

### 5.1 Roles
| Role | Does | Typical account |
|---|---|---|
| `staff` | Prepares RFPs/CVs, posts receipts, **releases** CVs (treasury) | leaslyn, quibong |
| `head` | Checks + approves every RFP step, builds/posts CONSO, **clears** CVs | alywin |
| `coo` | Signs CVs; CNR approval on RFPs **> ₱100,000** only | CNR/COO |
| `superadmin` | User Management, customer-master edits, role grants | admin |

**Segregation (hard-enforced):** preparer (or CNR approver) cannot approve the
same RFP again; nobody holds two steps on one document — except Head holding
the checked/acctg/fin trio. JE postings **> ₱100,000 require approved status**.
**Notifications today:** amber badge on **My Approvals** + inbox (page-load
refresh, no email). Requesters check the document; rejection reason shows inline.

### 5.2 RFP lifecycle
`prepared → submitted → checked → acctg_approved → fin_approved → [cnr_approved if > ₱100k] → posted (via CONSO)`.
Buttons appear per status on **My Approvals** or the RFP page. **Reject with
note** (note required) at any awaiting step → `rejected` (who/when/reason shown)
→ preparer-only **Revise & resubmit** (prefilled) → back to `submitted`.
Posted RFPs cannot be rejected; fully-approved (≤ ₱100k) cannot be rejected —
only CONSO remains. Same chain + close/revise applies to **POs**
(`prepared → submitted → checked → acctg → fin → [cnr] → approved → closed`).

### 5.3 CONSO posting (the only GL gate for AP)
Head opens **CONSO → New**, adds finance-approved RFPs, **Post batch** —
**atomic**: every member JE posts at once (Dr charge lines | Cr advances + AP).
All-approved gate enforced; failures leave batch unposted.

### 5.4 CV lifecycle (money actually leaves here)
`created (staff) → signed (COO) → released (staff/treasury) → cleared (head)`.
Out-of-order steps blocked. **Only `cleared` posts:**
`Dr AP {gross} | Cr Cash {net} + Cr WHT 64110-16`. Created/signed/released JEs
stay DRAFT and are **invisible to GL/TB/statements** — month-end must confirm
all released CVs are cleared.

### 5.5 Transfer lifecycle
`requested → submitted → approved (posts Dr Cash-To | Cr Cash-From)`,
or `rejected (note required) → revise (Edit) → resubmit`. Batch entry form takes
one row per leg (From → To → Amount → Purpose → Check No.); blank skipped,
invalid row rejects whole batch.

### 5.6 Manual JE + period close gates
JE form saves as **draft** with next JE number and live balance hint; **Post**
validates; > ₱100k needs Approve checkbox (head-only via API `approve=true`).
Reversal is reversing-entry only (no edit of POSTED). Month-end: four steps must
all be marked done before **Close period**; close locks the fiscal period
(no back-posting) and posts closing/appropriation JEs.

---

## 6. UI features (what the buyer sees)

- **Executive Dashboard `/` (ADR-046):** Zone A big-8 KPIs (Revenue/Expenses/Net
  Income YTD, Cash, GPM/NPM, AR/AP outstanding — MoM pills, drill links,
  DHPP/DMIE/OPS/All filter); Zone B 4 Chart.js charts (Revenue vs Expenses 12mo,
  Cash Flow, Segment Performance, Expense doughnut); Zone C AR/AP bucket bars;
  Zone D pipeline (pending/awaiting/posted), waiting-on-you, reversals,
  unposted docs, close checklist. KPI math = statement builders.
- **Access control (ADR-047):** per-user checkbox grants; sidebar filters;
  everything else 403 (URL, HTMX, export, API). COO can be locked to Dashboard +
  My Approvals and still sign CNR items in-inbox.
- **My Profile (ADR-048):** details (read-only role/screens), self password
  change, photo (256px square-crop, local), 8 theme presets following the user.
- **Journal:** General Journal workbook layout (Date|Cycle|Ref|Party|PO|Desc|
  CoA|Account|Dr|Cr + balanced flag + foot totals), list (last 100), detail
  (post/reverse stub), new-entry line grid with live balance.
- **Reports:** COA (392→185, search + segment/type filters), TB (as-of + segment,
  signed balances), 5 statements (generate + persisted snapshot + identity
  OK/FAILED), Cash Flow from cycles, Ledger (COA-grouped index + per-account
  running balances, fiscal-month or date-range, segment filter, TB drill-in).
- **Registers:** AR aging + open-invoice register (Refresh), customers
  (superadmin/head editable), receipts (ACCTG-FOR-005), suppliers, RFP/PO/CV/
  CONSO/advances/banks/cycles/recon/cash-short/transfers/collections-summary/
  COLLECTIBLES/assets/fleet-fuel/tax screens — all with search + choice/date
  filters, 50/page pagination (filters preserved, totals span full set).
- **Exports (every register + every document):** XLSX / CSV / PDF via
  `apps/core/exports.py`. XLSX has real numeric cells + frozen header + totals
  row where applicable; PDF landscape with wrapping (wide registers never clip);
  voucher PDFs form-faithful (RFP ACCTG-FOR-012, CV ACCTG-FOR-010, PCF
  ACCTG-FOR-002, JE, CONSO, AR receipt; A5 vouchers / A4 workpapers, `?paper=`).
  Export honours active filters; filenames are RFC-munged attachments.
- **Polish:** `money` thousand-separator filter everywhere, responsive
  (off-canvas sidebar < `lg`, scrollable tables, stacking headers), reusable
  partials (`page_header, list_card, form_card, status_badge, document_shell,
  workflow_actions, audit_trail, export_buttons`), HTMX row-swap partials
  re-binding JS, footer + login **ESV verse of the week** (52 rotating).

---

## 7. BIR / tax compliance — honest assessment

**Do NOT pitch as “BIR-certified filing software.” Pitch as “BIR-aligned
bookkeeping + data-prep that removes bana-bana estimation.”**

| Capability | State | Evidence |
|---|---|---|
| 12% VAT-inclusive math (`gross = net + output_vat`) | ✅ built | `VATService.extract_from_invoice / extract_for_period`, `VATComputation` |
| SI-level VAT extraction (declared = SI only, formalized) | ✅ built | Phase 9 tax app, `/reports/tax/vat/` renders |
| WHT 2307/2306 from posted CV withholding | ✅ built | `WithholdingService.build_certificates`, `/wht/` reflects CV split |
| WHT 2316 via payroll feed (64100-64126) | ✅ built (feed path) | Payroll skeleton + tax WHT only in UAT |
| Income tax provision → JE (Dr 64600 \| Cr payable, per segment) | ✅ built | `IncomeTaxService.provision`, 8 tests passing, immutable + reversal |
| Tax calendar + filed/paid tracking (2307/2306/2316/2550Q/2551Q/1702Q/1702) | ✅ built | `TaxCalendarService.mark`, `/calendar/` renders |
| BIR forms **data prep** (2307/2306/2316) | ✅ built | Derived from posted CV/payroll |
| COA tax accounts (63600-64606, 23010-23066, 64100-64126) | ✅ structured | `SUBSIDIARY-LEDGERS-AND-MASTER-DATA.md` §1.15/2.13 |
| Printable BIR-form PDFs / e-filing submission | ⚠️ **not built** | UI screens render; no BIR-spec PDF generator or filing integration |
| VAT I/O in GL v1 | ⚠️ **by design excluded** | RESOLUTION #15: VAT-inclusive practice; VAT computed at SI extraction, no VAT GL accounts unless Alywin approves (Q1) |
| Quarterly VAT reconciliation workflow | ⚠️ partial | Extraction works; formal quarterly close not in UAT |
| Full payroll run with real data | ⚠️ skeleton | Awaiting real payroll period import + Alywin review |

Bottom line for pitch: VAT/WHT/provision/calendar **logic + screens exist and
are tested**; buyer still files via their accountant/BIR portal using
system-prepared figures until form-PDF/e-file scope is added (quote as Phase 2).

---

## 8. Live data + verification (LIVE since Sept 2026 UAT → production)

Masters loaded: **COA 185 (revised Sept-2026 authoritative)** · **123 customers
(DHPP, owner/contact/address)** · **8 suppliers** · **54 fixed assets
(cost 22,359,081.01 / accum 4,117,838.30 / NBV 18,241,242.71, opening POSTED &
balanced)** · **11 banks + 4 PCF custodian funds** · **55 posted opening JEs**
(`OB-<year>-<SEG>`, Dr=Cr enforced, FY2026 + 13th adjustment period seeded).
Live users: quibong / leaslyn (staff), alywin (head/superuser) — **working daily
in production on Render**, past UAT into live ops. Live scope: AR,
RFP→CONSO→CV→clear, reject/revise, PCF, recon, transfers, cash-short, assets +
fleet register, TB/statements tie-back, close, tax screens. **Still deferred:**
PR/Receiving/SI screens, full fuel-log feed, full payroll run. Recent prod
commits prove live ops: zero-downtime health-gated deploys, avatar/media-disk
persistence, prod-log picker + statement-export + avatar fixes. Suite:
**600+ tests (239+ green at last gate), `manage.py check` clean**, incl. E2E
customer→AR→RFP→CONSO→CV→transfer→cycles→statements, export matrix (200 + magic
bytes + numeric XLSX cells + empty-DB smoke), dashboard contract,
user-management, and ADR-046 frontend-convention guards.

---

## 9. Pain points this kills (why they buy)

- Pricing-dependency AR errors (30% rework, ~70% accuracy) → three-tier
  per-cycle pricing + snapshots.
- Triple entry (MONITORING + per-client macro + collection summary) → one entry,
  auto AR#/CV#/JE numbers + gap tracking.
- Manual CONSO + “LAST AP” typing → CONSO automation + per-vendor history.
- 4-level chain blocking on absence → My Approvals inbox + status visibility +
  reject/revise without re-keying.
- 12-bank recon in Excel (10–15 min/bank) → per-cycle book-vs-statement recon.
- Paper POPs/filing, FB-Messenger follow-ups → aging, statements, audit trail,
  attachment-ready doc model (S3 pending).
- “Bana-bana” tax estimation → SI-level VAT + WHT certs + provision + calendar.
- Days-long close → accruals→recon→close→appropriations workflow (< 3-day target).
- STPC intercompany blur → billing module + segment tagging (dedicated STPC
  suffix still open).

---

## 10. Pricing (Philippines) — as-is, support, multi-tenant

### 10.1 Sell as-is bulk (single-tenant, source + deploy)
**₱350,000 – ₱500,000 one-time.** Use ₱350k to close fast, ₱500k with
migration/training load. Includes: full source, install on buyer infra (or
Render), master migration (COA/customers/suppliers/banks/assets), 2–3 day
training, **3 months hypercare**, 1-year bug-fix warranty. Position vs.
₱500k–₱2M Odoo-local builds and ₱2M+ agency customs: same ERP depth
(GL + AR/AP + treasury + fleet/assets + billing + statements) at SME price,
BIR-aligned from day one.

### 10.2 Monthly support (after hypercare)
- **₱5,000/mo — Essential:** ≤8 hrs, 48-hr response, bug fixes, BIR table updates
  (VAT/WHT), minor tweaks, monthly health check.
- **₱10,000/mo — Standard (recommended):** ≤16 hrs, 24-hr response, quarterly
  statement/close review, small workflow changes, backup verification, priority queue.
- **₱20,000–30,000/mo — Dedicated:** SLA + on-call close support, unlimited
  minors, monthly feature slot, retainer credited to Phase-2 work.
- Ad-hoc: **₱3,000–₱5,000/hr**. Annual prepay: 1 month free.
Scope excludes: new modules, multi-tenant rebuild, S3/e-file builds (separate SOW).

### 10.3 Multi-tenant SaaS later (ADR-037 exists, not built)
Add **₱200,000–₱300,000** build (4–6 wks): tenant isolation (schema or
`company_id` + RLS), per-tenant COA/fiscal/tax config, tenant admin onboarding,
data partition + backup per tenant, usage metering. Then:
- **Starter ₱1,500/mo** (≤5 users, GL+AR+AP+cash+basic reports).
- **Professional ₱3,000/mo** (unlimited users, all modules, fleet/assets/billing).
- **Enterprise ₱5,000+/mo** (dedicated DB, SLA, custom workflows, STPC split).
- Annual: 10–15% off. Per-extra-tenant support pool: **+₱8,000/mo** shared.
Keep single-tenant perpetual offered alongside SaaS; multi-tenant is an upsell,
not a rewrite of the sale.

---

## 11. Pitch kit (use verbatim)

**30-second opener:** “We replaced 40+ Excel files with one BIR-aligned ERP for
a Philippine fuel/equipment trader — AR with cycle pricing, 4-level RFP approval
with CNR over ₱100k, atomic CONSO posting, check-voucher sign→release→clear with
automatic WHT split, 12-bank recon, fleet + 54-asset depreciation, and six
financial statements from the same posted GL. **Live in production on Render
with the accounting head + staff working daily, CI/CD auto-deploying, 600+
tests.** You can
own it for ₱350k with source and 3-month hypercare, or start SaaS at ₱1,500/mo.”

**Demo path (20 min):** Dashboard (flip DHPP/DMIE/OPS) → AR receipt posts JE →
RFP New (show <₱2,500 block + unbalanced block) → Submit → My Approvals trio →
CNR RFP >₱100k → CONSO Post (atomic) → CV New → Sign → Release → Clear (show
WHT split + GL appearance) → Transfers + Recon → Assets depreciate → TB/IS/SFP
tie-back → Tax VAT/WHT/Calendar → Export XLSX/PDF.

**Differentiators:** fleet+assets in one GL (not add-on); cycle pricing +
prepayment-first ledger; form-faithful ACCTG-FOR PDFs; segment-wise statements
with machine-checked identities; immutable JE + same-person rule; 48 ADRs =
auditable decisions.

**Objections:** Excel “works” → show close-time + error math (§9). Security →
Django + PostgreSQL + RBAC + immutable audit. Django unfamiliarity → HTMX needs
almost no JS; training included. BIR validity → figures + certs + calendar are
system-prepared; filing stays via accountant/portal until form-PDF scope.

**Closing questions:** Excel-file count? Close days? VAT-registered + 2307/2306
volume? Fleet sizedepreciated how? Cycle-price changes? Provision process today?

---

## 12. Roadmap + gaps to quote as Phase 2

1. Multi-tenant (ADR-037) — §10.3.
2. Full payroll run + real-period import + 2316 PDFs.
3. Inventory bridge (webhook/API + dedupe + recon job); re-activate fuel module flag.
4. S3 document attachments (POPs, invoices, RFP files, statements).
5. BIR form-PDFs + quarterly VAT recon + aged VAT payable/receivable.
6. STPC dedicated suffix + standalone P&L (RESOLUTION #17).
7. Offline/low-bandwidth tolerance + backup/fallback runbook (inventory pain).
8. Redis/Celery async posting + report jobs (currently deferred).

---

## 13. Document map (source of truth per area)

| Area | Read first |
|---|---|
| Build scope + checklists | `BUILD-PLAN.md` + `REVIEW-ISSUES-RESOLUTIONS.md` |
| Posting math | `POSTING_RULES.md` + `adr/BUSINESS-EVENT-CATALOG.md` |
| Ledgers/masters | `SUBSIDIARY-LEDGERS-AND-MASTER-DATA.md` + `DOMAIN_MODEL.md` |
| Daily operation | `USERGUIDE.md` + `UAT-GUIDE.md` |
| Screens/exports | `UI.md` |
| Decisions | `adr/ADR-0*.md` (esp. 002, 004, 005, 008, 009, 010, 020, 033, 035, 036, 037, 040, 042, 043, 046, 047) |
| Deploy | `render.yaml` + `backend/Dockerfile` + `entrypoint.sh` |
| Pain context | `PAIN-POINTS-CONSOLIDATED.md`, `COMPENSATION-REVIEW.md`, `workshop-outputs/` |

*No code was changed to produce this file. Counts and statuses are taken from
the docs and UAT guide listed above; re-verify test counts with
`python -m pytest -q` before quoting.*
