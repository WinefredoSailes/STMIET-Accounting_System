# ADR-021: Advances to Employees Lifecycle

**Status:** Accepted  
**Date:** 2026-07-27  
**Deciders:** Architecture Team  

**References:**
- [ADR-018: RFP Document Model](./ADR-018-rfp-document-model.md) — RFP carries standing Cr to Advances to Employees
- [ADR-020: AP Approval Matrix](./ADR-020-ap-approval-matrix.md) — approval chain for RFP

---

## Context

Every RFP template in the AP workflow contains a **standing credit entry**:

```
Cr: Advances to Employees - Current    P 20,000.00
```

This appears on every RFP regardless of the payee or purpose. AP shadow confirmed this is standard practice, not an exception.

### Why P20,000 Stands on Every RFP

The Advances to Employees account (COA 12050-00) acts as a **clearing account** for officer and employee payables. The standing P20,000 credit represents:

1. **Officer advances** — CNR (COO) and other officers take cash advances for business expenses
2. **Employee reimbursements** — employees pay out-of-pocket and claim reimbursement via RFP
3. **Salary advances** — employees request salary advances before payday

The P20,000 is a **convention, not a fixed limit**. It represents the typical outstanding advance balance. The actual amount can differ per RFP.

### Current Flow

```
RFP Created:
    Dr: [Expense Account]            P X,XXX.XX
        Cr: Advances to Employees    P 20,000.00  (clearing)
        Cr: AP - Payee               P (X,XXX.XX - 20,000.00)

When employee liquidates:
    Dr: Advances to Employees        P 20,000.00
        Cr: [Actual Expense Acct]    P 20,000.00
```

### Why This Exists

The business uses Advances to Employees as a temporary holding account. The actual expense may not yet be categorized when the RFP is created. The standing credit:

1. Prevents the AP balance from being overstated
2. Gives time for the employee to submit supporting docs
3. Acts as a control — the advance must be liquidated before a new one is issued

---

## Decision

Advances to Employees is modeled as a formal lifecycle with four phases:

### Lifecycle Phases

#### Phase 1: RFP Creation (Advance Established)
- RFP is created with Cr Advances to Employees (default P20,000)
- Amount is adjustable per RFP (not hardcoded)
- The debit side is the actual expense/inventory/asset account
- AP - Payee gets the net amount (total - advance)

#### Phase 2: Advance Outstanding
- The Advances to Employees account shows a credit balance
- System tracks outstanding advances per employee/officer
- Before creating a new RFP for the same employee, system checks outstanding balance

#### Phase 3: Liquidation
- Employee submits supporting docs (receipts, travel order, etc.)
- A liquidation RFP or JE is created:
  ```
  Dr: Advances to Employees     P 20,000.00
      Cr: [Actual Expense Acct(s)]    P 20,000.00
  ```
- If actual expense > advance: additional RFP needed
- If actual expense < advance: excess must be returned

#### Phase 4: Netting / Close
- If excess advance is not liquidated by period-end, it becomes a receivable from the employee
- System can flag aging advances for management review

### Data Model

```python
class AdvanceToEmployee:
    rfp: RFP                       # Source RFP
    employee: Employee             # Who received the advance
    amount: Decimal                # Default P20,000
    outstanding: Decimal           # Unliquidated portion
    status: AdvanceStatus          # Active / Partial / Liquidated / Overdue
    
    liquidation_jes: List[JE]      # Liquidation entries
    created_at: datetime
    liquidated_at: datetime
    
class Employee:
    id: str
    name: str
    department: str
    total_outstanding_advances: Decimal   # Computed
```

### Business Rules

1. Default advance amount is P20,000 (configurable per employee level)
2. An employee with unliquidated advances > P50,000 cannot request new advances
3. Advances older than 30 days are flagged as "overdue" for management review
4. Year-end: all advances must be liquidated or classified as receivables

---

## Consequences

### Positive
- Formalizes the current manual practice into system-enforced lifecycle
- Prevents runaway advances (outstanding balance check)
- Auto-applied standing entry reduces manual JE errors
- Aging reports for management visibility

### Negative
- Additional complexity in RFP creation (must specify which employee gets the advance)
- If the P20,000 convention changes, all RFP templates need updating
- Liquidation requires separate JE or RFP — adds a step

### Neutral
- The P20,000 standing credit is a convention, not a system constraint
- Some RFPs may not involve employee advances (pure supplier payments) — in those cases, the Advances line can be zeroed
- COA: Advances to Employees - Current (12050-00) is an asset account (Dr balance normally, but Cr as a clearing mechanism)
