# Consolidated Pain Points — Accounting & Operations

> Based on shadow observations (Mich + Che), inventory system interview, and workshop.
> Awaiting: Quibs (Treasury), Alywin (Tax/Payroll/FA), Sir Aaron (Tariff), Mam Anne (Fuel Ordering).

---

## 1. MICH (AR & Collections) — Observed Days 1-2

| # | Pain Point | Severity | Frequency | Root Cause |
|---|-----------|----------|-----------|------------|
| 1 | **Pricing dependency delays payment processing** — Cannot post payment until price confirmed. Prices change daily via Viber/FB. 30% of AR entries need manual rework. | **Critical** | Daily | No system-enforced pricing; prices communicated informally |
| 2 | **Triple data entry** — Same transaction entered in MONITORING sheet, per-client macro sheet, AND collection summary. | **High** | Per transaction | No unified system; each file serves a different purpose |
| 3 | **AR reconciliation ~70% accuracy** — Pricing changes cause mismatches between collections and actual receivables. | **Critical** | Per cycle | Async pricing + manual entry = errors |
| 4 | **Acknowledgment Receipt tracking "unorganized"** — Pre-numbered blue forms tracked manually, gap detection is manual. | **Medium** | Daily | No system for AR# sequence management |
| 5 | **120+ per-client cycle sheets in macro** — Separate Excel file with individual sheet per client. Macro maintenance overhead. | **Medium** | Per cycle | Designed when clients were few; doesn't scale |
| 6 | **Bank deposit monitoring** — Manually tracks which bank each cash payment should go to. | **Medium** | Daily | No deposit instruction system |
| 7 | **POP attachment per cycle** — Prints and attaches Proofs of Payment per client per cycle manually. | **Low** | Weekly | Paper-based workflow carried over |
| 8 | **AR follow-up via FB Messenger** — Overdue clients tracked in paper lists, followed up via group chat. | **Medium** | Daily | No AR aging or automated reminders |
| 9 | **STPC intercompany tracking** — Sister company stations (~4) need separate tracking within same system. | **Medium** | Weekly | Shared cashier but separate accounting |
| 10 | **JO & SI not consistent in monitoring** — Job Orders and Sales Invoices not tracked uniformly. | **Low** | Weekly | No standard entry for non-fuel transactions |

---

## 2. CHE (AP & Payables) — Observed Days 3-4

| # | Pain Point | Severity | Frequency | Root Cause |
|---|-----------|----------|-----------|------------|
| 1 | **Inventory late submissions cause AP backlog** — Warehouse submits count sheets late, delaying RFP creation. | **Critical** | Weekly | Inventory → AP handoff is manual, no deadline enforcement |
| 2 | **Inventory count discrepancies** — Beginning/ending inventory not balanced, cascading to AP accuracy. | **High** | Per count | Physical inventory not organized, count process inconsistent |
| 3 | **PCF without supporting docs** — Walk-in purchases submitted without receipts, causing categorization issues. | **High** | Weekly | No enforcement of "receipt required" policy |
| 4 | **Manual CONSO consolidation** — RFPs consolidated into CONSO sheet manually before Accounting Head review. | **Medium** | Weekly | Extra step that could be automated |
| 5 | **Manual "LAST AP" tracking** — Previous RFP# per vendor typed manually on each new RFP for gap tracking. | **Low** | Per RFP | No system-enforced per-vendor history |
| 6 | **4-level approval chain** — Requestor → Checker (Alywin) → Acctg Mgr → Finance Mgr. Any absence blocks the flow. | **Medium** | Per RFP | Deep chain for ALL amounts, not just high-value |
| 7 | **Standing P20,000 Advances to Employees on every RFP** — Convention, not rule. Confusing for new users. | **Low** | Per RFP | Clearing account mechanism not formalized |
| 8 | **Wait for deposit slips** — Cannot pass to Treasury until deposit slips arrive from bank. | **Medium** | Per batch | Bank processing delay external to accounting |
| 9 | **Manual segment separation** — Must manually split DHPP vs non-DHPP entries when coding. | **Medium** | Per transaction | No default segment per transaction type |
| 10 | **Paper document management** — Supplier invoices, receipts, approvals all on paper. Filing and retrieval overhead. | **Medium** | Daily | No document digitization |

---

## 3. INVENTORY SYSTEM (Staff Interview)

| # | Pain Point | Severity | Current State | Improvement After System | Residual |
|---|-----------|----------|--------------|------------------------|----------|
| 1 | **JE to CONSO is manual** — Inventory JE must be manually re-entered to accounting CONSO. | **High** | Manual re-entry | — | No integration between Django inventory system and accounting |
| 2 | **Physical inventory not organized** — Warehouse arrangement affects count accuracy. | **High** | Disorganized | 0% (system cannot fix physical ops) | Operational, not system issue |
| 3 | **Discrepancy reduced only ~35%** — System helped, but residual errors remain due to manual CONSO entry and physical disorganization. | **Medium** | ~35% reduction | 35% improvement from manual | Still 65% gap |
| 4 | **Accountability vague** — Only one staff handles stockin/stockout. No separation of duties. | **Medium** | Single person | Unchanged | Process issue, system can only log |
| 5 | **Spelling/documentation errors** — Wrong product names, misspellings in entries. | **Low** | Common | ~75% improved by system validation | Residual manual entry |
| 6 | **Internet dependency** — System useful on-the-go only if internet available. | **Low** | Online-only | — | Field staff need offline capability |
| 7 | **System reliability concern** — "What if system breaks down?" — User unsure of fallback. | **Low** | No fallback plan | — | Need offline/backup procedure |

---

## 4. CROSS-CUTTING / SYSTEMIC PAIN POINTS

| # | Pain Point | Affects | Root Cause |
|---|-----------|---------|------------|
| 1 | **40+ disconnected Excel files** — Every person/department maintains their own spreadsheets. Same data entered 2-5 times. | All | No unified system |
| 2 | **No audit trail** — Excel cells can be edited without trace. No record of who changed what or when. | All | No system-enforced immutability |
| 3 | **Manual JE generation** — Every transaction type requires manual journal entry. Posting rules exist on paper but not enforced. | All | No posting engine |
| 4 | **Month-end close takes days** — Manual aggregation, reconciliation, and FS preparation. | Mich, Che, Alywin | No automation |
| 5 | **No real-time financial visibility** — FS produced monthly, not on-demand. | Management | Manual process |
| 6 | **Bank reconciliation is manual** — 12 bank accounts reconciled in Excel. Differences tracked manually. | Quibs | No bank feed integration |
| 7 | **No centralized master data** — Customers, suppliers, COA maintained in separate files. Duplicates and inconsistencies. | All | No master data management |
| 8 | **No separation of duties enforcement** — System doesn't enforce who can do what. Relies on trust. | All | No permission model |
| 9 | **Intercompany (STPC) not separable** — STPC transactions use DHPP accounts. Can't produce standalone STPC P&L. | Mich, Alywin | No dedicated COA suffix for STPC |

---

## 5. NOT YET OBSERVED (Expected Pain Points)

These are areas we know are painful from workshop mentions but haven't shadowed:

| Domain | Person | Expected Pain Points (from workshop / templates) |
|--------|--------|--------------------------------------------------|
| **Treasury / Cashflow** | Quibs | Bank reconciliation across 12 banks, COLLECTIBLES settlement (two-department), CASH SHORT tracking, PCF replenishment, Check Voucher lifecycle |
| **Tax / Payroll / FA** | Alywin | Fixed asset register maintenance, depreciation computation, payroll calculation, government remittance filing, VAT/WHT preparation, month-end close procedure, COA governance |
| **Operations — Tariff** | Sir Aaron | Volume reconciliation between Mich's collections and driver delivery receipts, tariff rate computation, driver settlement disputes |
| **Operations — Fuel Ordering** | Mam Anne | PO vs depot invoice matching, fuel price fluctuations between order and delivery, inventory level monitoring across substations |

---

## 6. SEVERITY MATRIX

```
CRITICAL (blocks daily operation):
├── Pricing dependency → 70% AR accuracy (Mich)
├── Triple data entry → wasted hours (Mich)
├── Inventory late submissions → AP backlog (Che)
├── Inventory discrepancies → inaccurate reporting (Che, Inventory)
├── No unified system → 40+ Excel files (ALL)
└── Manual JE generation → error-prone (ALL)

HIGH (major inefficiency, risk):
├── No audit trail (ALL)
├── PCF without supporting docs (Che)
├── Month-end close takes days (ALL)
├── Physical inventory not organized (Inventory)
├── JE to CONSO manual (Inventory)
└── 4-level approval chain blocks flow (Che)

MEDIUM (slows work, causes frustration):
├── AR tracking via FB Messenger (Mich)
├── Bank deposit monitoring manual (Mich)
├── 120+ per-client macro sheets (Mich)
├── Manual CONSO consolidation (Che)
├── Paper document management (Che)
├── No centralized master data (ALL)
├── AR# tracking "unorganized" (Mich)
├── Manual segment separation (Che)
└── No real-time FS visibility (Management)

LOW (annoyance, not blocking):
├── POP attachment per cycle (Mich)
├── Standing P20,000 convention unclear (Che)
├── Spelling errors (Inventory)
├── Internet dependency (Inventory)
└── System reliability concern (Inventory)
```

---

## 7. QUICK WINS vs LONG-TERM

### Quick Wins (system can fix immediately)
1. Auto AR# assignment (eliminates "unorganized" tracking)
2. Bank code dropdown (eliminates manual GL typing)
3. Centralized customer master (eliminates duplicates)
4. Auto "LAST AP" per vendor (eliminates manual tracking)
5. Enforced P2,500 threshold (eliminates PCF vs RFP confusion)

### Medium-term (requires process + system)
1. System-enforced pricing (eliminates 70% AR error)
2. CONSO automation (eliminates manual consolidation)
3. RFP approval tracking (visibility into where things are stuck)
4. Document digitization (eliminates paper management)
5. JE export from inventory system (eliminates manual CONSO entry)

### Long-term (requires full system + training)
1. Automated month-end close
2. Real-time financial statements
3. Bank reconciliation automation
4. Multi-segment COA with STPC separation
5. Permission/enforcement model (separation of duties)
