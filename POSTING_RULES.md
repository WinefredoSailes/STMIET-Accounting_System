# Posting Rules Specification

> Maps every business event to Journal Entry lines. This is the core of the accounting engine.

## Conventions

| Symbol | Meaning |
|--------|---------|
| Dr | Debit |
| Cr | Credit |
| [SEG] | Segment dimension (DHPP/DMIE/OPS) |
| [COA] | Account code |
| {formula} | Amount derivation |

All amounts are in PHP. Every entry must balance: total Dr = total Cr.

---

## 1. SALES TRANSACTIONS

### 1.1 Sales Invoice (Fuel Hauling / Equipment / OPS)

**Event**: `sales.invoice.posted`

| Line | Account | Segment | Debit | Credit |
|------|---------|---------|-------|--------|
| 1 | 11000-11999 Accounts Receivable | [SEG] | {total_net} | |
| 2 | 40000-41099 Trade Income (Sales) | [SEG] | | {sales_amount} |

**Accounts by segment**:
- DHPP: 40000 Sales - Fuel Hauling / 40500 Sales Discount - Hauling
- DMIE: 41003 Sales - DMIE / 41503 Sales Discount - DMIE
- OPS: 42006 Sales - OPS / 42506 Sales Discount - OPS

**Trigger**: SalesInvoice status changed to POSTED.

### 1.2 Sales Discount

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 40500/41503/42506 Sales Discount | {discount} | |
| 2 | 11000-11999 Accounts Receivable | | {discount} |

**Trigger**: Applied at invoice posting or as separate credit memo.

### 1.3 Collection Receipt

**Event**: `cash.receipt.collected`

| Line | Account | Segment | Debit | Credit |
|------|---------|---------|-------|--------|
| 1 | 10013-10040 Cash in Bank | [SEG] | {amount} | |
| 2 | 11000-11999 Accounts Receivable | [SEG] | | {amount} |

**Trigger**: CollectionReceipt created.

### 1.4 Other Income / Miscellaneous Income

**Event**: `sales.other_income.recorded`

**Example**: Gain on Freebies, Job Orders, Service Income, Miscellaneous Income, Interest Income, Income from Disposal

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 11000-11999 AR / 100xx Cash | {amount} | |
| 2 | 430xx Other Income | | {amount} |

**Accounts**: 43003-43106 (Gain on Freebies, Job Orders, Service Income, Misc, Interest, Disposal)

---

## 2. COST OF SALES

### 2.1 Direct COGS (Fuel Hauling — DHPP)

**Event**: `cogs.recorded` (at sale/inventory issue)

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 50000 COGS - Fuel Purchase | {cost} | |
| 2 | 13000 Fuel Inventory | | {cost} |

### 2.2 COGS Line Items (all segments)

**Cost elements** (accounts 50000-52046):
- Fuel Purchase / Gasoline
- Trip Wages
- Operational Staff
- Labor Cost
- Repairs and Maintenance
- Subscription Fees
- Storage and Handling
- Toll Fees
- Other Direct Fees
- Depreciation of Vehicles
- Calibration, Inverter, Shipping, Transfer Pump (DMIE)

**Rule**: When a trip is completed or inventory is issued to COGS:

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 50xxx COGS - {element} | {cost} | |
| 2 | 130xx Inventory / 2xxx Payable / 1xxx Cash | | {cost} |

**Trigger**: Trip completion, inventory issue, or supplier invoice.

### 2.3 COGS — Labor & Operational Staff

For payroll allocated to COGS:

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 50040/50050/51053/51063/52026/52036 COGS - Staff/Labor | {amount} | |
| 2 | 22020-22026 Accrued Salaries | | {amount} |

### 2.4 COGS — Depreciation of Vehicles

**Event**: `asset.depreciation.booked`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 50110/51173 COGS - Depreciation | {amount} | |
| 2 | 18513/17xxx Accumulated Depreciation | | {amount} |

---

## 3. OPERATING EXPENSES

### 3.1 General Operating Expenses

**Event**: `expense.incurred`

**Accounts**: 61000-64900 (Accommodation, Bad Debts, Bank Charges, Depreciation, Govt Shares, Impairment, Insurance, Interest, Professional Fees, Loan Related, Office Supplies, IT/System, Other Fees, Salaries & Benefits, Taxes, Travel, Utilities, Withholding Tax, Representation, Rent)

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 61xxx-64xxx Operating Expense | {amount} | |
| 2 | 2xxx Payable / 1xxx Cash | | {amount} |

### 3.2 Salaries & Benefits

**Event**: `payroll.run.posted`

**Accounts by employee level**: 634xx (13th/14th Month), 63420-63426 (Commission), 63430-63436 (Load Allowance), 63440-63446 (Meals), 63450-63456 (Other Allowances), 63460-63466 (Bonuses), 63470-63476 (OT), 63480-63496 (By Level: Dept Head, Executive, Supervisor), 63500-63506 (R&F), 63520-63526 (Welfare Fund)

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 634xx-635xx Salaries & Benefits | {gross_pay} | |
| 2 | 22020-22026 Accrued Salaries | | {net_pay} |
| 3 | 23010-23066 Govt Payables (SSS/PHIC/HDMF) | | {ee_contributions} |
| 4 | 64100-64126 Withholding Tax Payable | | {withholding_tax} |

**Employer contributions**:

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 61800-61806 Govt ER Shares | {er_total} | |
| 2 | 23040-23066 ER Govt Payables | | {er_contributions} |

### 3.3 Depreciation Expense (Operating)

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 61600-61606 Depreciation Expense | {amount} | |
| 2 | 17xxx Accumulated Depreciation | | {amount} |

### 3.4 Bad Debts Expense

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 61200-61206 Bad Debts Expense | {amount} | |
| 2 | 110xx Accounts Receivable / Allowance | | {amount} |

---

## 4. NON-OPERATING EXPENSES

### 4.1 Miscellaneous & Other G&A

**Accounts**: 65000-65006 (Miscellaneous), 66000-66006 (Other G&A)

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 650xx/660xx Non-Operating Expense | {amount} | |
| 2 | 2xxx Payable / 1xxx Cash | | {amount} |

---

## 5. INVENTORY TRANSACTIONS

### 5.1 Goods Receipt (Purchase)

**Event**: `inventory.goods_receipt`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 130xx Inventory Account | {quantity × unit_cost} | |
| 2 | 20000-20006 Accounts Payable | | {total} |

**Segment**: By product segment.
**Inventory accounts**: 13000 (Fuel), 13010-13020 (Fuel by location), 13030 (Spare Parts), 13040 (Lubricants), 13053-13116 (Other inventory)

### 5.2 Inventory Write-off / Adjustment

**Event**: `inventory.adjusted`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 63200-63246 Other Fees/Charges (if loss) | {variance} | |
| 2 | 130xx Inventory | | {variance} |

If gain (positive variance), reverse.

### 5.3 Physical Count Adjustment

Same as 5.2, with reference to PhysicalCount document.

---

## 6. FLEET TRANSACTIONS

### 6.1 Trip Completion

**Event**: `fleet.trip.completed`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 50030 COGS - Trip Wages | {trip_wages} | |
| 2 | 50090/51143 COGS - Toll Fees | {toll_fees} | |
| 3 | 50100/51083 COGS - Other Direct Fees | {other_exp} | |
| 4 | 220xx Accrued Expenses / 1xxx Cash | | {total} |

### 6.2 Vehicle Maintenance (COGS)

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 50060/51113/52016 COGS - Repairs & Maintenance | {cost} | |
| 2 | 200xx AP / 1xxx Cash | | {cost} |

### 6.3 Vehicle Maintenance (Operating Expense)

For non-trip vehicle expenses:

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 63240-63246 Other Repairs & Maintenance | {cost} | |
| 2 | 200xx AP / 1xxx Cash | | {cost} |

### 6.4 Fuel Consumption (for Fleet Operations)

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 63800-63806 Fuel & Oil (Travel Expense) | {cost} | |
| 2 | 13000-13020 Fuel Inventory | | {cost} |

---

## 7. PAYABLES & DISBURSEMENTS

### 7.1 Supplier Invoice Booking

**Event**: `payables.invoice.received`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 130xx Inventory / 6xxx Expense / 50xxx COGS | {amount} | |
| 2 | 20000-20006 Accounts Payable | | {amount} |

### 7.2 RFP Journal Entry (Request for Payment)

**Event**: `procurement.rfp.created`

The RFP (ACCTG-FOR-012) carries its own JE. Every RFP includes a standing credit to Advances to Employees.

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 6xxx Expense / 130xx Inventory / 17xxx Asset | {total_amount} | |
| 2 | 12070 Advances to Employees - Current | | {20,000} |
| 3 | 20000-20006 Accounts Payable - Vendor | | {total_amount - 20,000} |

**Note**: Canonical balancing formula (`TOTAL = 20,000 + (TOTAL − 20,000)`) per REVIEW-ISSUES-RESOLUTIONS.md #5. The Advances to Employees credit (default P20,000) is a clearing account — see ADR-021. Account basis moved from 12050 → 12070 per live COA (RESOLUTION #4). The actual amounts may vary.

### 7.3 RFP Approval → CONSO Posting

**Event**: `procurement.conso.reviewed`

When CONSO batch is approved by Accounting Head, all RFPs in the batch post their JEs:

```
For each RFP in CONSO:
    Dr: [Expense/Inventory/Asset]        {amount}
        Cr: Advances to Employees        {20,000}
        Cr: AP - Vendor                  {balance}
```

### 7.4 Payment / Disbursement Voucher

**Event**: `payables.payment.made`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 20000-20006 Accounts Payable | {amount} | |
| 2 | 100xx Cash in Bank | | {amount} |

If with withholding tax:

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 20000-20006 Accounts Payable | {gross} | |
| 2 | 100xx Cash in Bank | | {net} |
| 3 | 64110-64116 Withholding Tax Payable | | {tax} |

### 7.5 Advances to Employees (Clearing Account)

**Event**: `procurement.advance_to_employee.liquidated`

When employee liquidates the advance with receipts:

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 12050 Advances to Employees - Current | {20,000} | |
| 2 | 6xxx Appropriate Expense Account | | {actual_amount} |
| 3 OR | 100xx Cash (if excess returned) | | {refund} |
| 3 OR | 12050 Advances (if additional advance needed) | {top_up} | |

### 7.6 Accrued Expenses Booking

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 6xxx Appropriate Expense | {amount} | |
| 2 | 22000-22026 Accrued Expenses | | {amount} |

---

## 8. CASH & BANK

### 8.1 Petty Cash Fund Replenishment

**Event**: `cash.pcf.replenished`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 6xxx Various Expense Accounts | {total_by_account} | |
| 2 | 100xx Cash in Bank | | {replenishment_amount} |

### 8.2 Bank Reconciliation Adjustments

**Event**: `cash.bank_reconciliation.posted`

For book adjustments discovered during reconciliation:

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 6xxx Appropriate Expense/Income | {adj} | |
| 2 | 100xx Cash in Bank | | {adj} |

### 8.3 Cash Short/Excess

**Event**: `cash.cycle.settled`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 63210-63216 Other Operating Expenses (if short) | {short} | |
| 2 | 100xx Cash in Bank | | {short} |

If excess, reverse.

---

## 9. FIXED ASSETS

### 9.1 Asset Acquisition

**Event**: `asset.acquired`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 17xxx-19xxx Asset Account | {cost} | |
| 2 | 200xx AP / 100xx Cash / 270xx Loans Payable | | {cost} |

### 9.2 Monthly Depreciation

**Event**: `asset.depreciation.booked`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 50110/51173/616xx Depreciation Expense/COGS | {amount} | |
| 2 | 17xxx Accumulated Depreciation | | {amount} |

**Category-to-account mapping**:
| Asset Category | Exp/COGS Account | Accum Dep Account |
|---------------|-----------------|-------------------|
| Tanker/Vehicles (DHPP) | 50110 / 61600 | 17010-18650 |
| Vehicles (DMIE) | 51173 / 61603 | 18503-18513 |
| Building | 61600-61606 | 19000-19750 |
| Furniture | 61600-61606 | 19800 |
| Office Equipment | 61600-61606 | 19900-19966 |

### 9.3 Asset Disposal

**Event**: `asset.disposed`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 100xx Cash (proceeds) | {proceeds} | |
| 2 | 17xxx Accumulated Depreciation | {accum_dep} | |
| 3 | 17xxx Asset Account | | {cost} |
| 4 | 43070-43096 Income from Disposal (gain) | | {gain} |
| Or: 4 | 6xxx Other Expense (loss) | {loss} | |

---

## 10. GOVERNMENT CONTRIBUTIONS & TAXES

### 10.1 Monthly Government Remittance Payment

**Event**: `payroll.govt_remitted`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 23010-23066 Govt Payables | {total} | |
| 2 | 100xx Cash in Bank | | {total} |

### 10.2 Withholding Tax Remittance

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 64100-64126 Withholding Tax Payable | {total} | |
| 2 | 100xx Cash in Bank | | {total} |

### 10.3 Income Tax Provision

**Event**: `tax.income.provision`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 64600-64606 Income Tax Expense | {amount} | |
| 2 | 2xxx Income Tax Payable | | {amount} |

---

## 11. LOANS & FINANCING

### 11.1 Loan Proceeds Received

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 100xx Cash in Bank | {amount} | |
| 2 | 24010-24016 / 27010-27016 Loans Payable | | {amount} |

### 11.2 Loan Repayment

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 24010-24016 / 27010-27016 Loans Payable | {principal} | |
| 2 | 62400-62403 Interest Expense | {interest} | |
| 3 | 100xx Cash in Bank | | {total} |

### 11.3 Loan-Related Expenses

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 62800-62803 Loan-Related Expenses | {amount} | |
| 2 | 100xx Cash / 2xxx Payable | | {amount} |

---

## 12. PREPAID & DEFERRED

### 12.1 Prepaid Expense Booking

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 140xx Prepaid Expense | {amount} | |
| 2 | 100xx Cash | | {amount} |

### 12.2 Prepaid Expense Amortization

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 6xxx Appropriate Expense | {monthly_amort} | |
| 2 | 140xx Prepaid Expense | | {monthly_amort} |

### 12.3 Unearned Revenue (Advance from Customer)

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 100xx Cash | {amount} | |
| 2 | 21000-21016 Unearned Revenue | | {amount} |

### 12.4 Revenue Recognition from Unearned

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 21000-21016 Unearned Revenue | {amount} | |
| 2 | 4xxxx Revenue | | {amount} |

---

## 13. MONTH-END & YEAR-END

### 13.1 Closing of Revenue Accounts

**Event**: `period.closing.revenue`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 4xxxx Revenue Accounts | {balance} | |
| 2 | 30000-30006 E.Bagatua Capital | | {net_income} |

### 13.2 Closing of Expense Accounts

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 30000-30006 E.Bagatua Capital | {total_expenses} | |
| 2 | 5xxxx-6xxxx Expense/COGS Accounts | | {balance} |

### 13.3 Appropriation Entries

Based on Income Statement computation:

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 30000-30006 E.Bagatua Capital (appropriated) | {amount} | |
| 2 | 3xxxx Appropriation Reserves - Repairs & Maintenance | | {10%} |
| 3 | 3xxxx Appropriation Reserves - Tithing | | {10%} |

---

## 14. PAYROLL — DETAILED POSTING

### 14.1 Complete Payroll Journal Entry

**Event**: `payroll.run.posted`

**Gross-to-Net breakdown**:

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 63470-63476 OT Pay | {ot_total} | |
| 2 | 63480-63496 Salaries by Level | {salary_total} | |
| 3 | 63430-63436 Load Allowance | {load_total} | |
| 4 | 63440-63446 Meals Allowance | {meals_total} | |
| 5 | 63420-63426 Commission | {commission_total} | |
| 6 | 63450-63456 Other Allowances | {other_allow_total} | |
| 7 | 63460-63466 Bonuses | {bonus_total} | |
| 8 | 22020-22026 Accrued Salaries | | {net_pay_total} |
| 9 | 23010-23016 SSS Payable (EE) | | {sss_ee_total} |
| 10 | 23020-23026 PHIC Payable (EE) | | {phic_ee_total} |
| 11 | 23030-23036 HDMF Payable (EE) | | {hdmf_ee_total} |
| 12 | 64100-64106 Withholding Tax | | {tax_total} |

**Employer contributions** (separate JE):

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 61800-61806 Govt ER Shares | {er_total} | |
| 2 | 23040-23046 ER SSS Payable | | {sss_er_total} |
| 3 | 23050-23056 ER PHIC Payable | | {phic_er_total} |
| 4 | 23060-23066 ER HDMF Payable | | {hdmf_er_total} |

---

## 15. CASH FLOW CYCLE (WEEKLY)

The weekly cash flow cycle matching the COLLECTIBLES sheet:

### 15.1 Collections from Customers

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 100xx Cash in Bank | {collections} | |
| 2 | 110xx Accounts Receivable | | {collections} |

### 15.2 Payment to Depot (Fuel Supplier)

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 20000 Accounts Payable - Depot | {payment} | |
| 2 | 100xx Cash in Bank | | {payment} |

### 15.3 Gross Mark-up Recording

The difference between client collections and depot payments = gross mark-up.

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 100xx Cash in Bank (net) | {markup} | |
| 2 | 400xx Revenue (via accrual reversal) | | {markup} |

### 15.4 PCF Replenishment

**Trigger:** 85% of fund consumed (threshold-based, configurable per fund — ADR-027)

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 100xx Petty Cash Fund | {amount} | |
| 2 | 100xx Cash in Bank | | {amount} |

Then individual expense entries upon liquidation (see 8.1). Three funds exist: PCF-General (Leaslyn), PCF-Maintenance (Treasury), PCF-Technical (Alywin).

### 15.5 Inter-Account Fund Transfer

**Event**: `cash.interaccount_transfer` (ADR-030)

Transfers between the 11 cash columns (PNB, PSBC-S, PSBC-C, KB, 1VB, BDO, MBTC, RCBC, CHINA, E.TAN/STPC, PCF&COH). No P&L impact.

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 100xx Cash in Bank - [To] | {amount} | |
| 2 | 100xx Cash in Bank - [From] | | {amount} |

### 15.6 Cash Short / Excess (per cycle)

**Event**: `cash.short.identified` / `cash.excess.identified`

Variance = Deposits (passbook) − Collections recorded. Requires cause + approval (ADR-030).

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | 63210-63216 Other Operating Expenses (short) | {short} | |
| 2 | 100xx Cash in Bank | | {short} |

Excess reverses (Cr Other Income).

### 15.7 COLLECTIBLES Settlement

**Event**: `cash.collectibles.settled` (ADR-029)

The settlement document itself does NOT create a JE — the underlying events (collections → Dr Cash / Cr Unearned; depot payments → Dr AP / Cr Cash) are already posted. The settlement computes gross mark-up = client paid − depot paid and reconciles cashier records (passbooks + GCash + other credits) against the cycle totals. Variance rolls to CASH SHORT (15.6) or carry-forward.

---

## 16. SUMMARY: EVENT → POSTING RULE MATRIX

| Event | Posting Rule | Segment | Key Accounts |
|-------|-------------|---------|-------------|
| `sales.invoice.posted` | 1.1 | [SEG] | AR → Sales |
| `cash.receipt.collected` | 1.3 | [SEG] | Cash → AR |
| `cogs.recorded` | 2.1-2.4 | [SEG] | COGS → Inventory/Payable |
| `expense.incurred` | 3.1 | [SEG] | Expense → Payable/Cash |
| `payroll.run.posted` | 14.1 | [SEG] | Salaries → Accruals + Govt |
| `inventory.goods_receipt` | 5.1 | [SEG] | Inventory → AP |
| `inventory.adjusted` | 5.2 | [SEG] | Expense → Inventory |
| `fleet.trip.completed` | 6.1 | DHPP/DMIE | COGS → Accrued |
| `payables.invoice.received` | 7.1 | [SEG] | Expense/Inventory → AP |
| `payables.payment.made` | 7.2 | [SEG] | AP → Cash |
| `asset.acquired` | 9.1 | [SEG] | Asset → AP/Cash/Loan |
| `asset.depreciation.booked` | 9.2 | [SEG] | Depreciation → Accum Dep |
| `asset.disposed` | 9.3 | [SEG] | Cash+Accum Dep → Asset+Gain |
| `period.closing` | 13.1-13.3 | [SEG] | Rev/Exp → Capital |
| `cash.cycle.settled` | 15.1-15.4 | DHPP | Cash cycle reconciliation |

## 17. POSTING VALIDATION RULES

1. **Double-entry**: Every JournalEntry must have sum(debit) = sum(credit)
2. **Normal balance check**: Dr accounts must have Dr > 0 for increases, Cr accounts for decreases
3. **Segment consistency**: All lines in a JE must belong to same segment (except consolidating entries)
4. **Fiscal period**: Entry date must fall within an open fiscal period
5. **Approval**: JEs over {threshold} require supervisor approval before posting
6. **No back-posting**: Cannot post to a closed period
7. **Audit trail**: Once posted, JEs cannot be edited; corrections require reversal + new JE
