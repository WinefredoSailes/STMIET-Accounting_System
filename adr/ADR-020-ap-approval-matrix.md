# ADR-020: AP Approval Matrix

**Status:** Accepted  
**Date:** 2026-07-27  
**Deciders:** Architecture Team  

**References:**
- [ADR-008: Multi-Level Approval](./ADR-008-approval-hierarchy.md) — base approval framework
- [ADR-018: RFP Document Model](./ADR-018-rfp-document-model.md) — RFP carries 4 approval signatures

---

## Context

Every RFP template (ACCTG-FOR-012) contains four signature lines. AP shadow confirmed this is the standard approval chain for all payment requests. The full matrix varies by document type, source, and amount.

### RFP Signature Block (from actual form)

```
Prepared by:    ___________________   (Requestor/Che)
Date:           ___________________

Checked by:     ___________________   (Alywin - Dept Head/Checker)
Date:           ___________________

Approved by:    ___________________   (Accounting Manager)
Date:           ___________________

Approved by:    ___________________   (Finance Manager)
Date:           ___________________
```

### Observed RFP Types and Their Sources

| RFP Type | Requestor | Source |
|----------|-----------|--------|
| CNR Short Term Loan | CNR / Che | Salary advance for COO |
| Motorpool | Motorpool dept | Vehicle-related expenses |
| STPC Fuel | STPC station | Sister company fuel purchases |
| Shandong Fuel | Shandong (supplier) | Fuel delivery payment |
| ORIX | ORIX (leasing) | Equipment lease payments |
| PLDT | Admin | Telecom expenses |
| ZANECO | Admin | Electricity |
| Water District | Admin | Water utilities |
| Salaries (via CNR) | Che/Alywin | Payroll RFP |
| Bulilit Contractors | Operations | Contractor payments |
| Employee Reimbursements | Employee | Travel, supplies, etc. |
| Supplier Invoices | Che/Vendor | Standard vendor payments |

---

## Decision

Approval is enforced per document type with the following matrix:

### RFP Approval Matrix

| Step | Role | Person | Action |
|------|------|--------|--------|
| 1 | Requestor | Dept staff / Che | Prepare RFP with all supporting docs |
| 2 | Checker | Alywin | Verify: correct COA account, supporting docs complete, amounts match invoices |
| 3 | Approver 1 | Accounting Manager | Approve: JE correctness, budget availability |
| 4 | Approver 2 | Finance Manager | Final approve: cash flow check, release authorization |

**Rules:**
- All 4 signatures required before RFP moves to CONSO
- Step 2-4 can reject → returns to Step 1 with rejection reason
- Same person cannot hold two roles on the same RFP
- Alywin (Checker) is the Accounting Head — also handles JEs, adjustments, FA
- Accounting Manager and Finance Manager are superior roles (above Alywin)

### Amount Escalation

| Document Type | Threshold | Additional Approval |
|--------------|-----------|-------------------|
| RFP | > P100,000 (TBD) | CNR (COO) |
| Purchase Order | Any | CNR (COO) — confirmed from PO template with CNR signature |
| Check Voucher | > P100,000 (TBD) | CNR (COO) |
| Asset Purchase | Any | CNR (COO) |
| Write-off | Any | Management |
| Bank Recon Adjustment | Any | Alywin + CNR if material |

### Other Document Approval Chains

| Document | Chain |
|----------|-------|
| Purchase Order | Requestor → Alywin → CNR |
| Check Voucher | Che/Quibs → Alywin → Acctg Mgr → Finance Mgr → (CNR if > threshold) |
| Petty Cash Voucher | Requestor → Quibong (custodian) |
| Inventory Count | Adrian → Cherry → James → (Alywin if adjustment) |
| Journal Entry | Alywin → Acctg Mgr → (CNR if material) |
| Bank Reconciliation | Quibs → Alywin → (CNR if adjustment) |

---

## Consequences

### Positive
- Clear who approves what — no ambiguity
- Rejection workflow with reasons prevents repeated errors
- Amount thresholds prevent bypassing COO oversight on large payments

### Negative
- 4-level approval for every RFP can slow down processing for small amounts
- If Accounting Manager or Finance Manager is unavailable, payment is blocked

### Neutral
- Threshold amounts (P100,000+) are configurable parameters, not hardcoded
- CONSO batch approval by Accounting Head is a separate review step after individual approvals
