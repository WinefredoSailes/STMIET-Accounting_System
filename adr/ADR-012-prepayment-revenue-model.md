# ADR-012: Prepayment Revenue Recognition Model

**Status:** Accepted (Updated 2026-07-23)  
**Date:** 2026-07-23  
**Deciders:** Architecture Team, Accounting Lead  

**References:**
- [ADR-004: Event-Driven Posting Engine](./ADR-004-event-driven-posting.md) — this ADR defines the specific business events (Collection, Price Confirmation, Delivery) and their posting rules.
- [ADR-005: Immutable Journal Entries](./ADR-005-immutable-journal.md) — once a collection or delivery JE is posted, it cannot be reversed except via offsetting entry.
- [ADR-013: Cycle-Based Customer Ledger](./ADR-013-cycle-based-ledger.md) — the customer ledger is where overpayments and short payments are tracked and carried forward.

---

## Context

The business operates on a **prepayment-first** model for fuel (DHPP) and equipment (DMIE). Critically, **clients pay BEFORE the price is confirmed** in many cases. The payment is an estimated/approximate amount. The exact Amount Payable is computed later when Operations confirms the cycle price.

### Two Scenarios — Same Resolution

The cashier encounters **two different arrival orders** for payments and prices. Both converge at the same customer ledger netting logic:

#### Scenario A: Payment arrives before price is confirmed
```
Payment (POP) arrives → Mich issues AR → Price confirmed later → Netting at cycle end
```
Most common for fuel orders. Client sends POP without knowing exact price. Payment sits as "unapplied" until Operations sets the price.

#### Scenario B: Price is confirmed before payment arrives
```
Price confirmed → Client pays (cash/POP) → Mich issues AR → Immediate netting possible
```
Also happens. Cash walk-ins or informed clients who paid after price announcement. Even in this case, the payment amount may still be approximate — client might overpay or underpay intentionally.

#### Scenario C: Price is confirmed, client pays the exact amount
```
Price confirmed → Client pays exact amount (POP) → Mich issues AR → Fully settled
```
Clean case. Payment equals Amount Payable. No overpayment, no short payment. No carry-forward needed.

#### All scenarios converge at the same logic:
```
At cycle end (or at price confirmation):
  Amount Payable = Qty Ordered × Confirmed Price
  Overpayment = Total Payments − Amount Payable  (if positive)
  Short Payment = Amount Payable − Total Payments  (if positive)
  Cumulative Balance carries forward to next cycle
```

The **customer ledger** (see ADR-013) handles all three scenarios identically at the netting stage. The system does not need to know which event happened first — it only needs to know:
- How much was paid? (Recorded at payment time)
- What was the confirmed price? (Recorded at price confirmation time)
- What was ordered? (Recorded at order time)

### Real example from DEMONSTRATION sheet:

| Cycle | Amt Payable | Payments | Over/(Short) | Cumulative |
|-------|-------------|----------|-------------|------------|
| FEB 4-10 | 166,850 | 150,000 | -16,850 | **-16,850** |
| FEB 11-17 | 55,300 | 53,150 + 16,850(catch-up) | -2,150 | **-2,150** |
| FEB 18-24 | 55,100 | 59,850 + 2,150(catch-up) | +4,750 | **+4,750** |
| FEB 25-MAR 3 | 55,100 | 50,350 + 0(catch-up) + 4,750(offset) | 0 | **0** |

### From the General Journal:

Overpayment adjustments are posted as:
```
Dr: A/Receivables - Fuel Clients (12030)  P 200
   Cr: Sales - Fuel Hauling (40000)  P 200
```
(When overpayment is detected upon delivery — the overpayment is applied against the receivable)

---

## Decision

**Model all DHPP and DMIE collections as liability-creating events (Unearned Revenue) with a separate "unapplied" status until price confirmation. Overpayments and short payments are computed at cycle end and carry forward as cumulative running balances in the customer ledger.**

### Rules

1. **Collection creates a liability**, not revenue:
   - Every payment received creates/credits Unearned Revenue
   - Payment is tagged as **unapplied** until the cycle price is confirmed
   - The system never automatically recognizes revenue at collection time

2. **Price confirmation triggers Amount Payable computation:**
   - When Operations confirms prices for the cycle, the system computes:
     - Amount Payable = Quantity Ordered × Applicable Tier Price
     - Overpayment = Total Payments − Amount Payable (if positive)
     - Short Payment = Amount Payable − Total Payments (if positive)
   - Payments move from "unapplied" to "applied" status
   - This happens regardless of whether payments arrived before or after price confirmation

3. **Overpayment handling:**
   - Excess stays in Unearned Revenue (liability)
   - Carries forward to the next cycle as a credit balance
   - Applied as "Offset" in the next cycle's computation
   - Can be refunded or applied to future deliveries

4. **Short payment handling:**
   - Deficit becomes a Collectible (Accounts Receivable)
   - Carries forward to the next cycle as a debit balance
   - Client must pay the shortfall in a subsequent cycle
   - Tracked as "Previous Balance Payment" in the next cycle

5. **Cumulative running balance in customer ledger:**
   - Each cycle's result (Overpayment or Short Payment) is added to the cumulative balance from all previous cycles
   - Cumulative balance = 0 means fully settled
   - Cumulative > 0 means the client has credit (Unearned Revenue)
   - Cumulative < 0 means the client owes (Accounts Receivable)

6. **Revenue recognition is a separate (later) event:**
   - Upon fuel delivery: Dr: Unearned Revenue → Cr: Sales - Fuel Hauling
   - Delivery recognition uses the confirmed price, not the estimated payment
   - OPS services are recognized immediately at service completion

---

## Consequences

### Positive
- Matches actual accounting practice (verified in Collection System macro and General Journal)
- Handles both arrival orders — payment-before-price and price-before-payment — with the same logic
- Overpayments and short payments are explicit and traceable
- Clear audit trail: collection → unapplied → price confirmed → applied → netted → carried forward
- Customer is the single source of truth for over/short tracking

### Negative
- Requires a "price confirmation" event/status in the workflow
- Cumulative balance must be tracked per customer indefinitely (carries across cycles)
- Short payments create AR that needs follow-up (same pain point as today)
- Revenue cannot be reported from collections alone; needs delivery data

### Neutral
- Unearned Revenue reconciliation happens automatically via cumulative balance
- The "unapplied" status adds one state to the payment lifecycle

---

## Accounting Flow Diagram

### Scenario A: Payment before price

```
 Time
  │
  ├── COLLECTION EVENT (price unknown — Scenario A)
  │   Client pays P 150,000
  │   Dr: PNB Checking  P 150,000
  │   Cr: Unearned Revenue - DHPP  P 150,000   [unapplied]
  │
  ├── PRICE CONFIRMATION EVENT (hours/days later)
  │   Operations confirms: Premium @ P 76.35, Regular @ P 75.85
  │   Qty ordered: X=1, R=2
  │   Amt Payable: P 55,950 + P 110,900 = P 166,850
  │   PAYMENT vs PAYABLE: P 150,000 - P 166,850 = -P 16,850 (SHORT)
  │   → Payment moves to "applied"
  │   → Short tracked in customer ledger cumulative balance
  │
  ├── DELIVERY EVENT (days or weeks later)
  │   Fuel delivered: Dr: Unearned Revenue  P 55,300
  │                    Cr: Sales - Fuel Hauling  P 55,300
  │
  └── CYCLE END — Cumulative balance: -P 16,850 (carries forward)
```

### Scenario B: Price before payment

```
 Time
  │
  ├── PRICE CONFIRMATION EVENT (Scenario B)
  │   Operations confirms prices for the cycle
  │   System computes: Amount Payable = P 166,850
  │
  ├── COLLECTION EVENT (client pays after knowing price)
  │   Client pays P 150,000
  │   Dr: PNB Checking  P 150,000
  │   Cr: Unearned Revenue - DHPP  P 150,000
  │   Payment is "applied" immediately (price already known)
  │   PAYMENT vs PAYABLE: P 150,000 - P 166,850 = -P 16,850 (SHORT)
  │   → Short tracked in customer ledger cumulative balance
  │
  ├── DELIVERY EVENT
  │   Fuel delivered: Dr: Unearned Revenue  P 55,300
  │                    Cr: Sales - Fuel Hauling  P 55,300
  │
  └── CYCLE END — Cumulative balance: -P 16,850 (carries forward)
```

### Both scenarios produce the same end state
Even though the event order differs, the cycle netting (Amt Payable vs Total Payments) and cumulative balance are **identical**.
