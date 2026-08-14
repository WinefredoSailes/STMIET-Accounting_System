# ADR-029: COLLECTIBLES Settlement

**Status:** Accepted
**Date:** 2026-08-14
**Deciders:** Architecture Team

**References:**
- [ADR-028: Weekly Cash Cycle Model](./ADR-028-weekly-cash-cycle-model.md) — cycle data feeds settlement
- [ADR-011: Multi-Segment Data Architecture](./ADR-011-multi-segment-architecture.md) — segment separation
- [POSTING_RULES.md §15](../POSTING_RULES.md) — cash cycle posting

---

## Context

The COLLECTIBLES sheet (in SUMMARY OF CASH workbook) reconciles **two departments** per cycle:

### Distribution & Hauling Dept (Left Side)

```
TOTAL NET AMOUNT CLIENT PAID COLLECTED    =  6,615,525
TOTAL DEPOT AMOUNT PAID                    =  6,315,100
GROSS MARK-UP                              =    300,425
```

Plus adjustments:
```
LESS: TUBIL-OFFICE
LESS: PREVIOUS ORDERS
TOTAL NET AMOUNT CLIENT PAID COLLECTED (adj)
```

### Finance & Accounting Dept (Right Side)

```
TOTAL AMOUNT CLIENT PAID                 = 7,004,321.17  ← Gross per cashier records
BORROWINGS FROM OTHER ACCOUNTS           =         0
TOTAL DEPOT AMOUNT PAID                  = 7,641,900
EXCESS CASH REMAINING FROM COLLECTIONS   =  -637,578.83
Add: Ending Available Balance            = 2,257,842.54
TOTAL EXCESS CASH AFTER PAYMENTS         = 1,620,263.71
LESS: OTHER PAYMENTS / OUTFLOW           =   -635,973.95  (RFP AP, PCF, Loans, Transfers)
ENDING BALANCE, CASH AVAILABLE           =   984,289.76
LESS: ADVANCE PAYMENTS FOR NEXT CYCLE    =  -349,405
ACTUAL CASH EXCESS FOR THE CYCLE         =   634,884.76
```

### Cashier Reconciliation (Bottom)

```
PASSBOOKS          = 7,004,321.17
GCASH              =     5,050.00
OTHER BANK CREDITS =      -292.55
COLLECTED LAST CYCLE =   -43,800.00
TOTAL RECON        = 6,965,278.62   vs CASHIER = 7,685,480 → variance tracked
```

**Key insight:** The Distribution side computes **gross mark-up** (client paid − depot paid). The Finance side tracks **net cash position** after all outflows. The CASHIER recon reconciles passbook/bank records against cashier collection records. Variances roll to the next cycle (`REMAINING COLLECTIBLES` / `CASH SHORT ACTUAL`).

**Who computes gross mark-up:** Leaslyn ("Sir Bong") per Quibong shadow.

---

## Decision

The COLLECTIBLES settlement is modeled as a **cross-department reconciliation document** generated per cycle.

### Settlement Model

```python
class CollectiblesSettlement:
    cycle: CashCycle
    created_by: str              # Leaslyn computes gross mark-up
    
    # Distribution side
    client_paid_total: Decimal          # Sum of collections per AR (ADR-013)
    depot_paid_total: Decimal           # Payments to fuel depot
    gross_markup: Decimal               # client_paid - depot_paid
    tubil_office_adj: Decimal           # Deduction line (0 if none)
    previous_orders_adj: Decimal        # Deduction line
    net_client_paid_collected: Decimal  # Adjusted total
    
    # Finance side
    total_client_paid_gross: Decimal    # Per cashier records (bank deposits)
    borrowings: Decimal                 # ADR-030
    depot_paid_total_finance: Decimal
    excess_cash_from_collections: Decimal
    ending_available_balance: Decimal
    total_excess_after_payments: Decimal
    other_outflows: Decimal             # RFP AP + PCF + loans + transfers
    ending_balance_cash_available: Decimal
    advance_payments_next_cycle: Decimal
    actual_cash_excess: Decimal
    
    # Cashier recon
    passbooks: Decimal
    gcash: Decimal
    other_bank_credits: Decimal
    collected_last_cycle: Decimal
    cashier_total: Decimal
    
    # Result
    variance: Decimal                    # REMAINING COLLECTIBLES / short
    carry_forward_to_next_cycle: Decimal
```

### Posting Behavior

1. **DEPOT PAYMENTS** — Dr AP-Current / Advances to Suppliers | Cr Cash in Bank (already posted via AP/Treasury)
2. **GROSS MARK-UP** — arises from the difference; recognized per normal fuel posting (revenue at delivery, not at settlement — see ADR-012 prepayment model). The settlement *explains* the mark-up but does not itself create a JE; JEs come from the underlying collection and delivery events
3. **VARIANCE** — if settlement ≠ actual, variance becomes `CASH SHORT` (ADR-030) or carry-forward collectible; requires Alywin review when nonzero

### Workflow

```
Cycle ends (Tue)
    → System generates settlement draft from posted data
    → Distribution side: verify client_paid vs depot_paid (Leaslyn)
    → Finance side: verify deposits, borrowings, outflows (Quibong)
    → Cashier recon: passbook/gcash values (Quibong + Mich data)
    → Approvals: Quibong → Alywin
    → Variance ≠ 0 → flagged, carry-forward to next cycle
```

---

## Consequences

### Positive
- Replaces the two-department manual reconciliation with a generated document
- Gross mark-up visibility per cycle (Leaslyn's computation automated)
- Variance carry-forward is explicit and tracked across cycles
- Single source of truth: settlement reads from posted transactions

### Negative
- Initial cycles require validation of derivation rules against real data (Jan cycles available)
- Passbook/GCash values may arrive after cycle end (out-of-band data) — settlement needs "as of" handling

### Neutral
- Gross vs net mark-up terminology is retained (familiar to the team)
- TUBIL-OFFICE and PREVIOUS ORDERS lines are legacy adjustments — configurable include/exclude