# Subsidiary Ledgers & Master Data Design

> Every ledger, register, and master data required by the Seven-Trent Enterprise Accounting Platform.
> Derived from: COA, Trial Balance, Acctg-Entry posting rules, 6 Financial Statements, Cash Flow sheets, Workshop Discovery.

---

## 1. MASTER DATA (Shared Enterprise Register)

These are core entities referenced by every module. They are **authoritative** — maintained in this system and consumed by external systems via API.

### 1.1 Chart of Accounts (Account Master)
**Source**: COA-STMIET-2026.xlsx (392 records)
**Maintained by**: Alywin
**Fields**: Code, Title, Segment, Classification, Category, Sub-Account, Major Account, Normal Balance, Behavior (V/F), Traceability (D/I), Controllability (C/UC), Is Active, Is Contra, FS Line Item Sequence
**Use**: Every journal entry line references an Account. Every financial statement aggregates by account hierarchy.
**API**: `/api/accounts/` — consumed by inventory system for COGS account mapping

### 1.2 Segment Master
**Source**: Workshop discovery + AP shadow
**Values**:
| Code | Name | COA Suffix | Unearned Revenue GL | Notes |
|------|------|-----------|-------------------|-------|
| DHPP | Distribution & Hauling of Petroleum Products | 00 | 21000 | Primary segment — fuel hauling |
| DMIE | Industrial Equipment / Machinery | 03 | 21023 | TSRO machines, dispensers, tanks |
| OPS | Operations / Services | 06 | 21016 | Calibration, job orders, COC |
| STPC | Seven-Trent Petroleum Corp. | ⚠️ **None (uses DHPP)** | 15500 (Due from) | Sister company — intercompany only |

**Gap**: STPC has no dedicated COA suffix. Transactions use DHPP accounts (suffix 00) with manual STPC tag.

**Fields**: Code, Name, Company, COA Suffix, Default Unearned Revenue GL, Is Active, Is Intercompany

**Use**: Every transaction, JE line, and GL balance is tagged with segment. Reports can be rolled up or drilled down by segment. At reporting time, STPC must be separated from DHPP via segment tag despite sharing GL accounts.

### 1.3 Company / Legal Entity Master
**Source**: Workshop discovery
**Current**: STMIET (Seven-Trent Machineries Industrial Equipment Trading)
**Fields**: Code, Name, Address, TIN, Proprietor, Fiscal Year
**Future**: May expand to STPC, STMIET, or other entities

### 1.4 Customer Master
**Source**: Workshop — **CRITICAL GAP** — current inventory system has incomplete list
**Maintained by**: Mich (AR)
**Fields**: Customer Code, Name, TIN, Address, Contact Person, Credit Limit, Payment Terms, Segment Default, Is Active, Customer Group (Fuel/Equipment/OPS)
**Relations**: Has many SalesInvoices, CollectionReceipts, AR balances
**API**: Exposed to inventory system as authoritative customer source
**Import**: One-time migration from inventory system + manual cleanup

### 1.5 Supplier Master
**Source**: Workshop — already exists
**Maintained by**: Che (AP)
**Fields**: Supplier Code, Name, TIN, Address, Contact Person, Payment Terms, Bank Details, Is Active, Supplier Type (Depot/Equipment/Service/Govt)
**Relations**: Has many PurchaseOrders, SupplierInvoices, AP balances

### 1.6 Employee Master
**Source**: Workshop — Alywin handles payroll
**Fields**: Employee ID, Full Name, Position, Level (R&F/Supervisor/Dept Head/Executive), Segment, Basic Salary, Tax Status, SSS/PHIC/HDMF Numbers, Bank Details, Date Hired, Is Active
**Relations**: Has many PayrollItems, linked to Vehicles (drivers)

### 1.7 Vehicle Master
**Source**: COA accounts 17000-18650 + Workshop
**Fields**: Plate Number, Vehicle Type (Fuel Tanker/Boom Truck/Office Vehicle/Other), Brand, Model, Year, Acquisition Cost, Acquisition Date, Status (Active/In Repair/Decommissioned), Assigned Driver, Segment, Linked Asset
**Relations**: Has many Trips, FuelConsumptions, MaintenanceRecords
**Types from COA**:
| Account | Type |
|---------|------|
| 17000 | Tanker Cab and Chassis |
| 17010 | Fuel Tankers |
| 18503 | Boom Trucks |
| 18600 | Office Vehicles |
| 18650 | Other Vehicle/Specialized/Heavy Equip. |
**Import**: From existing fleet records

### 1.8 Product / Inventory Master
**Source**: COA accounts 13000-13116 + Inventory system
**Fields**: Product Code, Barcode, Name, Category, Product Type (FUEL/LUBRICANT/SPARE_PART/EQUIPMENT/SUPPLIES), UOM, Is Stockable, Standard Cost
**Product Types from COA**:
| COA Range | Product Type |
|-----------|-------------|
| 13000-13020 | Fuel |
| 13030 | Spare Parts for Vehicle |
| 13040 | Lubricants for Consumption |
| 13053 | Spare Parts for Machinery |
| 13066 | Lubricants for Sale |
| 13073 | Industrial Equipment |
| 13080 | Tires |
| 13093 | Machinery (TSRO/LFRO) |
| 13106-13116 | Other Materials |

### 1.9 Bank Account Master
**Source**: CASH END / trial; sheets — **12 bank accounts identified**
**Maintained by**: Quibs
**Fields**: Bank Name, Account Number, Account Type (Savings/Checking/OPEX), Segment, GL Account Mapping, ADB/Maintaining Balance, Is Active
**Actual Bank Accounts from CASH FLOW sheets**:
| Bank | Type | Maintaining Balance |
|-----|------|-------------------|
| PNB | OPEX | 50,000 |
| PNB | Checking | — |
| PSBC | Savings | 5,000 |
| PSBC | Checking | 5,000 |
| KB | Checking | 5,000 |
| KB | Savings | — |
| 1VB | — | 5,000 |
| BDO | — | 5,000 |
| MBTC | — | 50,000 |
| RCBC | — | 5,000 |
| CHINA BANK | — | 5,000 |
| E.TAN/STPC | — | — |
| PCF & COH | Petty Cash | 20,000 |

**Relations**: Has many BankTransactions, BankReconciliations

### 1.10 Fixed Asset Master
**Source**: COA accounts 17000-19976
**Maintained by**: Alywin
**Fields**: Asset Code, Name, Category, Segment, Acquisition Date, Cost, Salvage Value, Useful Life, Depreciation Method (SL/DB), Status (Active/Fully Depreciated/Disposed/Impaired), Location, Linked Vehicle
**Asset Categories from COA**:
| Account | Category | Useful Life |
|---------|----------|------------|
| 17000-17010 | Tanker Cab and Chassis / Fuel Tankers | 10-15 yrs |
| 18503-18513 | Boom Trucks | 10 yrs |
| 18600-18650 | Office Vehicles / Other Vehicles | 5-7 yrs |
| 19000-19750 | Building and Improvements | 15-20 yrs |
| 19800 | Furniture and Fixtures | 5 yrs |
| 19900-19966 | Office Equipment | 3-5 yrs |

### 1.11 Department Master
**Source**: Workshop
**Departments**: HR, Finance, Fleet, Operations (Dist & Haul), Compliance, Technical, IT
**Future**: Cost allocation and expense tracking by department

### 1.12 Project Master
**Source**: Workshop — confirmed future need
**Fields**: Project Code, Name, Segment, Start Date, End Date, Budget, Status
**Use**: Project-based cost tracking

### 1.13 Cost Center Master
**Source**: Workshop — confirmed future need
**Fields**: Code, Name, Department, Segment, Manager
**Use**: Cost allocation and responsibility accounting

### 1.14 Warehouse / Location Master
**Source**: COA (13010 Fuel Inventory at Dohinob, 13012 at San Pedro, 13020 at Office)
**Fields**: Code, Name, Address, Segment, Is Active
**Locations**: Dohinob, San Pedro, Office + future warehouses

### 1.15 Tax Code Master
**Source**: COA accounts 63600-64606 + workshop
**Tax Types**: VAT (12%), Withholding Tax (Compensation/Expanded/Final), DST, Income Tax, Business Registration

---

## 2. TRANSACTIONAL SUBSIDIARY LEDGERS

### 2.1 Customer / Accounts Receivable Ledger
**Purpose**: Track every customer's outstanding balance, aging, payment history
**Source**: Workshop — identified as **biggest bottleneck**
**Components**:
| Model | Key Fields | Linked To |
|-------|-----------|-----------|
| Customer | Code, Name, Credit Limit, Terms | Segment |
| SalesInvoice | SI#, Customer, Date, Due, Gross, Disc, Net, VAT, Status | Customer, Segment, JE |
| SalesInvoiceLine | Item, Qty, Price, Amount, Account | SI, Product, Account |
| CollectionReceipt | CR#, Customer, Amount, Method, Bank | Customer, Bank, JE |
| ReceiptAllocation | CR, SI, Amount Applied | CR, SI |
| OfficialReceipt | OR#, CR, Customer, Amount, Date | CR, Customer |
| CashReceiptJournal | Cycle, Collections, Depot, Markup, Short/Excess | Segment, JE |
| CreditNote | CN#, SI, Amount, Reason | SI, JE |

**Key Reports**: AR Aging (30/60/90/120+), Customer Statements, Collections Summary

### 2.2 Supplier / Accounts Payable Ledger
**Purpose**: Track supplier payables, due dates, payment status
**Maintained by**: Che
**Components**:
| Model | Key Fields | Linked To |
|-------|-----------|-----------|
| Supplier | Code, Name, Terms, Bank | — |
| PurchaseRequest | PR#, Requester, Date, Status, Approval | Segment |
| PRItem | PR, Product, Description, Qty, Est Cost, Account | PR, Product, Account |
| PurchaseOrder | PO#, Supplier, Date, Amount, Status | Supplier, Segment |
| POItem | PO, Product, Qty, Price, Amount, Qty Received | PO, Product, Account |
| ReceivingReport | RR#, PO, Date, Received By | PO, JE |
| RRItem | RR, POItem, Qty Received | RR, POItem |
| SupplierInvoice | SI#, Supplier, Date, Due, Amount, Status | Supplier, PO, JE |
| RFP | RFP# (A####), Payee, Amount, Purpose, Status, Segment | Supplier, JE, Segment |
| RFPApproval | RFP, Step (Checker/Acctg Mgr/Finance Mgr), Approver, Date, Status | RFP, User |
| CONSOBatch | CONSO#, Date, Total, Status | Segment, JE |
| CONSOItem | CONSO, RFP, Amount | CONSO, RFP |
| CheckVoucher | CV#, Payee, Amount, Bank, Status | Supplier, Bank, RFP |
| DisbursementVoucher | DV#, Payee, Date, Amount, Status | Segment, JE |
| DVAllocation | DV, SI, Amount | DV, SI |

**Key Reports**: AP Aging, Due Date Report, Unpaid Invoices, RFP Approval Status, CONSO Batch Summary

### 2.2A Advances to Employees Ledger
**Purpose**: Track employee/officer advances and liquidations
**Maintained by**: Che (via RFP), Alywin (liquidation)
**Components**:
| Model | Key Fields | Linked To |
|-------|-----------|-----------|
| AdvanceToEmployee | RFP, Employee, Amount (default P20,000), Outstanding, Status | RFP, Employee |
| AdvanceLiquidation | Advance, Receipts, Actual Expenses, Refund/Top-up Amount | Advance, JE |

**Flow**:
```
RFP Created: Cr Advances to Employees P20,000 (clearing)
Liquidation: Dr Advances to Employees P20,000 → Cr Actual Expenses
```

**Key Reports**: Outstanding Advances Aging, Employee Advance Summary, Overdue Advances

### 2.3 Cash & Bank Ledger
**Purpose**: Track all cash movements across 12 bank accounts + PCF
**Maintained by**: Quibs
**Components**:
| Model | Key Fields | Linked To |
|-------|-----------|-----------|
| BankAccount | Bank, Account#, Type, Maintaining Balance, GL Account | Segment |
| BankTransaction | Bank, Date, Description, Debit, Credit, Ref# | Bank, JE |
| BankReconciliation | Bank, Statement Date, Book Balance, Bank Balance, DIT, OC, Variance | Bank, JE |
| PettyCashFund | Fund Code, Custodian, Imprest Amount, Current Balance | Segment, Account |
| PettyCashReplenishment | PCF, Date, Total, Amount, Status | PCF, JE |
| PettyCashExpense | Replenishment, Description, Amount, Account | Replenishment, Account |
| CashReceiptJournal | Cycle Start/End, Segment, Collections, Depot, Markup, Deposits, Short/Excess | Segment, JE |
| CashFlowSummary | Cycle, Operating/Investing/Financing totals, Beginning/Ending Cash | Period |

**Weekly Cycle Flow** (from COLLECTIBLES/CASH SHORT sheets):
```
Distribution Dept: Client Paid Total → Less Depot Paid = Gross Mark-up
Finance Dept: Total Deposited vs Collections = Cash Short/Excess
Reconciliation: Passbook + GCash + Other Credits vs Cashier Records
```

**Key Reports**: Weekly Cash Flow, Bank Reconciliation, Cash Position (per bank), PCF Report

### 2.4 Inventory Ledger
**Purpose**: Track inventory quantities and values across warehouses
**Source**: Acctg-Entry INVENTORIES sheet + COA
**Components**:
| Model | Key Fields | Linked To |
|-------|-----------|-----------|
| Product | Code, Name, Category, Type, UOM, Standard Cost | ProductCategory |
| ProductCategory | Code, Name, Parent, Inventory/Revenue/COGS Account | Account |
| Warehouse | Code, Name, Address | Segment |
| StockTransaction | Product, Warehouse, Type (GR/GI/TR/ADJ/SR), Qty, Cost, Total | Product, Warehouse, JE |
| InventoryBalance | Product, Warehouse, Qty, Unit Cost, Total Value | Product, Warehouse |
| PhysicalCount | Product, Warehouse, Date, System Qty, Actual Qty, Variance | Product, Warehouse, JE |

**Inventory Flow** (from Acctg-Entry):
```
Purchase: DR Advances to Supplier → CR AP Current
Payment: DR AP Current → CR Cash in Bank
Receipt: DR Inventory → CR Advances to Supplier
Sale: DR COGS → CR Inventory + DR Unearned/AR → CR Sales
Consumption: DR Gasoline/Expense → CR Fuel Inventory
Transfer: DR Fuel Inventory-Location → CR Fuel Inventory
```

**Key Reports**: Inventory Valuation, Stock Card, Physical Count Variance, Reorder Report

### 2.5 Fleet Ledger
**Purpose**: Track vehicle operations, trips, fuel consumption, maintenance
**Source**: COA accounts + Acctg-Entry FUEL sheets
**Maintained by**: Fleet department
**Components**:
| Model | Key Fields | Linked To |
|-------|-----------|-----------|
| Vehicle | Plate#, Type, Brand, Model, Year, Cost, Status, Driver | VehicleType, Segment, Asset |
| VehicleType | Code, Name, Asset/Depreciation/Accum Dep Account | Account |
| Trip | Trip#, Vehicle, Driver, Dates, Origin/Destination, Load, Status | Vehicle, Customer, Segment |
| FuelConsumption | Vehicle, Date, Liters, Unit Cost, Total, Odometer | Vehicle, Trip |
| MaintenanceRecord | Vehicle, Date, Type (Routine/Repair/Overhaul), Cost, Provider | Vehicle, Account, Segment |

**Key Reports**: Trip Profitability, Fuel Consumption per Vehicle, Maintenance Cost Report, Fleet Utilization

### 2.6 Payroll Ledger
**Purpose**: Track employee earnings, deductions, net pay, and employer contributions
**Maintained by**: Alywin
**Components**:
| Model | Key Fields | Linked To |
|-------|-----------|-----------|
| Employee | ID#, Name, Position, Level, Salary, Tax Status, Govt #s | Segment |
| PayrollPeriod | Code, Start, End, FiscalPeriod | FiscalPeriod |
| PayrollRun | Period, Segment, Date, Status | PayrollPeriod, Segment, JE |
| PayrollItem | Run, Employee, Basic Pay, OT, Allowances, Bonus, 13th Month, SSS/PHIC/HDMF (EE), WHT, SSS/PHIC/HDMF (ER), Gross, Net | PayrollRun, Employee |
| GovernmentRemittance | Period, Type (SSS/PHIC/HDMF), EE Total, ER Total, Paid Date | JE |

**Payroll JE Flow** (from Acctg-Entry):
```
DR COGS-Labor Wages (operational staff)
DR Salaries & Benefits (admin staff)
CR SSS Payable (EE)
CR HDMF Payable (EE)
CR PHIC Payable (EE)
CR Withholding Tax Payable
CR Accrued Salaries Payable (net)

DR Government Remittances (ER shares)
CR ER SSS Payable
CR ER HDMF Payable
CR ER PHIC Payable
```

**Key Reports**: Payroll Summary by Segment, Government Remittance Schedule, 13th Month Projection

### 2.7 Fixed Asset Ledger
**Purpose**: Track asset register, depreciation, disposals
**Maintained by**: Alywin
**Components**:
| Model | Key Fields | Linked To |
|-------|-----------|-----------|
| AssetCategory | Code, Name, Useful Life, Dep Method, Asset/Dep/Accum/GL Accounts | Account |
| Asset | Code, Name, Category, Segment, Date, Cost, Salvage, Life, Status | AssetCategory, Segment, Vehicle |
| DepreciationEntry | Asset, Period, Amount | Asset, FiscalPeriod, JE |
| AssetDisposal | Asset, Date, Type, Proceeds, Gain/Loss | Asset, JE |

**Key Reports**: Asset Register, Monthly Depreciation Schedule, Asset Movement Report

### 2.8 Loans Ledger
**Purpose**: Track loans payable, amortization, interest
**Source**: Acctg-Entry LOAN_FINANCING-ORIX + LOANS PAYABLE-OFFICERS
**Components**:
| Model | Key Fields | Linked To |
|-------|-----------|-----------|
| LoanContract | Lender, Type (Bank/Officer/ORIX), Principal, Interest Rate, Terms, Start Date | Segment |
| LoanAmortizationSchedule | Loan, Date, Principal, Interest, Total, Balance | LoanContract |
| LoanPayment | Loan, Date, Principal, Interest, Total, Reference | LoanContract, JE |

**Loan JE Flow** (from Acctg-Entry):
```
DR Cash (loan proceeds)
DR Asset (if directly financing asset)
DR Notarial Fees / DST (loan fees)
CR Loans Payable
CR Interest Payable
```

**Key Reports**: Loan Amortization Schedule, Outstanding Loan Balance

### 2.9 Prepaid Expenses Ledger
**Purpose**: Track prepaid insurance, rent, subscription with amortization
**Source**: COA accounts 14000-14606
**Components**:
| Model | Key Fields | Linked To |
|-------|-----------|-----------|
| PrepaidSchedule | Account, Description, Total Amount, Period Start/End, Monthly Amort | Account, Segment |
| PrepaidAmortization | Schedule, Period, Amount | Schedule, FiscalPeriod, JE |

**Prepaid Accounts from COA** (21 accounts):
- 14000-14006: Prepaid Rent (DHPP/DMIE/OPS)
- 14010-14016: Prepaid Insurance
- 14020-14026: Prepaid Subscription
- 14030-14036: Prepaid Taxes
- 14040-14046: Prepaid Utilities
- 14050-14506: Prepaid Others

### 2.10 Accruals Ledger
**Purpose**: Track accrued expenses and recognize when due
**Components**:
| Model | Key Fields | Linked To |
|-------|-----------|-----------|
| AccrualEntry | Description, Account, Amount, Period, Reversal Date | Account, Period, JE |

**Accrued Expense Accounts from COA** (15 accounts):
- 22000-22006: Accrued Expenses Others
- 22010-22016: Accrued Utilities
- 22020-22026: Accrued Salaries

### 2.11 Deferred Revenue / Unearned Income Ledger
**Purpose**: Track customer prepayments and recognize when earned
**Source**: Acctg-Entry Fuel + Machinery sheets
**Components**:
| Model | Key Fields | Linked To |
|-------|-----------|-----------|
| UnearnedIncome | Customer, Description, Amount, Received Date, Recognition Schedule | Customer, Account |

**Unearned Income Accounts from COA**: 21000-21016

**Fuel Delivery Flow**:
```
Client pays → DR Cash | CR Unearned Income
Fuel delivered → DR Unearned Income | CR Sales
```

**Key Reports**: Unearned Income Aging, Revenue Recognition Schedule

### 2.12 Government Contributions Ledger
**Purpose**: Track SSS/PHIC/HDMF contributions per employee
**Source**: Acctg-Entry GOVT CONTRIBUTION sheet
**Components**:
| Model | Key Fields | Linked To |
|-------|-----------|-----------|
| GovtContributionSchedule | Employee, Period, Type, EE Amount, ER Amount | Employee, Period |

**Flow**: Accrual → Reversal → Actual Remittance
**Accounts from COA**: 23010-23066 (18 accounts for EE/ER SSS, PHIC, HDMF per segment)

### 2.13 Taxes Ledger
**Purpose**: Track output VAT, input VAT, withholding taxes, income tax
**Source**: COA accounts 63600-64606
**Components**:
| Model | Key Fields | Linked To |
|-------|-----------|-----------|
| TaxTransaction | Reference (SI/SI#), Type (VAT/WHT/EWT/DST), Amount, Period | SI/SI, Period |

**Tax Accounts from COA**:
- 63600-63606: Business Registration Fees
- 63610-63616: Documentary Stamp Tax
- 63620-63626: Taxes, Licenses, Penalties
- 64100-64106: Withholding Tax - Compensation
- 64110-64116: Withholding Tax - Expanded
- 64120-64126: Withholding Tax - Final
- 64600-64606: Income Tax

### 2.14 Journal Entry Audit Ledger
**Purpose**: Immutable record of every journal entry (immutable audit trail)
**Maintained by**: Alywin (approval), system (auto-posted)
**Components**:
| Model | Key Fields | Linked To |
|-------|-----------|-----------|
| JournalEntry | JE#, Date, Description, Period, Segment, Status, Source, Ref Type/Number, Posted By | FiscalPeriod, Segment |
| JournalEntryLine | JE, Line#, Account, Description, Debit, Credit, Source Type/ID | JE, Account |
| GeneralLedger | Account, Segment, Period, Beginning, Total Dr, Total Cr, Ending | Account, Segment, Period |

**Key Rules**:
- Once POSTED, no edits allowed
- Corrections require reversal JE + new JE
- No force balance (ADR-002)
- System-generated JEs track source document reference

---

## 3. SUBSIDIARY LEDGER RELATIONSHIP MAP

```
                        ┌─────────────────────┐
                        │   GENERAL LEDGER     │
                        │ (Account × Segment   │
                        │  × Period balance)   │
                        └──────────┬──────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
┌─────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│  AR Subsidiary   │   │   AP Subsidiary     │   │   Cash Subsidiary   │
│  Ledger          │   │   Ledger            │   │   Ledger            │
│                  │   │                     │   │                     │
│ Customers        │   │ Suppliers           │   │ Bank Accounts (12)  │
│ Sales Invoices   │   │ Purchase Orders     │   │ Bank Transactions   │
│ Collections      │   │ Supplier Invoices   │   │ Bank Reconciliations│
│ Receipts         │   │ Disbursements       │   │ PCF                 │
│ Customer Deposits│   │ PR → PO → RR → AP   │   │ Cash Flow Cycles    │
└─────────────────┘   └─────────────────────┘   └─────────────────────┘

┌─────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│ Inventory Sub.   │   │   Fleet Ledger      │   │   Payroll Ledger    │
│ Ledger           │   │                     │   │                     │
│                  │   │ Vehicles            │   │ Employees           │
│ Products         │   │ Trips               │   │ Payroll Runs        │
│ Warehouses (3)   │   │ Fuel Consumption    │   │ Govt Contributions  │
│ Stock Movements  │   │ Maintenance         │   │ Benefits Tracking   │
│ Physical Counts  │   │ Trip Profitability  │   │ 13th Month Accrual  │
└─────────────────┘   └─────────────────────┘   └─────────────────────┘

┌─────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│  Fixed Asset     │   │   Loans Ledger      │   │   Prepaids Ledger   │
│  Ledger          │   │                     │   │                     │
│                  │   │ Loan Contracts      │   │ Rent/Insurance/     │
│ Asset Register   │   │ Amortization Sched  │   │ Subscription/Taxes  │
│ Depreciation     │   │ Payments            │   │ Monthly Amortization│
│ Disposals        │   │ Interest Tracking   │   │                     │
└─────────────────┘   └─────────────────────┘   └─────────────────────┘

┌─────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│  Accruals        │   │  Deferred Revenue   │   │   Tax Ledger        │
│  Ledger          │   │  Ledger             │   │                     │
│                  │   │                     │   │ Output/Input VAT    │
│ Accrued Expenses │   │ Unearned Income     │   │ Withholding Tax     │
│ Accrued Salaries │   │ Recognition Sched   │   │ Income Tax          │
│ Accrued Utilities│   │ Customer Prepayments│   │ DST / Bus Reg       │
└─────────────────┘   └─────────────────────┘   └─────────────────────┘
```

---

## 4. SUBSIDIARY LEDGER → GENERAL LEDGER → FINANCIAL STATEMENT

Every subsidiary ledger posts summarized entries to the General Ledger:

```
Subsidiary Ledger              General Ledger               Financial Statement
─────────────────              ──────────────               ───────────────────
AR: Invoice total    ──────→   Dr AR (110xx)          ──→   Balance Sheet: AR
                     ──────→   Cr Revenue (4xxxx)      ──→   Income Statement: Sales
AP: Supplier invoice ──────→   Dr Inventory (130xx)    ──→   BS: Inventory
                     ──────→   Cr AP (200xx)           ──→   BS: Accounts Payable
Payroll: Gross pay   ──────→   Dr Salaries (634xx)     ──→   IS: Salary Expense
                     ──────→   Cr Accruals (220xx)     ──→   BS: Accrued Salaries
Cash: Collection     ──────→   Dr Cash (100xx)         ──→   BS: Cash
                     ──────→   Cr AR (110xx)           ──→   BS: Accounts Receivable
```

---

## 5. SUBSIDIARY LEDGER TYPES BY MODULE

| Module | Primary Ledger | Sub-Ledgers | Master Data |
|--------|---------------|-------------|-------------|
| Foundation | General Ledger | — | Account, Segment, Company, FiscalPeriod |
| AR | Customer Ledger | Sales, Collections, Deposits, Consignment, Installment | Customer |
| AP | Supplier Ledger | PR, PO, RR, SI, DV, Contractor | Supplier |
| Cash | Bank Ledger | Bank Account, PCF, Bank Recon, Cash Cycle | BankAccount |
| Inventory | Stock Ledger | Product, Warehouse, Movements, Physical Count | Product, Warehouse |
| Fleet | Vehicle Ledger | Trips, Fuel, Maintenance | Vehicle, VehicleType |
| Payroll | Employee Ledger | Payroll Run, Govt Remittances | Employee |
| Fixed Assets | Asset Ledger | Depreciation, Disposal | Asset, AssetCategory |
| Loans | Loan Ledger | Amortization, Payments | LoanContract |
| Prepaids | Prepaid Ledger | Amortization | PrepaidSchedule |
| Accruals | Accrual Ledger | — | — |
| Deferred Revenue | Unearned Income Ledger | Recognition Schedule | — |
| Taxes | Tax Ledger | VAT, WHT, Income Tax | TaxCode |

---

## 6. IMPLEMENTATION ORDER

Based on pain points identified in workshop + file analysis:

| Priority | Ledger | Reason |
|----------|--------|--------|
| 1 | General Ledger + COA | Foundation — everything depends on this |
| 2 | AR Ledger + Customer Master | Biggest bottleneck (AR tracking & pricing) |
| 3 | Cash & Bank Ledger | Weekly cash cycle, 12 banks, reconciliation |
| 4 | AP Ledger + Supplier Master | Second bottleneck (PO processing) |
| 5 | Inventory Ledger | Integration with existing inventory system |
| 6 | Fleet Ledger | Core to DHPP operations |
| 7 | Payroll Ledger | Multi-segment allocation needed |
| 8 | Fixed Asset Ledger | Monthly depreciation cycle |
| 9 | Loans, Prepaids, Accruals, Deferred, Taxes | Month-end closing |
