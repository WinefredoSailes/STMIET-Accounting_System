# ADR-013: Cycle-Based Customer Ledger

**Status:** Accepted (Updated 2026-07-23)  
**Date:** 2026-07-23  
**Deciders:** Architecture Team, Accounting Lead  

**References:** [ADR-007: Centralized Customer Master](./ADR-007-centralized-customer.md) — this ADR builds on the centralized customer master to add cycle-level ledger tracking per customer. The Customer entity in ADR-007 is the parent of the CustomerCycle records defined here.

---

## Context

The existing COLLECTION SYSTEM macro tracks each customer on a **weekly cycle basis** (Tuesday to Monday). This is the fundamental unit of the business — pricing, orders, deliveries, and payments are all organized by cycle.

### The Core Problem This Solves

**Overpayments and short payments happen in both directions:**
- Sometimes the client pays before the price is known → payment is estimated → over/short appears when price is confirmed
- Sometimes the price is known but the client still pays more or less than the exact amount → over/short appears immediately

The customer ledger is the **single mechanism** that tracks both scenarios. It stores the running cumulative balance per customer, so overpayments (credit) and short payments (debit) are always visible and carried forward until settled.

### Key observations from the macro:

1. **Cycle naming:** `"FEBRUARY 4-10, 2025"`, `"DEC. 16-22, 2025"` — each cycle is one calendar week
2. **Per-cycle data tracked:**
   - Fuel quantities ordered (X=Premium, R=Regular, D=Diesel)
   - Three price tiers per product per cycle (Regular, Patron, Volume)
   - Computed amount payable per product
   - Payments received per product (with PO# references)
   - Previous balance catch-up payments
   - Offset of previous cumulative overpayment/collectible
   - Overpayment/collectible per product
   - Running cumulative balance
3. **Customer status per cycle:** "OK", "FOR RECON", or blank
4. **Up to 5 payment references per cycle** (bank + AR# + amount)

### Critical timing observation:

**Payments and prices arrive independently.** The customer ledger must handle any arrival order:

| Scenario | Order of Events | How Ledger Handles It |
|----------|----------------|----------------------|
| **A** | Payment arrives first → Price confirmed later | Payment recorded as "unapplied". When price arrives, Amount Payable computed, over/short calculated, cumulative updated. |
| **B** | Price confirmed first → Payment arrives later | Amount Payable already known. Payment compared immediately, over/short calculated, cumulative updated. |

Both scenarios produce the same result at cycle end. The ledger does not care about arrival order — it only cares about two numbers: **Total Payments** and **Amount Payable**.

### Real example (DEMONSTRATION sheet):

| Cycle | Orders | Amt Payable | New Payments | Prev Bal Catch-up | Offset | Net Over/(Short) | Cumulative |
|-------|--------|-------------|-------------|-------------------|--------|-----------------|------------|
| FEB 4-10 | X=1, R=2 | 166,850 | 150,000 | 0 | 0 | -16,850 | **-16,850** |
| FEB 11-17 | X=1 | 55,300 | 53,150 | 16,850 | -16,850 | -2,150 | **-2,150** |
| FEB 18-24 | X=1 | 55,100 | 59,850 | 2,150 | -2,150 | +4,750 | **+4,750** |
| FEB 25-MAR 3 | X=1 | 55,100 | 50,350 | 0 | +4,750 | 0 | **0** |

The netting logic:
- **New Payments** = Fresh payments for this cycle's orders
- **Prev Bal Catch-up** = Extra payment to cover previous shortfalls
- **Offset** = Using previous overpayments to reduce this cycle's payable
- **Total for cycle** = New Payments + Prev Bal Catch-up − Offset
- **Over/(Short)** = Total for cycle − Amount Payable
- **Cumulative** = Previous Cumulative + Over/(Short) for this cycle

---

## Decision

**Adopt the weekly cycle as the primary grouping unit for customer transactions. The customer ledger's cumulative balance is the single source of truth for all overpayments and short payments, regardless of whether payment or price arrived first.**

### Rules

1. **Each customer has a cycle-based ledger:**
   - One row per customer per cycle
   - Stores quantities, prices, amounts payable, payments, catch-ups, offsets, and balances
   - The cumulative balance shows whether the client owes (negative) or has credit (positive)

2. **Cycles are system-generated:**
   - Start on Tuesday, end on Monday
   - Named as `"[MONTH] [START DAY]-[END DAY], [YEAR]"`
   - Consecutive with no gaps

3. **Prices are captured per cycle, not per transaction:**
   - Prices are set by Operations per cycle (can be before or after payments arrive)
   - The system stores all three price tiers per cycle per product
   - Amount Payable is computed when price is confirmed (immediately if price already known, or later if payment came first)

4. **Cycle-level netting (the core logic):**

   ```
   Total Payments = New Payments (Premium + Regular + Diesel)
                   + Previous Balance Catch-up
                   − Offset of Previous Cumulative Overpayment

   Cycle Over/(Short) = Total Payments − Amount Payable

   New Cumulative Balance = Previous Cumulative Balance
                          + Cycle Over/(Short)
   ```

   - Positive cumulative = Client has credit (Unearned Revenue / Overpayment)
   - Negative cumulative = Client owes (Accounts Receivable / Collectible)

5. **Multiple payments per cycle:**
   - A customer can make up to 5 separate payments within one cycle
   - Each payment recorded with: Date, Bank, AR#, Amount, PO#
   - Payments are tracked per product (Premium/Regular/Diesel)

6. **Payment status lifecycle:**
   - `Unapplied` → Payment received, price not yet confirmed
   - `Applied` → Price confirmed, Amount Payable computed, Over/(Short) calculated
   - `Netted` → Cycle closed, cumulative balance finalized
   - `Settled` → Cumulative balance reaches zero (fully paid)

---

## Consequences

### Positive
- Matches existing workflow exactly — no process change for Mich
- Handles both arrival orders (payment-first or price-first) with the same logic
- Overpayments and short payments are explicit and traceable per customer per cycle
- Cumulative balance is always available — Mich can see at a glance if a client is over or short
- Replaces the manual paper list of collectibles

### Negative
- Intra-cycle price changes cannot be handled within the same cycle
- New customers added mid-cycle may have partial cycles
- Cycle cutoff (Monday end-of-day) must be enforced strictly
- The "unapplied" period means cash is in Unearned Revenue but not yet matched to an order

### Neutral
- Cycle frequency could be changed but weekly is the established norm
- Historical data can be migrated cycle by cycle from the existing macro
- The offset logic mirrors exactly how the existing Excel macro works

---

## How the Ledger Solves Both Scenarios (Walkthrough)

### Scenario A: Payment before price

```
Cycle: FEB 4-10
Step 1: Payment P 150,000 arrives → recorded as Unapplied (price unknown)
Step 2: Price confirmed: X=76.35, R=75.85 → Amt Payable = 166,850
Step 3: Netting: 150,000 - 166,850 = -16,850 (SHORT)
Step 4: Cumulative: -16,850
Mich sees in the ledger: "Client owes P 16,850"
```

### Scenario B: Price before payment

```
Cycle: FEB 4-10
Step 1: Price confirmed: X=76.35, R=75.85 → Amt Payable = 166,850
Step 2: Payment P 150,000 arrives → recorded as Applied (price known)
Step 3: Netting: 150,000 - 166,850 = -16,850 (SHORT)
Step 4: Cumulative: -16,850
Mich sees in the ledger: "Client owes P 16,850"
```

### End result: identical

In both cases, the customer ledger shows the same cumulative balance. The ledger **absorbs the timing difference** and always produces the correct net position.

---

## Data Model

```python
class CustomerCycle:
    customer_id: str       # CDC code (e.g., "DH1000")
    cycle_label: str       # "FEBRUARY 4-10, 2025"
cycle_start: date      # Tuesday

    cycle_end: date        # Monday
    # Quantities ordered
    qty_premium: Decimal   # X
    qty_regular: Decimal   # R
    qty_diesel: Decimal    # D

    # Price tiers (per liter)
    price_regular_premium: Decimal
    price_regular_regular: Decimal
    price_regular_diesel: Decimal
    price_patron_premium: Decimal
    price_patron_regular: Decimal
    price_patron_diesel: Decimal
    price_volume_premium: Decimal
    price_volume_regular: Decimal
    price_volume_diesel: Decimal

    # Prices confirmed?
    prices_confirmed: bool
    prices_confirmed_at: datetime

    # Computed amounts payable (only when prices confirmed)
    amount_payable_premium: Decimal
    amount_payable_regular: Decimal
    amount_payable_diesel: Decimal

    # Payments (new money this cycle)
    payments: List[Payment]

    # Previous balance handling
    prev_balance_catch_up: Decimal    # Extra money paid to cover past shorts
    prev_cumulative_offset: Decimal   # Previous overpayment used to offset

    # Computed balances
    total_payments: Decimal       # New + Catch-up − Offset
    cycle_over_short: Decimal     # Total − Amount Payable
    cumulative_balance: Decimal   # Running total across all cycles

    status: str                   # "OK", "FOR RECON"
    payment_status: str           # "Unapplied", "Applied", "Netted", "Settled"
```

```python
class Payment:
    payment_date: date
    bank_code: str           # RCS, PSS, MBC, etc.
    ar_number: str           # Pre-numbered AR#
    amount: Decimal
    po_number: str           # PO# from customer
    product: str             # "Premium", "Regular", "Diesel"
    status: str              # "Unapplied", "Applied"
```
