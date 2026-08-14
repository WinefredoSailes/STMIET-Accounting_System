# ADR-030: Cash Short / Excess & Inter-Account Borrowing

**Status:** Accepted
**Date:** 2026-08-14
**Deciders:** Architecture Team

**References:**
- [ADR-029: COLLECTIBLES Settlement](./ADR-029-collectibles-settlement.md) — variance source
- [ADR-028: Weekly Cash Cycle Model](./ADR-028-weekly-cash-cycle-model.md) — transfer rows
- [POSTING_RULES.md §8.3](../POSTING_RULES.md) — short/excess JE

---

## Context

The CASH SHORT sheet (SUMMARY OF CASH workbook) tracks cash variances per cycle:

```
TOTAL AMOUNT DEPOSITED (from passbooks)   = 7,004,321.17
TOTAL NET AMOUNT CLIENT PAID COLLECTED    = 9,398,277.00 (Distribution)
DIFFERENCE = CASH SHORT/EXCESS            = -2,393,955.83
```

Also from the weekly cycle sheets:
- **`Inter-account fund transfer`** rows — money moved between banks (e.g., PNB→KB, MBTC→1VB, PCF&COH→PNB)
- **`Funds Borrowed from other accounts`** — borrowings row, e.g., PCF&COH 471,600 / 2,100,000

**Quibong shadow:** "Variance: trace manually, typo." — the root causes are typos (cashier entry, POP mismatch, bank-side).

**Current behavior observed in January 2026 cycles:**
- Bank A short of cash → transfer from Bank B (inter-account)
- Borrowings from other accounts recorded as an activity row
- Large "CASH SHORT ACTUAL" (-931,189.76) tracked at cycle end with no explanation recorded

---

## Decision

Cash variances and inter-account borrowing are modeled as **explicit, explainable events**.

### 1. Cash Short/Excess Detection

The system computes per cycle:
```
Expected cash (book collections + borrowings)
vs Actual cash (bank deposits + cash on hand + transfers received)
= Variance
```

Variance ≠ 0 requires:
- **Cause classification**: Typo (book), Typo (bank), POP mismatch, Unrecorded transaction, Pending deposit (float)
- **Resolution**: corrective JE (ADR-005 reversal) OR carry-forward with explanation
- **Approval**: Alywin for any adjustment JE (per ADR-008)

JE when confirmed short: `Dr 63210 Cash Short Expense | Cr Cash in Bank`
JE when confirmed excess: `Dr Cash in Bank | Cr 430xx Other Income`

### 2. Inter-Account Transfer (Borrowing/Lending)

```python
class InterAccountTransfer:
    from_bank: BankCode
    to_bank: BankCode
    cycle: CashCycle
    amount: Decimal
    transfer_type: str     # FUND_TRANSFER / BORROWING / LOAN_CLEAR
    reference: str         # Check #, bank reference
    purpose: str           # Required — e.g., "MBTC maintaining balance shortfall"
    created_by: User       # Quibong
    approved_by: User      # Alywin
```

**Posting:**
```
Dr: Cash in Bank - [To]        amount
    Cr: Cash in Bank - [From]       amount
```

No P&L impact — cash-to-cash movement. Borrowings from *external* accounts (e.g., loans, PCF bank lines) instead post to the appropriate liability/equity account (see ADR-031 financing section).

### 3. Explanations Mandatory

Every transfer and every variance carry-forward requires a purpose field. The "CASH SHORT ACTUAL" line must have an explanation before the cycle closes — eliminating the unexplained -931,189.76 pattern.

---

## Consequences

### Positive
- Variances get classified and resolved, not traced manually for hours
- Inter-account transfers are traceable with approval
- Unreported borrowings become visible
- Cycle-close blocks unclassified variances

### Negative
- Requires Quibong/Alywin to enter purpose on every variance (new discipline)
- Bank-side errors are external — system can only track and wait

### Neutral
- Transfer JEs are simple cash-to-cash entries (no P&L)
- Cash Short Expense / Other Income accounts exist in COA already (63210 range / 43060 range)