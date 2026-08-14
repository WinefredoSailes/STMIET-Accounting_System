# ACCOUNTING SYSTEM DISCOVERY WORKSHOP — CONSOLIDATION

**Date**: July 18, 2026
**Attendees**: Accounting Manager, Senior Accountant, Accounting Staff, Finance Representative, Systems Architect
**Recording**: `meeting-2026-07-18.m4a`

---

## PART 1 — COMPANY ACCOUNTING OVERVIEW

### Responsibilities
<!-- Capture what the accounting team said their responsibilities are -->

### Team Structure
| Role | Person | Handles |
|------|--------|---------|
| Cash | | |
| Payables | | |
| Receivables | | |
| Payroll | | |
| Inventory | | |
| Tax | | |
| Financial Statements | | |

### Work Division
<!-- By Business Unit? Branch? Company? Function? -->

### Companies Managed
| Company | Code | Notes |
|---------|------|-------|
| STPC | | |
| STMIET | | |
| Others? | | |

---

## PART 2 — CHART OF ACCOUNTS REVIEW

### COA Code Assignment
<!-- How assigned? Who creates? Can it change? -->

### Account Titles
<!-- Naming convention? Duplicates? Inactive accounts? -->

### Segments (DHPP / DMIE / OPS)
<!-- What exactly does each represent? Can a transaction belong to multiple? Can it change after posting? -->
- **DHPP**: Dstribution and Hauling of Petroleum Products
- **DMIE**: Distribution of Machineries and Industrial Equipment
- **OPS**: Other Products and Services

### Classification
<!-- For reporting or posting? -->

### Category
<!-- Purpose and difference from Classification -->

### Major Account → FS Mapping
<!-- How do they map to BS, IS, Cash Flow -->

### Parent/Sub Account Hierarchy
<!-- How deep? Example given: Fuel Expense → Diesel, Gasoline, Lubricants -->

### Future Dimensions Expected
<!-- Projects? Vehicles? Departments? Cost Centers? Branches? -->

---

## PART 3 — FINANCIAL STATEMENTS

### Income Statement
<!-- How is every number produced? Auto/Manual/Excel? Which accounts feed it? -->

### Balance Sheet
<!-- How often generated? Daily/Monthly/Yearly? -->

### Cash Flow
<!-- Manual preparation? How long does it take? -->

### Cost of Sales
<!-- Calculation method: FIFO/Moving Average/Specific Identification/Manual? -->

### Expenses
<!-- How categorized? Fuel, Maintenance, Repairs, Office, Payroll, Utilities -->

### Equity
<!-- Who prepares? How often? -->

---

## PART 4 — ACCOUNTING PROCESS (Daily Workflow)

### Daily Timeline
| Time | Activity |
|------|----------|
| 8:00 AM | |
| 9:00 AM | |
| 10:00 AM | |
| 11:00 AM | |
| 12:00 PM | |
| 1:00 PM | |
| 2:00 PM | |
| 3:00 PM | |
| 4:00 PM | |
| 5:00 PM | |

### Document Flow
<!-- What arrives first? Emails? Receipts? Invoices? Purchase Orders? -->

---

## PART 5 — TRANSACTION TYPES

| Transaction | Started By | Prepared By | Approved By | Recorded By | Storage | Verification | Reports Affected |
|------------|-----------|------------|------------|------------|---------|-------------|-----------------|
| Sales | | | | | | | |
| Purchases | | | | | | | |
| Collections | | | | | | | |
| Supplier Payments | | | | | | | |
| Fuel | | | | | | | |
| Payroll | | | | | | | |
| Inventory | | | | | | | |
| Adjustments | | | | | | | |
| Depreciation | | | | | | | |
| Loans | | | | | | | |
| Taxes | | | | | | | |
| Journal Entries | | | | | | | |

---

## PART 6 — SOURCE DOCUMENTS

| Document | Created By | Approved By | Received By | Format (Paper/Excel/PDF/Email) | Can Correct? |
|----------|-----------|------------|------------|-----------|---------|
| Purchase Request | | | | | |
| Purchase Order | | | | | |
| Receiving Report | | | | | |
| Sales Invoice | | | | | |
| Official Receipt | | | | | |
| Delivery Receipt | | | | | |
| Disbursement Voucher | | | | | |
| Journal Voucher | | | | | |
| Payroll | | | | | |
| Fuel Receipt | | | | | |
| Collection Receipt | | | | | |
| Bank Deposit Slip | | | | | |
| Inventory Count Sheet | | | | | |

---

## PART 7 — JOURNAL ENTRIES

### Types
| Type | Auto/Manual/Recurring/Adjusting/Closing |
|------|----------------------------------------|
| Sales | |
| Purchases | |
| Collections | |
| Payments | |
| Payroll | |
| Depreciation | |
| Inventory | |
| Accruals | |
| Prepaids | |
| Loan | |
| Tax | |

### Error Causes
<!-- What causes errors in journal entries? -->

---

## PART 8 — TRIAL BALANCE

<!-- How produced? How often? What if Dr ≠ Cr? Who validates? -->

---

## PART 9 — MONTH-END CLOSING

| Aspect | Answer |
|--------|--------|
| First activity | |
| Last activity | |
| Most difficult | |
| Most time consuming | |
| Most error-prone | |
| Biggest bottleneck | |

---

## PART 10 — APPROVALS

| Item | Who Approves? |
|------|--------------|
| Purchases | |
| Payments | |
| Journal Entries | |
| Adjustments | |
| Asset Purchases | |
| Write-offs | |
| Inventory Adjustments | |

---

## PART 11 — INTEGRATION REQUIREMENTS

| System | Accounting Entries Generated |
|--------|---------------------------|
| Inventory | |
| Fleet | |
| Fuel | |
| Payroll | |
| Procurement | |
| Sales | |
| Maintenance | |
| Assets | |

---

## PART 12 — PAIN POINTS

### Top 5 Automations (if nothing changed)
1.
2.
3.
4.
5.

### What takes the longest?

### What causes mistakes?

### Which reports are manually prepared?

### Most requested reports by Management

---

## PART 13 — ARCHITECTURAL DECISIONS FROM WORKSHOP

### Confirmed
<!-- Based on discussion, what decisions are confirmed? -->

### Open Questions
<!-- What still needs clarification? -->

### Risks / Concerns
<!-- What did the team express concern about? -->

---

## NEXT STEPS

- [ ] Save meeting recording to `workshop-outputs/` folder
- [ ] Answer/open questions above
- [ ] Systems architect to refine Django models based on answers
- [ ] Create project scaffold (Django + PostgreSQL)
- [ ] COA Excel import script
- [ ] Phase 1: Foundation (COA, JE, GL, Trial Balance)
- [ ] Posting rules engine implementation

---

*Fill this document based on the workshop recording and discussion, then pass back to the systems architect for model refinement.*
