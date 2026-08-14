# ADR-022: P2,500 Threshold Rule

**Status:** Accepted  
**Date:** 2026-07-27  
**Deciders:** Architecture Team  

**References:**
- [ADR-017: Purchase-to-Pay Document Flow](./ADR-017-purchase-to-pay-cycle.md) — two payment paths
- [ADR-018: RFP Document Model](./ADR-018-rfp-document-model.md) — RFP for amounts P2,500+
- [ADR-020: AP Approval Matrix](./ADR-020-ap-approval-matrix.md) — RFP approval chain

---

## Context

AP shadow and RFP Templates revealed a clear threshold rule for payment processing:

| Amount | Document | Path | Approvals | Custodian |
|--------|----------|------|-----------|-----------|
| **P2,500 and above** | RFP (ACCTG-FOR-012) | Full Purchase-to-Pay chain | Requestor → Alywin → Acctg Mgr → Finance Mgr | Treasury (Quibs) |
| **Below P2,500** | Petty Cash Voucher (PCV) | Simplified PCF path | Requestor → Quibong | Quibong (custodian) |

### PCF Details (from interview)

- **Custodian:** Quibong
- **Replenishment trigger:** Percentage-of-amount-left (exact % TBD from Quibs shadow)
- **Max per expense:** Below P2,500 (by definition)
- **Supporting docs:** Required but current practice has "walk-in PCF without supporting docs" — categorized as a pain point
- **COA impact:** PCF expenses are categorized when replenished, not at disbursement

### Current Pain Point

> "Walk-in PCF without supporting docs" — Che shadow

Staff submit PCF requests after purchasing without prior approval or receipts. This creates categorization issues for AP.

---

## Decision

The P2,500 threshold is a system-enforced rule that determines which payment path a request follows.

### Rules

1. **Amount ≥ P2,500** → RFP (ACCTG-FOR-012) with full approval chain
2. **Amount < P2,500** → Petty Cash Voucher (PCV) from Quibong
3. **Threshold is configurable** — not hardcoded, stored in system parameters
4. **No splitting** — a single purchase cannot be split into sub-P2,500 amounts to bypass RFP

### PCF Model

```python
class PettyCashVoucher:
    id: str                      # PCV-YYYY-SEQ
    amount: Decimal              # Must be < threshold (default P2,500)
    payee: str                   # Employee/Staff name
    purpose: str
    expense_category: str        # Assigned at creation or at replenishment
    supporting_docs: List[File]  # Receipt images
    
    status: str                  # Pending → Approved (Quibong) → Disbursed → Replenished
    custodian: User              # Quibong
    replenishment_batch: PCReplenishment
    
class PettyCashFund:
    custodian: User              # Quibong
    imprest_amount: Decimal      # Fixed fund amount (TBD)
    current_balance: Decimal     # Computed: imprest - total disbursed + total replenished
    replenishment_threshold: Decimal  # % of imprest — triggers replenishment (TBD from Quibs)
    last_replenishment: date
```

### PCF Workflow

```
1. Requestor submits PCV with purpose and amount
2. Quibong approves (verifies fund balance)
3. Cash disbursed from PCF
4. Receipt/receipts attached to PCV
5. When fund reaches threshold → Quibong requests replenishment
6. Replenishment RFP created (≥P2,500 trigger for the batch replenishment)
7. All PCV expenses in the batch are categorized and posted as JEs
```

### PCF Replenishment JE

When PCF is replenished (via RFP):

```
Dr: [Various Expense Accounts]    P Total (all PCVs in batch)
Cr: Cash in Bank - [PCF Account]  P Total
```

The expenses are categorized at replenishment time, not at disbursement. This is the current practice and is retained (per inventory interview, this is how the existing system works).

---

## Consequences

### Positive
- Clear, enforceable boundary between petty cash and formal AP
- Prevents RFP process overload for small expenses
- PCF custodian (Quibong) has clear responsibility

### Negative
- PCF without prior approval means expenses are categorized after the fact
- Replenishment batch requires aggregation of multiple PCVs
- Walk-in PCF without docs is a process issue, not solvable by system alone (but system can require at minimum a purpose field)

### Neutral
- Replenishment threshold % is TBD from Quibs shadow — placeholder for now
- PCF fund amount (imprest) is TBD from Quibs shadow
- The system can flag PCVs missing supporting docs after 7 days
