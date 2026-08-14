# WORKSHOP CONSOLIDATED FINDINGS + POST-WORKSHOP ANALYSIS

**Date**: July 18, 2026 | **Duration**: 2 hours
**Files used**: COA-STMIET-2026 (392 active accounts), Acctg-Entry-finance-and-acctg (actual posting rules), 6 Financial Statements, Trial Balance

---

## 1. ORGANIZATION

### Team
| Person | Role | Handles |
|--------|------|---------|
| **Mich** | Accounting Staff | Cash, Collections, AR, Client accounts |
| **Che** | Accounting Staff | AP, Inventory, Financial Statements, Income Statement |
| **Quibs** | Accounting Staff | Cashflow, Bank reconciliation, Fuel payment monitoring, Expenses |
| **Alywin** | Accounting Head | Tax, Payroll, Fixed Assets, Balance Sheet, Equity, COA maintenance, JE validation |

### Company Structure
- **Entity**: STMIET (Seven-Trent Machineries Industrial Equipment Trading)
- **Business Units**: DHPP, DMIE, OPS
- **Departments**: HR, Finance, Fleet, Operations (Dist & Haul), Compliance, Technical, IT
- **Branches**: N/A
- **Proprietor**: E. Bagatua
- **COO**: Clyde N. Rebollos (CNR) — final approval authority

### Segments Defined
| Segment | Business |
|---------|----------|
| **DHPP** | Fuel — distribution & hauling of petroleum products, tanker operations, billing, utilities |
| **DMIE** | Machineries — fuel dispensers, industrial equipment distribution |
| **OPS** | Other Products & Services — compliance, lubricants, job orders, calibration bucket |

---

## 2. CHART OF ACCOUNTS (392 accounts — all active)

### Key Facts
- **Maintained by**: Alywin only
- **New accounts**: Created by Alywin when needed (e.g., new department)
- **Structure can change**: Yes, if new departments or dimensions are added
- **Segments**: DHPP (code suffix 00), DMIE (03), OPS (06)
- **Transactions can span segments**: Yes (e.g., salary allocated across DHPP/DMIE/OPS)
- **Segments after posting**: Cannot change

### Future Dimensions Needed (Confirmed)
| Dimension | Status |
|-----------|--------|
| Vehicles | ✅ Already in COA |
| Departments | ✅ Already used |
| Customers | ❌ NEEDED — current system has incomplete customer list |
| Projects | ✅ Needed |
| Cost Centers | ✅ Needed |
| Warehouses | ✅ Needed |
| Branches | ✅ Needed |
| Suppliers | ✅ Already have |

### Critical Pain Point — Customers
> *"We have many customers, and we need a proper customer ledger. Our existing inventory system has a customer list but it is not complete."*

This must be a priority in Phase 2.

---

## 3. ACCOUNTING PROCESS (End-to-End)

### Document Flow
```
Department (initiates) 
    → Supporting Docs / PO / Receipt 
    → RFP (Request for Payment) 
    → Approval (Finance) 
    → AP Entry (Che — bookkeeper) 
    → Verification (Alywin — Accounting Head)
    → Treasury (Quibs — check budget & release)
    → Check Issuance / Encashment
    → Check Clearance (Bank)
    → Check Voucher Liquidation (Reverse Entry AP)
    → Filing
    → Journal Entry (must reflect in Ledger)
    → Ledger → Trial Balance → Financial Statements
```

### Transaction Types & Ownership
| Transaction | Initiator | Key Person | Reports Affected |
|------------|-----------|------------|-----------------|
| Sales | Customer PO → Anne/Bong | Mich → Alywin | IS, CF, BS |
| Purchases | Department request | Che | IS, CF, BS |
| Collections | Client payment (bank/office) | Mich | IS, CF, BS |
| Supplier Payments | Inventory (Adrian) → PO → RFP | Che → Alywin | IS, CF, BS |
| Fuel Purchases | Depot (Clyde/kamada) | Che | IS, BS |
| Payroll | DTR → Computation → Approval (Sir Boy) | Alywin | IS, CF, BS |
| Inventory | PO → RFP → Voucher | Che | IS, CF, BS |
| Depreciation | Monthly schedule | Alywin | IS, BS |
| Taxes | Extract SI entries (declared) | Alywin | IS |
| Loans | RFP → Voucher | Alywin | IS, BS, CF |
| Adjustments | Error correction, reversal, accrual | Alywin | IS, BS, CF |
| Journal Entries | General/Special journals | Alywin | BS |

---

## 4. SOURCE DOCUMENTS (All must be in system)

Confirmed: Purchase Request, Purchase Order, Receiving Report, Sales Invoice, Official Receipt, Delivery Receipt, Journal Voucher, Disbursement Voucher, Payroll Summary, Fuel Receipt, Collection Receipt, Bank Deposit Slip, Inventory Count Sheet

**Corrections**: Allowed on all documents.

---

## 5. ACTUAL POSTING RULES (from Acctg-Entry-finance-and-acctg.xlsx)

The accounting team already documented their actual journal entries. 14 transaction categories:

### 5.1 Machinery Sales (DMIE)
| Step | Event | Debit | Credit |
|------|-------|-------|--------|
| 1 | Purchase of Machine | Dr. Purchase-TSRO / Dr. Input VAT | Cr. Cash/AP |
| 2 | Client Deposit | Dr. Cash | Cr. Customer's Deposit |
| 3 | Full Payment | Dr. Cash | Cr. Customer's Deposit |
| 4 | Delivery to Client | Dr. Sales Receivable + Dr. Customer's Deposit | Cr. Output VAT + Cr. Sales Revenue |
| | COGS at Delivery | Dr. Cost of Sales | Cr. Machine Inventory |
| 5 | Collection of Receivable | Dr. Cash | Cr. Sales Receivable |

### 5.2 Fuel Transactions (DHPP) — Most complex
| Step | Event | Debit | Credit |
|------|-------|-------|--------|
| 1 | Ordering to Depot | Dr. Advances to Suppliers | Cr. Cash in Bank |
| 2a | Pickup (already paid) | Dr. Fuel Inventory | Cr. Advances to Suppliers |
| 2b | Pickup (credit) | Dr. Fuel Inventory | Cr. AP Current |
| 3 | Client Payment (pre-delivery) | Dr. Cash in Bank | Cr. Unearned Income |
| 3b | Payment + Previous Balance | Dr. Cash + Dr. Unearned (settle) + Dr. AR | Cr. Unearned Income + Cr. AR |
| 4 | Fuel Transfer to Substation | Dr. Fuel Inventory - Office | Cr. Fuel Inventory |
| | Fuel for Tanker Consumption | Dr. COGS-Gasoline Expenses | Cr. Fuel Inventory |
| 5 | Delivery to Client (paid) | Dr. COGS-Fuel Purchase | Cr. Fuel Inventory |
| | | Dr. Unearned Income | Cr. Sales-Fuel Hauling |
| 5b | Delivery (unpaid) | Dr. AR-Fuel Clients | Cr. Sales-Fuel Hauling |
| | | Dr. COGS-Fuel Purchase | Cr. Fuel Inventory |

### 5.3 Bulilit Station (Contractor Model)
Client pays → Recognize Payable to Contractor + Other Income → Remit to Contractor

### 5.4 Consignment Sales
Setup SOA → Dr. Cash + Dr. AR-Consignment + Dr. COGS | Cr. Inventory + Cr. Sales → Collection of AR

### 5.5 Installment Sales (with Freebies)
Receive freebies → Dr. Inventory | Cr. Gain on Freebies
Sold (DP) → Dr. Cash + Dr. AR-Installment | Cr. Inventory
And → Dr. Reversal of Gain on Freebies | Cr. Other Income

### 5.6 Job Orders (OPS)
Prepayment → Dr. Cash | Cr. Unearned Income
Service rendered → Dr. Unearned Income | Cr. Job Orders
Post-service payment → Dr. Cash | Cr. Job Orders

### 5.7 Loans & Financing
Asset acquisition → Dr. Asset | Cr. Cash/AP
Loan recognition → Dr. Asset/Cash | Cr. Loans Payable + Interest
Fees → Dr. Notarial/DST | Cr. Cash/AP
Insurance → Dr. Prepaid Insurance | Cr. Cash/AP
Monthly payment → Dr. Interest Expense + Dr. Loans Payable | Cr. Cash

### 5.8 Government Contributions
Salaries → Dr. Salaries Expense | Cr. SSS/PHIC/HDMF Payable + W/H Tax + Accrued Salaries
ER Shares → Dr. Gov't Remittances | Cr. ER SSS/PHIC/HDMF Payable
RFP → Dr. All Payables | Cr. AP-Others
Payment → Dr. AP-Others | Cr. Cash

### 5.9 Salaries & Wages
Dr. COGS-Labor + Dr. Salaries & Benefits | Cr. SSS/PHIC/HDMF + W/H Tax + Accrued Salaries Payable

---

## 6. APPROVAL MATRIX

| Item | Approver |
|------|----------|
| Purchases | CNR (COO) |
| Payments | Alywin → CNR |
| Journal Entries | Alywin |
| Asset Purchases | CNR |
| Inventory Adjustments | Cherry → James → Alywin |
| Write-offs / Bad Debts | Management → CNR |
| Manual Adjustments | Alywin |

---

## 7. PAIN POINTS & BOTTLENECKS

| Issue | Severity |
|-------|----------|
| **AR (Payment & Pricing)** — Most time-consuming | 🔴 High |
| **Hauling Sales + PO** — Biggest bottleneck | 🔴 High |
| **Wrong accounts / Typo errors** — Most common errors (no force-balance feature allowed) | 🔴 High |
| **Manual posting** — Everything is manual | 🟡 Medium |
| **Incomplete customer list** — Inventory system has partial data only | 🟡 Medium |
| **Tax estimation** — "bana-bana" (guess-timate) for expenses | 🟡 Medium |
| **AR tracking** — Difficult to track customers across segments | 🔴 High |

---

## 8. INTEGRATION REQUIREMENTS (All confirmed "must have")

| System | Events to Accounting |
|--------|---------------------|
| **Inventory** (separate system) | Stock in/out → Inventory value, COGS |
| **Procurement** | PR → PO → Receiving → Supplier Invoice → AP |
| **Fleet** | Fuel Purchases, Vehicle Expenses, GPS/Cartrack, Maintenance |
| **Sales** | Sales Orders (PO) → Sales Invoices → Collections |
| **HR & Payroll** | Payroll Summary, Employee Benefits, Government Contributions |
| **Fixed Assets** | Acquisition, Depreciation, Disposal |

> **Key**: The inventory system is separate and will need API integration with this accounting system.

---

## 9. OBSERVATION PERIOD — APPROVED

The 2-week observation was approved by the accounting head. This validates:
- Daily transaction intake
- Source document movement
- Journal preparation
- Posting process
- Reconciliations
- Month-end activities
- Report generation
- Approval flow
- Cross-department coordination

---

## 10. ARCHITECTURAL DECISIONS (ADRs to Make)

Based on the workshop, the following decisions are now clear:

1. **Architecture**: Modular Django monolith → Microservices later if needed
2. **Segmentation**: Segment (DHPP/DMIE/OPS) as first-class dimension on every transaction
3. **Allocation**: Salary and shared expenses must support multi-segment allocation
4. **Customer Ledger**: Must be centralized within accounting system (not relying on inventory system)
5. **No force-balance**: System must never auto-balance journal entries — prevents typo masking
6. **Posting**: Event-driven posting engine matching Acctg-Entry Excel rules
7. **Approval workflow**: Hierarchical (Staff → Head → COO for high-value)
8. **Audit trail**: Immutable JEs, corrections via reversal only
9. **Inventory integration**: API bridge to existing inventory system
10. **Observation**: 2-week validation before final implementation

---

## 11. REVISED IMPLEMENTATION ROADMAP

Based on confirmed pain points:

| Phase | Focus | Why This Order |
|-------|-------|----------------|
| **Phase 1** | Foundation: COA, JE, GL, Trial Balance, Posting Engine | Core must exist before anything |
| **Phase 2** | **Customer Ledger + AR + Collections** | Biggest bottleneck (AR tracking) |
| **Phase 3** | AP + Procurement (PR → PO → RR → Supplier Invoice) | Second biggest bottleneck (PO) |
| **Phase 4** | Cash & Bank + Cash Flow + Reconciliation | Weekly cash cycle |
| **Phase 5** | Inventory Integration (API bridge to existing system) | Inventory values → GL |
| **Phase 6** | Fleet Management (Fuel, Trips, Maintenance) | Fuel hauling core operations |
| **Phase 7** | Payroll (with multi-segment allocation) | Shared across all segments |
| **Phase 8** | Fixed Assets + Depreciation | Monthly/Yearly |
| **Phase 9** | Reporting: All FS + Management Reports | Depends on all modules |
| **Phase 10** | Tax module (SI extraction, VAT, WHT, income tax) | Remove "bana-bana" estimation |

> **2-Week Observation**: Should start immediately. Validates workflow before Phase 1 coding begins.
