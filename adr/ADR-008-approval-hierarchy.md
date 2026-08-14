# ADR-008: Multi-Level Approval with Authority Escalation

**Status**: Accepted
**Date**: 2026-07-18
**Last Updated**: 2026-07-27
**Decision**: Document approval uses a configurable multi-level hierarchy based on document type and amount.

## Context
The workshop confirmed base approval levels. AP shadow and RFP Templates revealed the full approval matrix per document type:

### Full Approval Matrix

| Document Type | Creator | Checker | Approver 1 | Approver 2 | Final (if > threshold) |
|--------------|---------|---------|------------|------------|----------------------|
| **RFP** (AP) | Requestor dept | Alywin (Dept Head) | Accounting Manager | Finance Manager | CNR (COO) |
| **RFP (STPC Fuel)** | Requestor | Alywin | Accounting Manager | Finance Manager | CNR |
| **RFP (CNR Loan)** | Requestor | Alywin | Accounting Manager | Finance Manager | CNR |
| **Purchase Order** | Procurement | — | Alywin | — | CNR |
| **Check Voucher** | Che/Quibs | Alywin | Accounting Manager | Finance Manager | CNR |
| **Journal Entry** | Alywin | — | Accounting Manager | — | CNR (if material) |
| **Inventory Count** | Adrian (staff) | — | Cherry → James | — | Alywin (if adjustment) |
| **Acknowledgment Receipt** | Mich | — | — | — | None (pre-numbered) |
| **Petty Cash Voucher** | Requestor | — | Quibong (custodian) | — | — |
| **Bank Reconciliation** | Quibs | — | Alywin | — | CNR (if adjustment > threshold) |

### RFP Signature Chain (from ACCTG-FOR-012)
```
Prepared by: Requestor
Checked by:  Alywin (Dept Head / Checker)
Approved by: Accounting Manager
Approved by: Finance Manager
```

Inventory count approval chain (separate process):
```
Counted by: Adrian
Verified by: Cherry
Approved by: James
Adjusted by: Alywin (if variance exists)
```

### Key Personnel & Roles

| Person | Primary Role | Domain | Signature Authority |
|--------|-------------|--------|-------------------|
| Mich | Cashier/AR Clerk | AR Collections | AR issuance only |
| Che | AP Clerk | AP/Payables | RFP preparation, CONSO |
| Quibong | Treasury/Cashflow | Treasury | PCF custodian, bank deposits, check release |
| Alywin | Accounting Head | Tax/Payroll/FA/JE | Approves RFP (checker), JEs, adjustments, FA |
| Accounting Manager | Superior | Overall | Approves RFP, CV |
| Finance Manager | Superior | Finance | Final AP approval |
| CNR (Clyde N. Rebollos) | COO | Executive | High-value PO, CV, asset purchases, write-offs |
| Cherry | Inventory Verifier | Inventory | Count verification |
| James | Inventory Approver | Inventory | Count approval |

## Decision
Approval is configured per document type with amount thresholds. No user can approve their own entries. The system enforces the chain as documented per document type above.

## Consequences
- Configurable per-company, per-segment
- Clear audit trail of who approved what, at which step
- Prevents single-person control over sensitive transactions
- AP module has the deepest approval chain (4 levels: Requestor → Checker → Acctg Mgr → Finance Mgr)
- RFP can be rejected at any step and returned to requestor
