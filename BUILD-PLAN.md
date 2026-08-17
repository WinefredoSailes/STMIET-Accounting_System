# BUILD PLAN — STMIET Accounting System

**Status:** Active — build confirmed (ADR-025 superseded → Build, 2026-08-14)
**Guiding ADRs:** ADR-001..033 | **Source of truth:** REVIEW-ISSUES-RESOLUTIONS.md (resolution register), source workbooks, BUSINESS-EVENT-CATALOG.md, POSTING_RULES.md, SUBSIDIARY-LEDGERS-AND-MASTER-DATA.md

**Architecture:** Modular Django monolith (ADR-009/010) — PostgreSQL, DRF, React or HTMX, Celery/Redis, S3. Event-driven posting engine (ADR-004), immutable journal (ADR-005), no force balance (ADR-002).

---

## Standard Classic Accounting Mapping (how this system maps to enterprise norms)

| Classic module | STMIET equivalent | ADR | Status |
|---|---|---|---|
| General Ledger & Chart of Accounts | COA (392 accts, 5-digit, segment-suffixed) + GL + JE + TB | 001-005, 011 | Phase 1 |
| Accounts Receivable subledger | Customer ledger, Over/(Short) cycle model, Acknowledgment Receipts (NO ORs) | 007, 012-015 | Phase 2 |
| Accounts Payable subledger | AP ledger, RFP (ACCTG-FOR-012), CONSO, CV, supplier master | 017-024 | Phase 3 |
| Cash & Banks / Treasury | 12 bank accounts, 9 banks, bank recon, PCF×3 (85% trigger), weekly cycles (Tue–Mon) | 016, 026-031 | Phase 4 |
| Inventory | Existing live Django inventory system → API bridge (event bus) | 004, 009 | Phase 5 |
| Fixed Assets | Asset register, straight-line dep, disposal | [ADR-034](./adr/ADR-034-fixed-assets.md) | Phase 7 |
| Payroll / HR | EXTERNAL system — GL feed contract (file-based v1, API-ready) | 033 | Phase 6 |
| Financial Statements | IS, SFP, CF, CoS, Total Expenses, SOCE (6 templates) + TB | 031, [035](./adr/ADR-035-financial-statements.md) | Phase 8 |
| Tax & Compliance | VAT at SI extraction, WHT, income tax (removes "bana-bana" estimation) | (Phase 10 ADR todo) | Phase 10 |
| Month-End Close | accruals → recon → close → appropriations (10% R&M, 10% Tithing) | 013, 035 | Phase 8 |
| Audit & Controls | Immutable JE, approval hierarchies, segment immutability, no force-balance | 002, 005, 008, 020 | All phases |

---

## PHASE 0 — PRE-BUILD (FOUNDATION READINESS) *[est. 1 wk]*

- [ ] Resolve Alywin Q&A gate (REVIEW-ISSUES §B: Q1–Q8)
- [ ] COA master finalized: 392 accounts → 5-digit validation, add missing accounts (Cash Short/Over; confirm Advances 12070–76; confirm no VAT), sync TB↔COA (COA = truth, 396-row TB regenerated)
- [ ] Event catalog corrected (per RESOLUTION #9/#17/#25; re-dated 2026-08-14)
- [ ] Event-name registry (catalog = truth; POSTING_RULES mapped; 10 renamed events reconciled)
- [ ] Correct all docs per REVIEW-ISSUES resolutions (register is authoritative)
- [ ] Customer master cleanup plan (~200+ customers; dedupe 120+ macro sheets vs inventory list)
- [ ] Fiscal calendar verified: 12 monthly periods + weekly cycles Tue→Mon per year
- [ ] Bank master: 12 accounts/9 banks + PCF&COH (ADB: PNB 50k, MBTC 50k, others 5k, PCF&COH 20k)
- [ ] Scaffold repo: Django 5 + PostgreSQL + DRF + dev/staging/prod containers
- [ ] COA import script (Excel → Account model) + validation (unique code+segment, FS sequence)
- [x] ADR for Fixed Assets (register, SL dep, disposal, per-category lives) — Phase 0 deliverable
- [x] ADR for Financial Statements & Reporting (5 templates as data, windows, month-end close) — Phase 0 deliverable
- [ ] ADR for Tax module scope (VAT extraction, WHT, income tax) — Phase 0 deliverable

**Done when:** Alywin Q&A answered; COA imports clean; TB tie-out test passes; posting engine spec final.

---

## PHASE 1 — GENERAL LEDGER & POSTING ENGINE *[est. 8-10 wks]*

- [ ] Models: Company, Segment (incl. STPC tag), FiscalYear, FiscalPeriod, Account (+full_title, FS sequence, expense dimensions)
- [ ] JournalEntry + JournalEntryLine (immutable on POSTED; reversal-only corrections — ADR-005)
- [ ] PostingRule + PostingRuleLine (account-prefix matching, amount formulas, JSON conditions — ADR-004)
- [ ] PostingService: event → match rule → create JE → update GL; **ΣDr=ΣCr enforced; NO force balance (ADR-002)**
- [ ] GeneralLedger (account × segment × period, beginning/total Dr/Cr/ending)
- [ ] Segment validation: JE segment consistency, except consolidating (ADR-011)
- [ ] Voucher/sequence registry: AR# (YYYY-SEQ), RFP# (A#### + gap tracking), CV#, doc numbers (ACCTG-FOR series)
- [ ] Approval workflow engine (Draft→Submitted→Approved→Posted→Closed; thresholds — ADR-008/020)
- [ ] Trial Balance report (monthly + YTD, per segment) — matches TB workbook structure (12-month pairs)
- [ ] Fiscal period close (no back-posting to closed periods — rules §17)
- [ ] Phase tests: FBAR-style entry tests for each POSTING_RULES family (§1-4, §12-13 baselines)

**Done when:** TB generated from posted JEs equals workbook layout; all 113 event→rule mapping validated for foundation events.

---

## PHASE 2 — ACCOUNTS RECEIVABLE (CUSTOMER LEDGER + COLLECTIONS) *[est. 6-8 wks]*

- [ ] Customer master (+ one-time migration/cleanup, segment default, group Fuel/Equipment/OPS)
- [ ] Customer ledger: Over/(Short) **cumulative** cycle model (ADR-013) — payments vs amounts payable
- [ ] Three-tier pricing: Regular/Patron/Volume + **per-cycle price snapshots** (ADR-014; prices via Viber/FB → system data entry; kills ~70% AR rework, pain #1)
- [ ] Acknowledgment Receipt (ACCTG-FOR-005 v3): pre-numbered YYYY-SEQ, print matches workbook (ADR-032/015)
- [ ] Collection entry: Dr Cash | Cr Unearned 21000/21016/21023 (or Cr AR 120xx when applying to prior AR) — single event `cash.collection` (RESOLUTION #9)
- [ ] Deposit tracking: 12-bank + PCF&COH columns; deposit = state change, NO JE (ADR-016)
- [ ] Cycle settlement: COLLECTIBLES-derived report; two-department (Distribution vs F&A); gross mark-up = client paid − depot paid (ADR-029; NO JE)
- [ ] Cash short/excess worksheet (CASH SHORT sheet = recon worksheet; variance requires cause + Alywin approval — ADR-030)
- [ ] AR aging (30/60/90/120+), client statements, AR follow-up list (kills FB-paper-list pain #8)
- [ ] Weekly collection summary auto-generated (eliminates triple data entry, pain #2)
- [ ] Integrate with fuel delivery events (delivery-completed-paid/unpaid JEs — catalog #48/49)
- [ ] Migration: AR-BLUE 2026 (1M+ rows → filtered to active), macro per-client sheets

**Done when:** Mich runs a live weekly cycle end-to-end; AR accuracy target 100% (from 70%); aging < 1 min.

---

## PHASE 3 — ACCOUNTS PAYABLE & PROCUREMENT *[est. 6-8 wks]*

- [ ] Supplier master (Depot/Equipment/Service/Govt; TIN; "LAST AP" auto-track — kills pain #5, ADR-024)
- [ ] PR → PO → RR → Supplier Invoice → RFP → CONSO → CV document chain (ADR-017; forms: PO_LIMDON layout, RFP ACCTG-FOR-012)
- [ ] RFP model: A#### auto-numbering + gap enforcement (ADR-019); 4-level approval (ADR-020); P2,500 threshold enforced (ADR-022; ≥RFP, <PCV)
- [ ] **RFP JE (canonical):** Dr Expense/Inventory/Asset {TOTAL} | Cr Advances-to-Employees 12070–76 {20,000} | Cr AP {TOTAL − 20,000} (RESOLUTION #5)
- [ ] Advances to Employees ledger (standing 20k, liquidation, aging) — ADR-021
- [ ] Multi-segment AP allocation (single RFP split across DHPP/DMIE/OPS — ADR-023)
- [ ] CONSO batch: auto-generate JE per RFP batch; reviewed by Accounting Head (kills manual CONSO, pain #4)
- [ ] Check Voucher print (ACCTG-FOR-010, exact ADR-032 layout) + Petty Cash Voucher (ACCTG-FOR-002)
- [ ] Payment clearing: Dr AP | Cr Cash (+WHT split Dr AP {gross} | Cr Cash {net} + Cr WHT 64110-16)
- [ ] AP aging, due-date tracking, supplier statements
- [ ] Payment-based invoice booking flag (RESOLUTION #27 — confirm in Phase 3 with observed practice)
- [ ] Migration: RFP TEMPLATES (39 sheets), supplier invoices history

**Done when:** Che runs live RFP→CONSO→CV cycle; IS variance same-day; PO-to-payment trackable.

---

## PHASE 4 — CASH & BANKS (TREASURY) *[est. 4-6 wks]*

- [ ] BankAccount master (12/9 banks+PCF&COH; ADB maintaining balances; account type S/C)
- [ ] Weekly cash cycle sheet (Tue–Mon): 11 columns, 8 activity rows (ADR-028) — derived report
- [ ] Bank reconciliation per weekly cycle (ADR-026; target <15 min/bank from 10–15; difference causes = typo/POP/cashier)
- [ ] Petty Cash: 3 funds (Leaslyn/Treasury/Alywin), 85% replenishment trigger, ADR-027
- [ ] Inter-account transfer (Dr Cash-To | Cr Cash-From; purpose required; ADR-030)
- [ ] Cash Flow Statement generation from cycles (ADR-031; identity test: Net Inc = End − Beg + ADB adjustments)
- [ ] Check disbursement tracking (CV lifecycle: created → signed CNR → released Quibs → cleared)
- [ ] COLLECTIBLES + CASH SHORT worksheets generated from posted data (ADR-029/030)
- [ ] Migration: SUMMARY OF CASH JANUARY 2026 (weekly cycles, CF, COLLECTIBLES, CASH SHORT)

**Done when:** January 2026 data reproduces in system: CF identity -941,691.96 = 1,316,150.58 − 2,412,842.54 + 155,000 ✓; Quibs weekly cash flow < 30 min.

---

## PHASE 5 — INVENTORY INTEGRATION (API BRIDGE) *[est. 6-8 wks]*

- [ ] API bridge to live Django inventory system (POST /inventory-events or webhook; ADR-004/009; eliminates manual JE→CONSO, staff request)
- [ ] Events: stock received (Gr), stock issued (Gi), transfer, physical count, write-off, revaluation
- [ ] Posting rules 5.1–5.3 (two-path: advances vs AP credit; write-off Dr 632xx | Cr 130xx)
- [ ] Periodic sync + reconciliation job (inventory value vs GL 130xx per segment)
- [ ] Error queue + retry; idempotency (event dedupe) to prevent double posting
- [ ] Offline-tolerant design decisions (pain: internet dependency) — document, don't block

**Done when:** Inventory JE export/direct-post goes straight to CONSO without manual re-entry (~35%→100% discrepancy reduction path).

---

## PHASE 6 — PAYROLL (GL FEED CONTRACT) *[est. 4-6 wks]*

- [ ] ADR-033 feed importer: validate schema → JE preview → review (Alywin per Q8) → post
- [ ] Feed: SUMMARY + JE LINES sheets; entity/segment/cost-center/GL validation v1 schema
- [ ] Posting: payroll.run.posted 12-line gross-to-net (POSTING_RULES §14) + ER shares separate JE
- [ ] Payroll subsidiary ledgers: Payroll, Government Contributions (23010-23066), WHT (64100-64126), Accrued Salaries (22020-26)
- [ ] Govt remittance via AP module (RFP → AP-Others → CV → cash) — RESOLUTION #10
- [ ] Feed archive (immutability), batch reference linkage, versioned schema (v1)
- [ ] Future: API endpoint `POST /payroll-feed` (ADR-033 upgrade path, NOT in v1)

**Done when:** One real payroll period imported and posted with review; GL ties to payroll system totals.

---

## PHASE 7 — FIXED ASSETS *[est. 4-6 wks]*

- [x] Asset register (categories from COA: tankers 10-15y, boom trucks 10y, vehicles 5-7y, building 15-20y, furniture 5y, office equip 3-5y)
- [x] Acquisition (Dr 17xxx-19xxx | Cr AP/Cash/Loans), financed acquisitions w/ fees
- [x] Straight-line depreciation engine (monthly: Dr 50110/616xx | Cr Accum Dep 17xxx)
- [x] Disposal (Dr Cash + Accum Dep | Cr Asset + gain/loss 43070-96)
- [x] Depreciation schedule + fully-depreciated-still-in-use flag (Alywin pain)
- [x] Asset↔Vehicle link (Vehicles are assets — 17000-18650)
- [ ] Seed per-segment accum-dep accounts beyond 18513 (Boom Trucks) + residual-value convention w/ Alywin
- [ ] Confirm loss-on-disposal account (62000/62003 Impairment vs dedicated 6xxx) w/ Alywin

**Done when:** Asset register live; acquisition/depreciation/disposal post via API with gain/loss; fully-depreciated-still-in-use visible.

---

## PHASE 8 — FINANCIAL STATEMENTS & REPORTING *[est. 4-6 wks]*

- [x] 5 FS templates reproduced from workbook layouts as data (IS MARCH 2026, SFP YEAR END, CoS, Total Expenses CGSE, SOCE) — `apps.reporting`, `[ADR-035](./adr/ADR-035-financial-statements.md)`
- [x] IS: segment columns (DHPP/DMIE/OPS/Grand) + GPM/Expense Ratio/NPM + appropriations (10% R&M, 10% Tithing)
- [x] SFP: current/NC split, ratios, capital identity (Assets == Liabilities + Equity machine-checked)
- [x] CoS by segment (DHPP 12 lines, DMIE 18, OPS 5) + liters quantity rows
- [x] Total Expenses (CGSE) with reconciliation of duplicate/leftover template issues
- [x] SOCE (beginning cap + additional + net profit − drawings = ending, machine-checked)
- [x] Month-end close workflow: accruals → recon → close → appropriations (locks the fiscal period; kills days-long close, target < 3 days)
- [ ] CF statement (weekly cycles → monthly CF, ADR-031 cadence)
- [ ] Management reports: weekly collections, cash short/excess, AR/AP aging, fleet fuel
- [ ] Reporting test: January 2026 actuals reproduced across all 6 statements

**Done when:** All 6 FS generated from posted data match template layouts; month-end close < 3 days (from 5–30+).

---

## PHASE 8b — SERVER-RENDERED UI (Django Templates + HTMX + Tailwind) *[est. 2-3 wks]*

- [x] Architecture decision: server-rendered UI over SPA — `[ADR-036](./adr/ADR-036-ui-frontend.md)`; DRF API stays as the external contract (JWT)
- [x] `apps/ui` scaffolded (view-only bounded context, no models); mounted at `/` alongside `api/v1/`
- [x] Tailwind build pipeline (`backend/frontend`) + vendored HTMX 1.9.12
- [x] Auth: login/logout (session auth, built-in form)
- [x] Dashboard: fiscal period, entry counts, close progress, recent entries
- [x] Journal: list / detail / create (line grid + balance hint) / post (P100k approve gate) / reverse stub
- [x] Trial Balance screen (as-of + segment filter)
- [x] Financial statements: 5 types, generate + persisted snapshot, identity OK/FAILED
- [x] Month-end close screen: step-by-step advance + complete (locks period)
- [x] List screens: customers, receipts, suppliers, RFPs, banks, cash cycles, assets
- [x] UI smoke tests (30 tests: render + auth + JE workflow + close lifecycle) — 106 total passing
- [x] Functional screens per module (following the office form layouts ACCTG-FOR-005/010/012):
  - AR: customer create, receipt create (auto AR# → posts collection JE)
  - AP: supplier create, RFP create (line grid + advance credit), RFP detail with ADR-020 approval chain (submit → checked → acctg → fin → CNR >₱100k, same-person rule enforced), approve / approve-CNR actions
  - AP: check voucher create (CV-YYYY-#### from approved RFP, posts 7.4 JE with WHT split) + detail with sign → release → clear lifecycle
  - Cash: bank create, weekly cycle generation (Tue–Mon, idempotent), PCF funds (+ setup screen), petty cash voucher / replenishment (ACCTG-FOR-002: payee, distribution grid, post replenishment JE)
  - Cash: bank reconciliation (book vs statement per cycle, resolved/open), cash short worksheet (record variance + approve)
  - Cash: daily collections JE summary screen (cashier worksheet format: per-bank DR columns, AR/AP DR-CR, day totals, debits=credits check)
  - AP: CONSO batch UI (open → add approved RFPs → post atomically)
  - Assets: acquire (FA-YYYY-####, posts 9.1), detail with depreciation schedule + NBV, post depreciation (9.2), dispose (9.3)
- [x] Register / analysis screens: general journal (workbook layout, balanced flag), cash flow statement (per segment, identity check), COLLECTIBLES worksheet per cycle, AR aging + open-invoice register, advances ledger + inline liquidation, inter-account transfers, COA listing with filters (all master-data driven, no hardcoded segment names)
- [x] `seed_demo` management command (idempotent January-2026 dataset through services: posted AR/RFP/CONSO/CV/transfer/advance, cycles, COLLECTIBLES, cash flow) — seed only, run against a dev DB
- [x] UI functional tests (77 UI/tests.py + E2E workflow in `test_e2e.py`) — full suite 153 passing, `manage.py check` clean
- [ ] Statement input chaining (IS net profit → SFP/SOCE `eq_net_profit` / `soce_net_profit`)
- [ ] HTMX partial updates (inline status transitions, filters) on list screens
- [ ] Remaining workflow screens: PCF fund setup, check disbursement reconciliation (bank recon), cash short approval, CONSO batch UI

**Done when:** An operator can run the full month-end pack from the browser; all Phase 2–7 workflows have a screen.

---

## PHASE 9 — TAX & COMPLIANCE *[est. 4-6 wks]*

- [ ] SI extraction (what's declared = SI only — current practice formalized)
- [ ] VAT computation at SI level (12% VAT-inclusive → I/O VAT derived; no GL VAT accounts unless Alywin approves — Q1)
- [ ] WHT: compensation/expanded/final (64100-64126) remittance via AP module
- [ ] Income tax provision (Dr 64600-06 | Cr 2xxx)
- [ ] Tax calendar + filing tracking (removes "bana-bana" estimation)
- [ ] BIR forms data prep (2307, 2306, 2316 from payroll feed)

---

## PHASE 10 — MIGRATION, UAT & GO-LIVE *[est. 4-6 wks]*

- [ ] Master data migration: COA (392), customers, suppliers, banks, employees, vehicles, assets
- [ ] Opening balances: January 2026 TB-equivalent; FS tie-out vs workbooks
- [ ] UAT per person: Mich (Phase 2), Che (Phase 3), Quibs (Phase 4), Alywin (Phases 1/6-9)
- [ ] Parallel run: real cycle processing in system while Excel continues (2-3 weeks)
- [ ] Success metrics re-measurement (OBSERVATION-PLAN targets: close < 3 days, 0 errors, 100% accuracy)
- [ ] Training + SOP documents per role
- [ ] Go-live + data freeze + hypercare

---

## Cross-cutting (all phases)

- [ ] RBAC/segregation of duties (no single user creates+approves+posts; Wright/JE approval by Alywin)
- [ ] Audit trail (ADR-005/006): every JE → source document; every status change logged
- [ ] Document management (S3): POPs, invoices, RFP attachments, bank statements (kills paper filing pain #9 Che)
- [ ] Posting rules engine tests for all POSTING_RULES families (§1-17)
- [ ] Reporting identity tests (CF identity, TB tie-out, FS cross-check)

---

## Deferred (explicitly out of scope unless revisited)

- Sir Aaron driver tariff & Mam Anne fuel ordering workflows (ADR-025 de-scope note; handoff boundaries captured in AP/Treasury)
- Intercompany STPC standalone P&L (needs segment-tag reporting decision — RESOLUTION #17)
- Real-time payroll API (ADR-033 v2)
- Microservices split (ADR-009 — only if a module needs independent deployment)