# Business Event Catalog

> Every business event that triggers accounting treatment.
> Format: `domain.action.state`
> Up to date as of: 2026-07-27 (AP shadow + Inventory interview)

---

## 1. SALES & RECEIVABLES (18 events)

| # | Event | Trigger | Source | Data Required | Posting Rule | Approval |
|---|-------|---------|--------|--------------|-------------|----------|
| 1 | `sales.order.created` | Customer PO received | Sales dept | Customer, items, amount, segment | — | — |
| 2 | `sales.order.approved` | Credit check passed | Sales mgr | Order ID, approved by | — | — |
| 3 | `sales.invoice.created` | Order fulfilled | Sales/Alywin | Customer, items, prices, VAT | — | — |
| 4 | `sales.invoice.posted` | Invoice approved | Alywin | Invoice total, disc, VAT, segment | Dr AR | Cr Revenue | Alywin |
| 5 | `sales.credit_note.created` | Return/adjustment | Alywin | Original invoice, amount, reason | Dr Sales Returns | Cr AR | Alywin |
| 6 | `sales.credit_note.posted` | Credit approved | Alywin | Credit note ID | Reverse revenue | Alywin |
| 7 | `cash.collection.received` | Client pays | Mich | Customer, amount, payment method, bank | Dr Cash | Cr AR | — |
| 8 | `cash.collection.deposited` | Cash deposited to bank | Mich | Bank acct, amount, deposit slip | — | — |
| 9 | `cash.ar_issued` | Acknowledgment Receipt issued | Mich | AR# (YYYY-SEQ), customer, amount, segment | Dr Cash | Cr Unearned Revenue | — |
| 10 | `sales.customer_deposit.received` | Advance payment | Mich | Customer, amount, segment | Dr Cash | Cr Unearned Income | — |
| 11 | `sales.customer_deposit.applied` | Applied to invoice | Mich | Deposit ref, invoice ref | Dr Unearned | Cr AR | — |
| 12 | `sales.consignment.setup` | SOA for consignment | Mich | Items on consignment, client | Dr Cash + AR | Cr Sales + Inventory | — |
| 13 | `sales.consignment.settled` | Consignee pays | Mich | Consignment ref, amount | Dr Cash | Cr AR | — |
| 14 | `sales.installment.created` | Installment sale | Mich | Customer, DP, installment terms | Dr Cash + AR | Cr Inventory + Gain | — |
| 15 | `sales.installment.payment` | Installment received | Mich | Payment amount, invoice ref | Dr Cash | Cr AR + Gain reversal | — |
| 16 | `sales.job_order.prepaid` | Prepayment for services | Mich | Customer, amount, segment | Dr Cash | Cr Unearned Income | — |
| 17 | `sales.job_order.rendered` | Service completed | OPS dept | Job order ref, amount | Dr Unearned | Cr Job Orders | — |
| 18 | `sales.job_order.direct` | Payment after service | Mich | Customer, amount | Dr Cash | Cr Job Orders | — |

---

## 2. PROCUREMENT & PAYABLES (22 events)

| # | Event | Trigger | Source | Data Required | Posting Rule | Approval |
|---|-------|---------|--------|--------------|-------------|----------|
| 19 | `procurement.pr.created` | Department needs items | Any dept | Items, estimated cost, account, segment | — | Dept head |
| 20 | `procurement.pr.approved` | PR approved | Dept head | PR ref | — | — |
| 21 | `procurement.po.created` | Supplier selected | Procurement | Supplier, items, prices, terms | — | — |
| 22 | `procurement.po.approved` | PO approved | CNR | PO ref | — | CNR |
| 23 | `procurement.goods.received` | Items delivered / inspected | Adrian/Warehouse | PO ref, qty received, RR number | If inventoriable: Dr Inventory | Cr Advances to Supplier | — |
| 24 | `procurement.supplier_invoice.received` | Bill from supplier | Che | Invoice ref, amount, VAT, PO ref | Dr Expense/Inventory | Cr AP | — |
| 25 | `procurement.rfp.created` | Request for Payment prepared | Che | Payee, amount, purpose, COA account, segment, supporting docs | Dr Expense/Inventory/Asset | Cr Advances to Employees (P20,000) + Cr AP (balance) | — |
| 26 | `procurement.rfp.checked` | RFP reviewed by dept head | Alywin | RFP ref, verification of docs & account | — | Alywin |
| 27 | `procurement.rfp.acctg_approved` | RFP approved by Accounting Manager | Acctg Mgr | RFP ref, JE correctness check | — | Acctg Mgr |
| 28 | `procurement.rfp.fin_approved` | RFP approved by Finance Manager | Finance Mgr | RFP ref, cash flow check | — | Finance Mgr |
| 29 | `procurement.rfp.cancelled` | RFP cancelled/voided | Che | RFP ref, reason | Reverse any provisional entry | — |
| 30 | `procurement.conso.created` | CONSO batch created from approved RFPs | Che | Batch of RFP refs, total amount | — | — |
| 31 | `procurement.conso.reviewed` | Accounting Head reviews CONSO batch | Acctg Head | CONSO ref, batch summary | Batch JE posted: Dr all expenses | Cr all AP accounts | Acctg Head |
| 32 | `procurement.check_voucher.created` | CV prepared for payment | Che | Payee, amount, bank acct, RFP ref | — | — |
| 33 | `procurement.check_voucher.signed` | CV signed / check printed | CNR | CV ref, authorized signatory | — | CNR |
| 34 | `procurement.check_voucher.released` | Check released to payee | Quibs | CV ref, releasing officer | — | — |
| 35 | `procurement.payment.cleared` | Check cleared bank | Quibs | Bank statement ref, cleared amount | Dr AP | Cr Cash | — |
| 36 | `procurement.advance.to_supplier` | Prepayment to supplier | Che | Supplier, amount | Dr Advances to Supplier | Cr Cash | Alywin |
| 37 | `procurement.advance.liquidated` | Goods received against advance | Adrian/Warehouse | Advance ref, RR ref | Dr Inventory | Cr Advances to Supplier | — |
| 38 | `procurement.advance_to_employee.created` | Employee advance via RFP | Che | Employee, amount (default P20,000), purpose | Dr Advances to Employee | Cr AP | — |
| 39 | `procurement.advance_to_employee.liquidated` | Employee submits liquidation | Employee | Receipts, actual expenses | Dr [Actual Expense] | Cr Advances to Employee | — |
| 40 | `procurement.contractor.billing` | Contractor invoices (Bulilit model) | Che | Client payment, contractor amount, markup | Dr Cash | Cr Payable to Contractor + Other Income | — |

---

## 3. FUEL & FLEET (12 events)

| # | Event | Trigger | Source | Data Required | Posting Rule | Approval |
|---|-------|---------|--------|--------------|-------------|----------|
| 41 | `fuel.order.to_depot` | Fuel order placed | Clyde/ops | Supplier (depot), amount | Dr Advances to Suppliers | Cr Cash | CNR |
| 42 | `fuel.pickup.paid` | Fuel loaded (prepaid) | Dispatcher | Liters, cost, depot | Dr Fuel Inventory | Cr Advances to Suppliers | — |
| 43 | `fuel.pickup.credit` | Fuel loaded (on account) | Dispatcher | Liters, cost, depot | Dr Fuel Inventory | Cr AP Current | — |
| 44 | `fuel.client_payment.received` | Client pays for fuel (before delivery) | Mich | Client, amount, segment | Dr Cash | Cr Unearned Income | — |
| 45 | `fuel.client_payment.with_balance` | Payment with previous balance settlement | Mich | Client, payment, old balance | Dr Cash + Dr Unearned + Dr AR | Cr Unearned + Cr AR | — |
| 46 | `fuel.transfer.to_substation` | Fuel moved to substation | Dispatcher | Location (Dohinob/San Pedro/Office), liters | Dr Fuel Inventory - Location | Cr Fuel Inventory | — |
| 47 | `fuel.tanker.consumption` | Fuel used by tankers | Fleet | Liters, vehicle | Dr COGS-Gasoline Expenses | Cr Fuel Inventory | — |
| 48 | `fuel.delivery.completed.paid` | Fuel delivered to client (prepaid) | Driver | Delivery receipt, liters | Dr COGS-Fuel Purchase + Dr Unearned Income | Cr Fuel Inventory + Cr Sales | — |
| 49 | `fuel.delivery.completed.unpaid` | Fuel delivered (on credit) | Driver | Delivery receipt, client, amount | Dr AR-Fuel Clients + Dr COGS-Fuel Purchase | Cr Sales + Cr Fuel Inventory | — |
| 50 | `fleet.trip.started` | Trip begins | Dispatcher | Vehicle, driver, origin, destination | — | — |
| 51 | `fleet.trip.completed` | Trip ends, costs known | Driver | Trip wages, toll fees, other expenses | Dr COGS-Trip Wages + COGS-Toll + COGS-Other | Cr Accrued/Cash | — |
| 52 | `fleet.maintenance.done` | Vehicle repaired/maintained | Fleet | Vehicle, service provider, cost, type | Dr COGS-Repairs (trip) / Dr OpEx-Repairs (non-trip) | Cr AP/Cash | — |

---

## 4. INVENTORY (10 events)

| # | Event | Trigger | Source | Data Required | Posting Rule | Approval |
|---|-------|---------|--------|--------------|-------------|----------|
| 53 | `inventory.stock.received` | Items received into warehouse | Adrian/Warehouse | Product, qty, warehouse, PO ref | Dr Inventory | Cr Advances/AP | — |
| 54 | `inventory.stock.issued` | Items withdrawn from warehouse | Adrian/Warehouse | Product, qty, cost center/account | Dr COGS/Expense | Cr Inventory | — |
| 55 | `inventory.transfer.completed` | Stock moved between warehouses | Adrian/Warehouse | Product, qty, from, to | Dr Inventory - To | Cr Inventory - From | — |
| 56 | `inventory.physical_count.done` | Count completed | Adrian | Count sheet, system vs actual | — | Cherry, James |
| 57 | `inventory.physical_count.adjusted` | Variance adjusted | Alywin | Variance amount, account | Dr Loss/Expense (if shortage) | Cr Inventory | Cherry → James → Alywin |
| 58 | `inventory.write_off` | Obsolete/damaged written off | Management | Items, value, reason | Dr Write-off Expense | Cr Inventory | Management |
| 59 | `inventory.revaluation` | Cost changed (FIFO/MA) | Alywin | New unit cost, adjustment | Dr/ Cr Inventory | Cr/ Dr COGS | Alywin |
| 60 | `inventory.consignment.shipped` | Goods sent on consignment | Adrian | Product, qty, consignee | Dr Inventory-Consignment | Cr Inventory | — |
| 61 | `inventory.consignment.sold` | Consignee sold goods | Mich | SOA from consignee | Dr COGS | Cr Inventory + Dr AR | Cr Sales | — |
| 62 | `inventory.je.exported` | JE exported from inventory system to CONSO | Staff | Inventory transactions for period | — (separate Django system → manual or API) | — |

---

## 5. PAYROLL (8 events)

| # | Event | Trigger | Source | Data Required | Posting Rule | Approval |
|---|-------|---------|--------|--------------|-------------|----------|
| 63 | `payroll.dtr.submitted` | Time records from departments | HR | Employee, hours, OT | — | — |
| 64 | `payroll.run.calculated` | Payroll computed | Alywin | Gross pay, deductions, net | — | — |
| 65 | `payroll.run.approved` | Payroll approved | Sir Boy | Payroll summary | — | Sir Boy |
| 66 | `payroll.run.posted` | Payroll JE created | Alywin | Gross pay breakdown, deductions, employer share | Dr Salaries + COGS-Labor + ER Shares | Cr Accrued + Govt Payables + W/H Tax | Alywin |
| 67 | `payroll.disbursement.created` | RFP for salary payment | Alywin | Net pay total | Dr Accrued Salaries | Cr AP-Others | — |
| 68 | `payroll.disbursement.uploaded` | Salary file to bank | Quibs | Bank file, net amounts | — | CNR |
| 69 | `payroll.govt_remittance.rfp` | RFP for govt contributions | Alywin | SSS/PHIC/HDMF summary | Dr All Govt Payables | Cr AP-Others | — |
| 70 | `payroll.govt_remittance.paid` | Govt remittances cleared | Quibs | Bank statement, remittance advices | Dr AP-Others | Cr Cash | — |

---

## 6. FIXED ASSETS (9 events)

| # | Event | Trigger | Source | Data Required | Posting Rule | Approval |
|---|-------|---------|--------|--------------|-------------|----------|
| 71 | `asset.acquisition.ordered` | Purchase of asset ordered | Dept head | Asset type, cost, supplier | — | CNR |
| 72 | `asset.acquisition.received` | Asset delivered | Adrian | Asset details, cost, location | Dr Asset Account | Cr AP/Cash | — |
| 73 | `asset.acquisition.financed` | Asset bought via loan | Alywin | Loan terms, down payment, fees | Dr Asset + Dr Fees | Cr Cash + Cr Loans Payable | CNR |
| 74 | `asset.insurance.paid` | Insurance for asset | Alywin | Premium, period | Dr Prepaid Insurance | Cr Cash | — |
| 75 | `asset.insurance.amortized` | Monthly insurance expense | Alywin | Monthly portion | Dr Insurance Expense | Cr Prepaid Insurance | — |
| 76 | `asset.depreciation.calculated` | Monthly depreciation | Alywin | Asset, period, amount | Dr Depreciation Expense/COGS | Cr Accum Depreciation | — |
| 77 | `asset.impairment.recognized` | Asset value impaired | Alywin | Impairment amount | Dr Impairment Loss | Cr Accum Depreciation | Management |
| 78 | `asset.disposal.executed` | Asset sold/scrapped | Alywin | Proceeds, accum dep, gain/loss | Dr Cash + Dr Accum Dep | Cr Asset + Cr Gain (or Dr Loss) | CNR |
| 79 | `asset.transfer` | Asset moved between segments | Alywin | Asset, from segment, to segment | Dr Asset-To | Cr Asset-From | Alywin |

---

## 7. CASH & BANK (13 events)

| # | Event | Trigger | Source | Data Required | Posting Rule | Approval |
|---|-------|---------|--------|--------------|-------------|----------|
| 80 | `cash.bank_deposit.made` | Cash deposited | Mich | Bank acct, amount, deposit slip | Dr Cash-Bank | Cr Cash-Collection | — |
| 81 | `cash.pcf.created` | Petty cash fund established | Quibs | Amount, custodian (Quibong) | Dr Petty Cash Fund | Cr Cash in Bank | Alywin |
| 82 | `cash.pcf.voucher.created` | PCV for expense < P2,500 | Requestor | Amount, purpose, payee | — | Quibong |
| 83 | `cash.pcf.disbursed` | Cash given from PCF | Quibong | PCV ref, amount | Dr Expense (deferred to replenishment) | Cr Petty Cash | — |
| 84 | `cash.pcf.replenished` | PCF replenishment (trigger: % remaining) | Quibs | Batch of PCVs, total, expense breakdown | Dr Various Expenses | Cr Cash in Bank | Alywin |
| 85 | `cash.bank_reconciliation.prepared` | Monthly bank recon | Quibs | Bank statement, book balance, adjustments | — | — |
| 86 | `cash.bank_reconciliation.adjusted` | Book adjustments from recon | Quibs | Adjustments found | Dr/Cr appropriate account | Dr/Cr Cash | Alywin |
| 87 | `cash.cycle.settled` | Weekly cash cycle closed | Quibs | Collections, depot payments, mark-up, short/excess | Dr Bank Accounts (collections) | Cr Unearned Revenue + Cr AP (depot) + Cr Mark-up Income | — |
| 88 | `cash.short.identified` | Cash shortage found | Quibs | Short amount, cycle ref | Dr Cash Short Expense | Cr Cash | Alywin |
| 89 | `cash.excess.identified` | Cash overage found | Quibs | Excess amount, cycle ref | Dr Cash | Cr Other Income | — |
| 90 | `cash.collectibles.settled` | COLLECTIBLES reconciliation (Distribution vs Finance) | Quibs | Gross mark-up, net mark-up, settlement amount | Dr AR-Distribution | Cr Income (gross) + Cr AR-Finance (net) | — |
| 91 | `cash.interaccount_transfer` | CASH SHORT borrowing between accounts | Quibs | From account, to account, amount | Dr Cash-To | Cr Cash-From | Alywin |
| 92 | `cash.check_released` | Check released to payee | Quibs | CV ref, payee, amount, bank | Dr AP | Cr Cash in Bank | — |

---

## 8. LOANS & FINANCING (6 events)

| # | Event | Trigger | Source | Data Required | Posting Rule | Approval |
|---|-------|---------|--------|--------------|-------------|----------|
| 93 | `loan.received` | Loan proceeds received | Alywin | Lender, amount, terms, interest | Dr Cash + Dr Fees | Cr Loans Payable + Cr Interest Payable | CNR |
| 94 | `loan.interest.accrued` | Monthly interest accrual | Alywin | Interest amount, period | Dr Interest Expense | Cr Interest Payable | — |
| 95 | `loan.payment.made` | Monthly amortization | Quibs | Principal, interest, total | Dr Loans Payable + Dr Interest Expense | Cr Cash | — |
| 96 | `loan.officer.received` | Loan from officer | Alywin | Officer, amount | Dr Cash + Dr Interest Expense | Cr Loans Payable-Officer + Cr Interest Payable | CNR |
| 97 | `loan.officer.paid` | Officer loan repaid | Quibs | Loan ref, amount | Dr Loans Payable-Officer + Dr Interest Payable | Cr Cash | — |
| 98 | `loan.chattel.paid` | Chattel mortgage fees | Alywin | Fees amount | Dr Notarial/DST Fees | Cr Cash/AP | — |

---

## 9. TAX (6 events)

| # | Event | Trigger | Source | Data Required | Posting Rule | Approval |
|---|-------|---------|--------|--------------|-------------|----------|
| 99 | `tax.si.extracted` | Sales Invoices extracted for VAT | Alywin | SI list, output VAT, input VAT | — | — |
| 100 | `tax.vat.filed` | VAT return filed | Alywin | Output VAT, input VAT, payable | Dr Output VAT Payable | Cr Input VAT + Cr Cash (net) | — |
| 101 | `tax.wht.compensation.remitted` | WHT on compensation paid | Quibs | Amount | Dr WHT Payable | Cr Cash | — |
| 102 | `tax.wht.expanded.remitted` | EWT remitted | Quibs | Amount | Dr EWT Payable | Cr Cash | — |
| 103 | `tax.wht.final.remitted` | Final WHT remitted | Quibs | Amount | Dr Final WHT Payable | Cr Cash | — |
| 104 | `tax.income.provision` | Income tax provision | Alywin | Taxable income, rate | Dr Income Tax Expense | Cr Income Tax Payable | — |

---

## 10. MONTH-END & ADJUSTMENTS (9 events)

| # | Event | Trigger | Source | Data Required | Posting Rule | Approval |
|---|-------|---------|--------|--------------|-------------|----------|
| 105 | `period.prepaid.amortized` | Prepaid expenses amortized | Alywin | Prepaid schedules | Dr Expense | Cr Prepaid | — |
| 106 | `period.accrual.created` | Accrual entry | Alywin | Expense/income to recognize | Dr Expense | Cr Accrued Liability | Alywin |
| 107 | `period.depreciation.booked` | All depreciation booked | Alywin | All assets, current period | Dr Depreciation Expense/COGS | Cr Accum Depreciation | — |
| 108 | `period.deferred.revenue.recognized` | Unearned revenue earned | Alywin | Unearned schedules | Dr Unearned Income | Cr Revenue | — |
| 109 | `period.closing.revenue` | Close revenue accounts | Alywin | Revenue balances | Dr All Revenue | Cr Capital | Alywin |
| 110 | `period.closing.expense` | Close expense accounts | Alywin | Expense balances | Dr Capital | Cr All Expenses | Alywin |
| 111 | `period.closing.drawing` | Close drawings | Alywin | Drawing balance | Dr Capital | Cr Drawings | — |
| 112 | `period.appropriation.computed` | Net income appropriation | Alywin | Net income, % for repairs (10%), tithing (10%), expansion (5%) | Dr Capital | Cr Appropriation Reserves | — |
| 113 | `journal.adjustment.manual` | Manual adjusting entry | Alywin | Accounts, amounts, reason | Configurable Dr/Cr | Configurable Dr/Cr | Alywin |

---

## SUMMARY

| Domain | Events |
|--------|--------|
| Sales & Receivables | 18 |
| Procurement & Payables | 22 |
| Fuel & Fleet | 12 |
| Inventory | 10 |
| Payroll | 8 |
| Fixed Assets | 9 |
| Cash & Bank | 13 |
| Loans & Financing | 6 |
| Tax | 6 |
| Month-End & Adjustments | 9 |
| **Total** | **113** |
