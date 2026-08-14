# ADR-026: Bank Reconciliation Process

**Status:** Accepted
**Date:** 2026-08-14
**Deciders:** Architecture Team

**References:**
- [ADR-016: Bank Code & Deposit Tracking](./ADR-016-bank-code-and-deposit-tracking.md) — bank code master
- [ADR-028: Weekly Cash Cycle Model](./ADR-028-weekly-cash-cycle-model.md) — cycle feeds book balance
- [ADR-005: Immutable Journal Entries](./ADR-005-immutable-journal.md) — corrections via reversal

---

## Context

Quibong shadow (Cashflow, Days 5-6) documented the bank reconciliation process:

| Finding | Detail |
|---------|--------|
| Accounts reconciled | **All 12 accounts / 9 banks** — PNB, PSBC-S, PSBC-C, KB, 1VB, BDO, MBTC, RCBC, CHINA BANK, E.TAN/STPC, PCF & COH |
| Time per bank | **10-15 minutes** |
| Tools | Excel + manual check-off |
| Difference causes | **Typos, POP (Proof of Payment) mismatch, cashier typo** |
| Frequency | Ongoing; all accounts actively reconciled |

**Pain points identified:**
1. 12 accounts × 10-15 min = ~2-3 hours of manual reconciliation per cycle
2. Differences traced manually — typos (both cashier and bank-side) cause most variances
3. No system-enforced matching between book and bank transactions
4. POP mismatch: proof of payment reference differs from recorded transaction

---

## Decision

Bank reconciliation is a **system-assisted workflow** with automated matching and manual review.

### Process Model

```
Cycle-End (Weekly):
    Book side: All bank transactions from the cycle (Collections, Checks, Transfers, RFP payments)
    Bank side: Bank statement imports (manual CSV entry or file upload — no bank API feeds confirmed)
    
    System matching pass:
        1. Exact match: amount + date + reference (auto-matched, cleared)
        2. Amount-only match: single candidate → suggested match (user confirms)
        3. POP match: POP reference number links if present
        4. No match → exception queue (user resolves)
    
    Exceptions:
        - Typo in book entry (amount/date wrong) → corrective JE (via reversal, ADR-005)
        - Bank-side error → note until bank corrects
        - Missing bank statement entry → wait for next statement / flagged
```

### Data Model

```python
class BankReconciliation:
    bank: BankCode
    cycle: CashCycle
    book_balance: Decimal          # From GL
    bank_balance: Decimal          # From statement
    reconciled_at: datetime
    status: str                    # Draft → In Progress → Reconciled → Adjusted

class BankReconLine:
    recon: BankRecon
    source: str                    # BOOK / BANK
    date: date
    amount: Decimal
    reference: str
    match_status: str              # Matched / Suggested / Unmatched / Adjusted
    matched_to: BankReconLine      # FK to opposite-side line
    adjustment_je: JE              # If typo correction needed
```

### Matching Rules

1. **Exact match** — same amount + same date + same reference → auto-cleared
2. **Amount match** — same amount, single candidate either side → flagged for confirm
3. **Reference match** — POP/check number matches, amount differs → flagged (typo likely)
4. **Unmatched book entries** — appear in exception list with suggested causes
5. **Unmatched bank entries** — e.g., bank charges, interest → present for JE suggestion

### Correction Workflow (typos)

- Book entry typo → **reversal JE** + new correct entry (ADR-005 immutable journal)
- Category flag: `REVERSAL_FOR_RECON` links the correction to the recon instance
- Cashier typos are logged with `created_by` attribution → training/QA signal

---

## Consequences

### Positive
- 2-3 hours per cycle → minutes (auto-matched lines need only review)
- Typo causes visible in exception queue with attribution
- Every reconciliation result is retained (audit trail through cycles)
- POP references used as matching key (behavior already exists manually)

### Negative
- Bank statements still entered manually (no bank API confirmed) — CSV import is a partial fix
- Reconciliation requires accurate book-side reference entry (discipline from Mich/Che)
- Exception queue requires judgment — not fully automatable

### Neutral
- Reconciled status locks the cycle period for further GL changes (ties to month-end close)
- ADB/maintaining balance checks remain part of the cycle sheet (ADR-028)