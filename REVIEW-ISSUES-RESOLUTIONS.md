# REVIEW ISSUES & RESOLUTIONS REGISTER

**Status:** Final review pass before build — 2026-08-14
**Scope:** All 33 ADRs, 4 master docs (POSTING_RULES, SUBSIDIARY-LEDGERS, DOMAIN_MODEL, ARCHITECTURE), BUSINESS-EVENT-CATALOG, 9 source Excel workbooks, 3 observation folders, workshop outputs, all shadow docx.
**Method:** Four independent audits (ADR consistency; source workbooks; observation files; full docx/transcripts). This register records every discrepancy found and the resolution adopted. Resolutions with **[FIXED]** are already applied to docs; **[TODO]** are queued for Phase 0 of the build.

---

## A. Resolved Decisions (correct facts established)

| # | Issue | Finding | **RESOLUTION** |
|---|-------|---------|----------------|
| 1 | COA digit count | ADR-025/033 say "10-digit"; real COA = **5-digit** codes `[1][2][3][4][5]`, segment in last digit (0=DHPP, 3=DMIE, 6=OPS; tens-triplets 00/03/06, 10/13/16, …90/93/96 for cash families) | **[TODO]** All docs normalized to 5-digit. ADR-033 example uses 61100 → replace with 63400-level payroll accounts. |
| 2 | Cycle day range | ADR-013/028/025 state "Wed–Tue"; **every real cycle label is Tue→Mon** (FEB 4-10 2025 = Tue–Mon; DEC 23-29 = Tue–Mon; JAN 06-12/13-19/20-26 2026 = Tue–Mon) | **[TODO]** Cycle = **Tuesday → Monday** (cutoff Monday EOD). Fix ADR-013/028/025 + docs/03. |
| 3 | Bank account count | 11/12/13 across docs | **[RESOLVED]** BankAccount master = **12 accounts / 9 banks** (PNB-OPEX, PNB-Checking, PSBC-S, PSBC-C, KB-C, KB-S, 1VB, BDO, MBTC, RCBC, CHINA, E.TAN/STPC) + **PCF&COH** as a separate non-bank cash column → 13 columns total; cycle sheet aggregates to 11 columns (KB-S folded, E.TAN/STPC merged) |
| 4 | Advances to Employees GL | ADR-021/POSTING_RULES use 12050; real COA has **12070/12073/12076** (Advances to Employees, segment-suffixed); 12050 doesn't exist | **[TODO]** Use 12070–12076. |
| 5 | RFP standing P20,000 JE math | ADR-018/021/023/POSTING_RULES §7.2 all write incompatible (non-balancing) JEs | **[RESOLVED]** Canonical JE (balances): **Dr Expense/Inventory/Asset {TOTAL} \| Cr Advances-to-Employees {20,000} \| Cr AP-Vendor {TOTAL − 20,000}**. Applies when payee = employee with standing advance (Che convention, pain point #7 — keep as convention, clarify in form). |
| 6 | AR GL account range | POSTING_RULES uses 11000–11999; real GJ uses **12020 A/R-Other Current, 12030 A/R-Fuel Clients** | **[TODO]** AR = 120xx range only. |
| 7 | Unearned range | POSTING_RULES 12.3 says 21000–21016 (misses DMIE) | **[RESOLVED]** Unearned = **21000 (DHPP), 21016 (OPS), 21023 (DMIE)**. |
| 8 | Cash Short account | 63210 in real COA = "Other Operating Expenses-DHPP", not cash short; POSTING_RULES 8.3/15.6 assume 63210–63216 | **[TODO]** Add new COA account **Cash Short/Over Expense** (new code, e.g. 6321x range pending Alywin) to COA master. CASH SHORT sheet itself is a recon worksheet, not a JE. |
| 9 | Collection event duplication | Catalog #7 `cash.collection.received` (Dr Cash/Cr AR), #9 `cash.ar_issued` (Dr Cash/Cr Unearned), #44 `fuel.client_payment.received` — 3 events, same physical moment; #8/#80 deposit; #87/#90 settlement | **[RESOLVED]** **One posting event** `cash.collection` (Dr Cash \| Cr Unearned 210xx for prepaid clients; Cr AR 120xx when applied to prior AR — per client state). AR issuance (#9) = document event, NO separate JE. Deposit (#8/#80) = NO JE (state change). Settlement #87/#90 = NO JE (derived report, per ADR-029). Catalog corrected in Phase 0. |
| 10 | Payroll disbursement path | Catalog #67/#69 route via AP-Others; POSTING_RULES 10.1/10.2 pay direct | **[RESOLVED]** **All disbursements go through AP module** (RFP ≥ P2,500 / PCV < P2,500, ADR-022): payroll & govt remittance = RFP → Dr payables \| Cr AP-Others → CV → Dr AP-Others \| Cr Cash. Matches real practice (CONSOLIDATED-FINDINGS 5.8). |
| 11 | PCF model | POSTING_RULES 8.1 direct vs 15.4 imprest | **[RESOLVED]** Imprest: Dr Petty Cash Fund \| Cr Cash at replenishment; expenses liquidated at replenishment (Dr Expenses \| Cr PCF). 3 funds (Leaslyn/Treasury/Alywin), 85% trigger, PCF&COH ADB 20,000. |
| 12 | Name spellings | Alwyn vs Alywin; Quibs/Quids/Quibong | **[RESOLVED]** **Alywin** (all docs; zero "Alwyn" in sources). "Quibs" for treasury person; "Quibong" full name. |
| 13 | Entity IPPC | Used in GUIDELINES (salary sheet G15) but undefined | **[RESOLVED]** IPPC = real entity (salary allocation) — add to Company master alongside STMIET/STPC. |
| 14 | COA count / TB sync | TB has 396 rows vs COA 392; 7 TB-only accum-dep accounts, 3 COA-only | **[TODO]** Phase 0: reconcile — TB regenerated from COA (COA = source of truth, Alywin-approved). |
| 15 | Missing COA accounts | No VAT I/O, no Govt Remittances asset, no Customer's Deposit, no dedicated Cash Short, no appropriation reserves | **[TODO]** Phase 0: COA additions list (pending Alywin): Cash Short/Over; decision on VAT = **not tracked in GL v1** (VAT-inclusive practice; VAT computed at SI extraction in Tax phase); Govt Remittances & Customer's Deposit modeled via 2xxx/1xxx existing if needed. |
| 16 | Deposit/settlement derived | COLLECTIBLES + CASH SHORT = derived reports | **[RESOLVED]** Matches ADR-028/029/031 — confirmed. |
| 17 | STPC intercompany | No COA suffix; uses DHPP accounts; no standalone STPC P&L (systemic pain #9) | **[TODO]** STPC = 4th **segment tag** (not COA suffix) with Due-from 15500 / Other Payables 25500; intercompany recon events added to catalog (Phase 0). |
| 18 | Official Receipt | DOMAIN_MODEL/ARCHITECTURE still model OfficialReceipt; company issues NONE (ADR-015) | **[TODO]** Remove OfficialReceipt entity → AcknowledgmentReceipt (ACCTG-FOR-005 v3, YYYY-SEQ). |
| 19 | Event catalog version | 113 events (verified correct); but contradicts ADR-010 "100 events" and has stale JE claims (#87/#90, #7/#9/#44) | **[TODO]** Catalog gets "Last Updated 2026-08-14" + event corrections per rows 9/17. |
| 20 | Event names drift | POSTING_RULES uses names not in catalog (cogs.recorded, expense.incurred, inventory.goods_receipt, etc.) | **[TODO]** Phase 0: single event-name registry (catalog = source of truth; POSTING_RULES maps to it). |
| 21 | Payroll events numbering | ADR-033 says "Payroll-01..08" + §8 ref | **[FIXED]** ADR-033 corrected: catalog events #63–70, POSTING_RULES §14. |
| 22 | Voucher forms approvers | ADR-032 form has COO unconditional on CV; ADR-008/020 chain has no Acctg/Finance Mgr slots | **[TODO]** ADR-008/020 updated: CV signature block = REQUESTED → CHECKED (Alywin) → APPROVED (CNR) — printed form governs (forms are fixed); thresholds enforced in workflow engine behind the form. |
| 23 | PCF custodian contradiction | ADR-006/008/017/020/022 say "Quibong custodian"; ADR-027: 3 custodians | **[RESOLVED]** 3 custodians (Leaslyn/Treasury/Alywin) — custodians = fund holders; Quibs = treasury administrator/recon. Earlier ADRs corrected in Phase 0. |
| 24 | COGS-Gasoline vs 63800 | Catalog #47 tanker consumption → COGS-Gasoline 50020; POSTING_RULES 6.4 → 63800 Travel OpEx | **[TODO]** Confirm with Alywin during FA/fleet phase; provisional: **50020 COGS-Gasoline** (tanker = revenue-earning, matches docs/02). |
| 25 | Appropriation % | Catalog #112 adds 5% expansion; POSTING_RULES 13.3 = 10% R&M + 10% Tithing | **[RESOLVED]** 10% R&M + 10% Tithing only (matches all docs except catalog) — catalog fixed. |
| 26 | Goods receipt credit | Catalog #23 Cr Advances-to-Supplier vs POSTING_RULES 5.1 Cr AP | **[RESOLVED]** Both valid paths: paid pickup → Cr Advances-to-Supplier; credit pickup → Cr AP. Rule 5.1 amended to two-path model (matches Acctg-Entry FUEL sheet). |
| 27 | Invoice on receipt vs payment | Che books supplier invoice at payment (per shadow) | **[RESOLVED]** Invoice booked on receipt event (matching) BUT RFP drives payment; actual practice books at payment — keep event model + allow payment-based booking flag. Confirm in Phase 3. |
| 28 | MACHINERY vs MACHINERIES conventions | Two DMIE models (VAT+Customer's Deposit vs Advances+Unearned, no VAT) | **[RESOLVED]** Live practice = **MACHINERIES model (no VAT, Unearned 21023, advances to supplier)**. MACHINERY/VAT template = legacy. |
| 29 | Customer count | 120+ macro sheets vs 121 supplier codes vs ~200+ customers | **[TODO]** Master data cleanup/migration (Phase 0/2) — dedupe, one-time migration. |
| 30 | Roads divergence | ARCHITECTURE 9 phases vs CONSOLIDATED-FINDINGS 10 phases | **[RESOLVED]** BUILD-PLAN.md supersedes both (10 phases + migration + tax). |
| 31 | JE threshold approval | POSTING_RULES §17.5 placeholder {threshold} | **[TODO]** Default: JEs above ₱100,000 require Alywin approval (mirror AP thresholds). Confirm Phase 0. |
| 32 | Voucher doc numbering | ACCTG-FOR-001/003/004/006–009/011 undefined | **[RESOLVED]** Register: 001=?, 002=PCV, 003=?, 004=?, 005=AR v3, 006=?, 007=?, 008=?, 009=?, 010=CV, 011=?, 012=RFP. Unknown slots = legacy/unused; do not invent. |
| 33 | Deposit tracking | #8 no-JE vs #80 JE | **[RESOLVED]** Deposit = state change, NO JE (per row 9). |
| 34 | Procurement must-haves | PR/PO/RR/SI — confirmed in Acctg-Entry + PO_LIMDON | **[RESOLVED]** Confirmed. PO total excludes VAT (VAT-inclusive pricing practice). |

---

## B. Queries Requiring Alywin (accounting head) — Phase 0 gate

| # | Question | Where it blocks |
|---|----------|-----------------|
| Q1 | Approve COA additions: Cash Short/Over Expense code; confirm no VAT accounts; confirm Advances 12070–76 | COA importer |
| Q2 | Confirm cycle cutoff = Monday EOD (Tue–Mon) | Fiscal calendar builder |
| Q3 | Confirm RFP canonical JE (TOTAL = Advances 20k + AP balance) and whether P20,000 remains standing | Posting engine, AP |
| Q4 | Tanker consumption: 50020 COGS-Gasoline vs 63800 | Posting engine, fleet |
| Q5 | JE approval threshold (₱100,000 default) | Workflow engine |
| Q6 | TB↔COA sync authority (COA = truth) | Migration |
| Q7 | Appropriation: 10% R&M + 10% Tithing (no 5%) | Month-end |
| Q8 | Payroll feed reviewer = Che (ADR-033) vs Alywin | Payroll import workflow |

---

## C. Where the resolved facts are already applied

- **ADR-025** — status → Superseded (Build confirmed) **[FIXED]**
- **ADR-033** — §8 → §14, payroll events #63–70 **[FIXED]** (remaining: 61100 example → Phase 0)
- **ADR-032** — voucher format spec (source of truth for forms) **[FIXED]**
- **BUILD-PLAN.md** — the staged execution plan below, phases map 1:1 to classic enterprise accounting modules

---

## D. Process lessons (for change management during build)

1. All cross-document references must go through a **decision register** (this file) — never edit an ADR without a register entry.
2. The source workbooks remain the ultimate truth; ADRs are derived. When they disagree, the workbook wins unless Alywin rules otherwise.
3. Event names come from BUSINESS-EVENT-CATALOG only; POSTING_RULES must not invent names.
4. Real data beats prose: every "Wed-Tue" prose claim was overturned by actual cycle labels (Tue-Mon).
