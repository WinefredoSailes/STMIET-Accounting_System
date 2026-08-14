# Accounting ERP — System Architecture

## 1. Business Context

| Item | Value |
|------|-------|
| Entity | Seven-Trent Machineries Industrial Equipment Trading |
| Ownership | Sole Proprietorship (E. Bagatua) |
| Business Units | DHPP (Fuel Hauling), DMIE (Industrial Equipment), OPS (Operations) |
| Employees | R&F, Supervisor, Dept. Head, Executive levels |
| Current State | Excel-driven accounting, weekly cash cycles, manual FS preparation |

## 2. Architecture Philosophy

**Modular Monolith (Django) — split into microservices only when needed.**

All modules share one database and one Django project. ERPs have extremely tight coupling between modules (e.g., AR ↔ GL ↔ Inventory). Premature microservices create distributed transaction nightmares. Split only when a module needs independent deployability or team ownership.

## 3. Layered Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                     │
│  Django REST Framework (API) + React/Vue/HTMX Frontend   │
├─────────────────────────────────────────────────────────┤
│                    APPLICATION LAYER                      │
│  ┌─────────┐ ┌──────────┐ ┌────────┐ ┌───────────────┐ │
│  │ Services │ │ Workflows│ │ Tasks  │ │ Posting Engine│ │
│  └─────────┘ └──────────┘ └────────┘ └───────────────┘ │
├─────────────────────────────────────────────────────────┤
│                    DOMAIN LAYER (Django Models)           │
│  ┌──────────┐ ┌──────┐ ┌───────┐ ┌───────┐ ┌────────┐  │
│  │Foundation│ │AR/AP │ │Inventory│ │Fleet  │ │Payroll │  │
│  │(COA, JE) │ │Cash  │ │ & FA  │ │Mgmt   │ │ & HR   │  │
│  └──────────┘ └──────┘ └───────┘ └───────┘ └────────┘  │
├─────────────────────────────────────────────────────────┤
│                    INFRASTRUCTURE                         │
│  PostgreSQL │ Redis (cache/queue) │ S3 (documents)       │
└─────────────────────────────────────────────────────────┘
```

## 4. Module Architecture

### 4.1 Foundation Layer (Core)
```
company/
├── models
│   ├── Company          — Legal entity (extensible for multi-company)
│   ├── Segment          — Business unit (DHPP, DMIE, OPS)
│   ├── FiscalYear       — Fiscal year definition
│   ├── FiscalPeriod     — Monthly periods within FY
│   └── Account          — Chart of Accounts (all 392 entries)
├── services
│   ├── coa_importer     — Import COA from Excel
│   └── period_closer    — Month-end & year-end close
└── posting_engine/
    ├── PostingRule       — Rule definition (event → JE template)
    ├── PostingService    — Executes rules, creates Journal Entries
    └── JournalEntry      — Header with reversal, recurring flags
```

### 4.2 Order-to-Cash (AR)
```
├── Customer             — Customer master
├── SalesInvoice         — Billing document
├── CollectionReceipt    — Payment received
├── OfficialReceipt      — Official receipt issued
├── CreditNote           — Sales returns/credit
├── CashReceiptJournal   — Daily collections summary
└── ReceivablesAging     — Aging report
```

### 4.3 Procure-to-Pay (AP)
```
├── Supplier             — Supplier master
├── PurchaseRequest      — Internal request
├── PurchaseOrder        — Order to supplier
├── ReceivingReport      — Goods received
├── SupplierInvoice      — Bill from supplier
├── DisbursementVoucher  — Payment voucher
├── CheckVoucher         — Check issuance
└── PayablesAging        — Aging report
```

### 4.4 Inventory Management
```
├── Product              — Item master (fuel, parts, equipment, lubricants)
├── ProductCategory      — Category hierarchy
├── Warehouse            — Physical storage (Dohinob, San Pedro, Office)
├── StockTransaction     — Every stock movement (IN/OUT/TRANSFER/ADJUST)
├── PhysicalCount        — Count sheet for inventory
└── InventoryValuation   — Costing method (moving average / FIFO)
```
> **Note**: Fuel Inventory module exists but is deactivated. Re-activate via feature flag when needed.

### 4.5 Fleet Management
```
├── Vehicle              — Vehicle register (tankers, boom trucks, office vehicles)
├── VehicleType          — Classification (Fuel Tanker, Boom Truck, Office Vehicle)
├── Trip                 — Delivery trip record
├── FuelConsumption      — Fuel usage per trip/vehicle
├── MaintenanceRecord    — Repairs & maintenance log
└── VehicleAssignment    — Driver/operator assignment
```

### 4.6 Payroll
```
├── Employee             — Employee master (with level: R&F, Supervisor, Dept Head, Exec)
├── PayrollPeriod        — Cut-off definition
├── PayrollRun           — Batch payroll computation
├── PayrollItem          — Individual pay items (salary, OT, allowance, govt shares)
├── GovernmentRemittance — SSS, PHIC, HDMF remittance tracking
└── PayrollJournal       — Journal entry generation from payroll
```

### 4.7 Fixed Assets
```
├── Asset                — Asset register
├── AssetCategory        — Building, Vehicle, Office Equipment, etc.
├── DepreciationMethod   — Method definitions (Straight-line, DB, etc.)
├── DepreciationSchedule — Monthly depreciation projection
└── AssetDisposal        — Disposal/retirement record
```

### 4.8 Cash & Bank
```
├── BankAccount          — Bank account register
├── PettyCashFund        — PCF register
├── PettyCashReplenishment — Replenishment requests
├── BankTransaction      — Bank statement lines
├── BankReconciliation   — reconciliation records
└── CashFlowStatement    — Weekly cash flow report data
```

### 4.9 Procurement
```
├── Bid / Quotation      — Supplier quotes
├── Contract             — Long-term supplier contracts
├── PurchaseRequestItem  — Line items with account coding
└── ApprovalMatrix       — Approval routing by amount & type
```

## 5. Integration Design

### 5.1 Event-Driven Posting
```
Business Event → PostingService → [Match PostingRule] → Create JournalEntry → Update GeneralLedger
```

Every operational module emits domain events:
- `sales.invoice_posted`
- `purchase.invoice_received`
- `inventory.stock_adjusted`
- `payroll.run_completed`
- `fleet.trip_completed`
- `asset.depreciation_booked`
- `cash.receipt_collected`

The **Posting Engine** listens and creates accounting entries.

### 5.2 Approval Workflow
```
Draft → Submitted → Approved (1st level) → Approved (2nd level) → Posted → Closed
```
Configurable per document type and amount threshold.

## 6. Reporting Architecture

```
Operational Data → General Ledger → Trial Balance → Financial Statements
                                          ↓
                                    Management Reports
                                    (Segment-wise P&L,
                                     Cash Flow Cycle,
                                     Appropriation Tracking)
```

### Built-in Reports (matching current Excel outputs):
1. Trial Balance (monthly with YTD)
2. Income Statement (by segment with grand total + appropriation computation)
3. Statement of Financial Position (year-end + ratios)
4. Statement of Cash Flows (weekly cycle format)
5. Cost of Sales Statement (by segment)
6. Total Expenses Statement
7. Statement of Changes in Equity
8. Weekly Collections Report
9. Cash Short/Excess Report
10. AR Aging
11. AP Aging
12. Inventory Valuation Report
13. Fleet Fuel Consumption Report

## 7. Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.x + Django REST Framework |
| Database | PostgreSQL (relational data + JSONB for flexible attributes) |
| Queue | Redis + Celery (async posting, report generation) |
| Search | PostgreSQL full-text search |
| File Storage | Local/S3 (source docs, receipts) |
| Frontend | React with TypeScript (or Django templates + HTMX for rapid delivery) |
| API | REST (JSON) + Webhooks for integrations |
| Auth | JWT + Role-Based Access Control |
| Docs | Swagger/OpenAPI |

## 8. Deployment

```
Development → Staging → Production

Containers:
- nginx (reverse proxy)
- django (gunicorn)
- postgres
- redis
- celery-worker
```

## 9. Development Phases

| Phase | Duration | Deliverables |
|-------|----------|-------------|
| Phase 1 | 8-10 weeks | Foundation: COA, JE, GL, Trial Balance, Posting Engine, Account import from Excel |
| Phase 2 | 6-8 weeks | AR/Cash: Customers, Sales Invoice, Collections, Cash Flow, Official Receipt |
| Phase 3 | 6-8 weeks | AP/Procurement: Suppliers, PO, Receiving, AP, Disbursement |
| Phase 4 | 8-10 weeks | Inventory: Products, Warehouses, Stock Transactions, Valuation |
| Phase 5 | 6-8 weeks | Fleet: Vehicles, Trips, Fuel Consumption, Maintenance |
| Phase 6 | 6-8 weeks | Payroll: Employees, Payroll Run, Govt Remittances |
| Phase 7 | 4-6 weeks | Fixed Assets: Register, Depreciation, Disposal |
| Phase 8 | 4-6 weeks | Reporting: All FS, Management Reports, Dashboards |
| Phase 9 | 4-6 weeks | Integration Testing, UAT, Data Migration, Go-Live |
| **Total** | **10-12 months** | |

> **Fast-track**: Phase 1 & 2 can replace the current Excel accounting and are the highest priority.
