# ADR-014: Three-Tier Pricing with Cycle Snapshots

**Status:** Accepted (Updated 2026-07-23)  
**Date:** 2026-07-23  
**Deciders:** Architecture Team, Operations Lead  

**References:**
- [ADR-004: Event-Driven Posting Engine](./ADR-004-event-driven-posting.md) — pricing confirmation is a business event that triggers Amount Payable computation and moves payments from "unapplied" to "applied".
- [ADR-012: Prepayment Revenue Model](./ADR-012-prepayment-revenue-model.md) — pricing confirmation is the step that converts estimated payments into exact overpayment/short payment amounts.

---

## Context

Pricing is the single biggest operational bottleneck in the cashier workflow. Key findings from the shadow:

- **Prices change every cycle** (sometimes more frequently)
- **Three price tiers** exist: Regular, Patron, and Volume
- **Three products** are priced independently: Premium (XCS), Regular (REG), Diesel (ADO)
- **Each customer is assigned a price tier** — not all customers get volume pricing
- **The price is confirmed via Viber/FB Messenger** — after payments have already been received
- **Late price confirmation** is the #1 cause of delay in finalizing cycle balances
- **AR reconciliation accuracy (~70%)** is primarily due to pricing inconsistencies
- **Clients pay estimated amounts** before knowing the actual price — the difference becomes overpayment or short payment

### Critical correction from the cashier data:

**Payments are NOT blocked by missing prices.** Mich issues Acknowledgment Receipts and records payments immediately when POP arrives. The price confirmation comes later from Operations. The system must support:

1. **Payment entry without confirmed price** — record the cash, issue AR
2. **Price confirmation as a separate event** — Operations sets price, system computes Amount Payable
3. **Auto-netting** — system compares Total Payments vs Amount Payable to produce overpayment/short payment

### Current system in the macro:
```
| Cycle           | X | R | D | X Reg | X Pat | X Vol | R Reg | R Pat | R Vol | D Reg | D Pat | D Vol |
|-----------------|---|---|---|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| FEB 4-10, 2025  | 1 | 2 | 0 | 76.35 | 58.50 | 55.95 | 75.85 | 58.00 | 55.45 | 72.25 | 55.85 | 52.30 |
| DEC 23-29, 2025 | 1 | 0 | 0 | 91.25 | 54.15 | 51.60 | 90.75 | 53.65 | 51.10 | 85.35 | 53.70 | 48.95 |
```

Prices vary significantly cycle-to-cycle. Premium Regular price went from P 76.35 (Feb) to P 92.85 (Jan 27-Feb 2), a 22% swing.

---

## Decision

**Model pricing as a time-series snapshot per cycle, with customer-level tier assignment. Pricing confirmation is a separate event from payment collection — it triggers Amount Payable computation and payment application.**

### Rules

1. **Master price list per cycle:**
   - Stored as a single record per cycle: 9 price points (3 products × 3 tiers)
   - Prices are set by Operations (can be before, during, or after the cycle)
   - Once confirmed, prices are immutable for that cycle

2. **Customer tier assignment:**
   - Each customer has an assigned tier: Regular, Patron, or Volume
   - Assignment is maintained separately from pricing
   - The system computes Amount Payable = (Customer's tier price) × (Quantity ordered)

3. **Price confirmation triggers netting:**
   - When Operations confirms prices for a cycle:
     1. System computes Amount Payable per customer per product
     2. System compares Total Payments (received so far) vs Amount Payable
     3. System computes Overpayment (+) or Short Payment (-)
     4. System updates cumulative running balance
     5. Payments move from "unapplied" to "applied"
   - If prices are confirmed mid-cycle, only completed payments to date are netted

4. **Late price confirmation is handled, not blocked:**
   - Mich can enter payments and issue ARs at any time — no price dependency
   - The system notifies Mich when prices are confirmed (replaces Viber/FB)
   - Until prices are confirmed, the customer's cycle status shows "Awaiting Pricing"
   - After prices are confirmed, status updates to "OK" or "FOR RECON"

5. **Historical tracking:**
   - All price snapshots are retained for audit
   - The system can reconstruct the price at any point in time for any customer
   - If a price correction is needed, it applies to the NEXT cycle (not retroactively)

---

## Consequences

### Positive
- Removes the price bottleneck — Mich never waits for prices to enter payments
- Cash is recorded immediately (accurate cash position at all times)
- Price confirmation is a separate, asynchronous event
- Auto-computes overpayments and short payments at price confirmation time
- Price history enables analytics and margin analysis

### Negative
- Customers won't know their exact balance until prices are confirmed
- "Awaiting Pricing" status needs clear communication to stakeholders
- Mid-cycle price changes require manual reconciliation (price applies to next cycle)
- Three tiers × three products × 121 customers = complex data entry if prices vary per customer (currently prices are the same for all in a tier)

### Neutral
- Migration: existing macro already contains 12+ months of price history per cycle
- The system replaces the Viber/FB price notification workflow
- No change to when Operations sets prices — just formalizing the existing process

---

## Data Model

```python
class CyclePrice:
    cycle_label: str
    cycle_start: date
    cycle_end: date

    # Premium (XCS)
    premium_regular: Decimal
    premium_patron: Decimal
    premium_volume: Decimal

    # Regular (REG)
    regular_regular: Decimal
    regular_patron: Decimal
    regular_volume: Decimal

    # Diesel (ADO)
    diesel_regular: Decimal
    diesel_patron: Decimal
    diesel_volume: Decimal

    created_at: datetime
    created_by: str          # Operations user who entered prices
    confirmed: bool          # Confirmed = triggers Amount Payable computation
    confirmed_at: datetime
    confirmed_by: str
```

```python
class Customer:
    code: str                # CDC e.g., "DH1000"
    business_name: str
    owner: str
    address: str
    price_tier: str          # "Regular", "Patron", "Volume"
    segment: str             # "DHPP", "DMIE", "OPS"
    status: str              # "Active", "Inactive"
```

### Price Confirmation Event Flow

```
Entry                                Trigger
─────                                ───────
Mich receives POP                    Record payment, issue AR
  → Payment status: Unapplied
  → Cycle status: Awaiting Pricing

Operations sets prices for cycle     Price Confirmation Event
  → System computes Amount Payable per customer
  → System compares to Total Payments
  → System computes Over/(Short)
  → Payment status: Applied
  → Cycle status: OK or FOR RECON

Cycle closes (Tuesday cutoff)        Cycle Close Event
  → System finalizes cumulative balance
  → Payment status: Netted
  → Generates Collection JE Summary for Accounting
```
