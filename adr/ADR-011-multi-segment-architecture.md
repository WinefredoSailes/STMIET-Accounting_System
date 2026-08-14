# ADR-011: Multi-Segment Data Architecture

**Status:** Accepted  
**Date:** 2026-07-23  
**Last Updated:** 2026-07-27  
**Deciders:** Architecture Team, Accounting Lead  

**References:** 
- [ADR-003: Segment as First-Class Dimension](./ADR-003-segment-first-class.md) — segment definitions and COA suffix rules
- [ADR-017: Purchase-to-Pay Document Flow](./ADR-017-purchase-to-pay-cycle.md) — AP segment allocation
- [ADR-023: Multi-Segment AP Allocation](./ADR-023-multi-segment-ap-allocation.md) — shared expense allocation

---

## Context

Cashier shadow and AP shadow revealed the business operates **four distinct segments** sharing one cashier (Mich) and one AP clerk (Che) but with separate accounting treatment:

| Segment | Business | Unearned Revenue GL | COA Suffix | Product Types |
|---------|----------|-------------------|-----------|---------------|
| **DHPP** | Distribution & Hauling of Petroleum Products | 21000 | 00 | Fuel (Gasoline, Diesel, Jet Fuel, LPG, Kerosene) |
| **DMIE** | Industrial Equipment / Machinery | 21023 | 03 | TSRO Machines, Dispensers, Tanks, Parts |
| **OPS** | Operations / Services | 21016 | 06 | Calibration, Job Orders, COC Processing |
| **STPC** | Sister Company (Seven-Trent Petroleum Corp.) | 15500 (Due from) | ⚠️ **None** | Intercompany receivables/payables |

**Gap identified in AP shadow:** STPC has no dedicated COA suffix (00/03/06). In RFP templates, STPC transactions use DHPP accounts (suffix 00). This means STPC expenses and payables are not separable from DHPP in the current COA structure. The AP module must handle this with a separate segment tag even when the GL account uses the DHPP suffix.

All segments are tracked in a single MONITORING sheet (AR-BLUE 2026.xlsx), but each has separate GL accounts, product codes, and revenue recognition rules.

The cashier cannot reliably determine segment solely by customer — some customers transact across multiple segments.

---

## Decision

**Adopt a tenant-aware data model with shared cashier interface but isolated accounting per segment.**

1. **Core Entity — `Segment`:**
   - Each segment has its own prefix (DHPP, DMIE, OPS)
   - Each segment owns its Chart of Accounts, Product Catalog, and Customer relationships
   - Default GL accounts are configured per segment (e.g., Unearned Revenue account is segment-specific)

2. **Collection Entry requires segment selection:**
   - When Mich posts a payment, she selects the segment first
   - The system filters available products, GL accounts, and customer codes based on segment
   - If a customer exists in multiple segments, a separate customer record exists per segment (linked by a master customer ID)

3. **Intercompany transactions:**
   - STPC is modeled as both a customer (for fuel purchases) and an intercompany counterparty
   - Due from STPC (15500) and Due to STPC are tracked as sub-ledger accounts within the DHPP segment
   - Intercompany reconciliations are reported separately

4. **Reporting:**
   - Financial reports can be filtered by segment or consolidated
   - MONITORING sheet equivalent shows all segments in a unified view (as Mich does today)

---

## Consequences

### Positive
- Clear separation of concerns — each segment's accounting is independently verifiable
- Cashier workflow unchanged: she already knows which segment each transaction belongs to
- Future segments can be added without modifying existing ones
- Revenue recognition rules are segment-specific and enforceable by the system

### Negative
- A customer transacting across segments has separate ledgers per segment
- Segment selection is an extra click/field during data entry
- Intercompany transactions require double-entry across segments (both Dr and Cr)

### Neutral
- GL account numbers (21000, 21023, 21016) are embedded in the system as defaults per segment
- Product code ranges must be enforced (1xx=DHPP, 2xxx=DMIE, 7xx=OPS)

---

## Options Considered

| Option | Pros | Cons |
|--------|------|------|
| **Single flat CoA** (rejected) | Simpler data model | Breaks existing accounting; segments already use different GLs; cannot report per-segment P&L |
| **Completely separate databases** (rejected) | Strongest isolation | Mich needs unified view; intercompany reconciliation becomes manual; over-engineered |
| **Tenant-aware with shared ledger** (selected) | Balances isolation with unified cashier view | Requires segment field on every transaction; training needed |

---

## Key Implementation Details

```python
class Segment:
    id: str          # "DHPP", "DMIE", "OPS"
    name: str
    default_uneamed_revenue_gl: str

class Transaction:
    segment: Segment
    date: date
    customer: Customer
    product: Product
    amount: Decimal
    dr_account: GLAccount      # Bank account
    cr_account: GLAccount      # Unearned Revenue / Revenue
    ar_number: str             # Pre-numbered Acknowledgment Receipt
    po_number: str
    bank_code: str
    payment_reference: str
```
