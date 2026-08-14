# ADR-023: Multi-Segment AP Allocation

**Status:** Accepted  
**Date:** 2026-07-27  
**Deciders:** Architecture Team  

**References:**
- [ADR-003: Segment as First-Class Dimension](./ADR-003-segment-first-class.md) — segment awareness
- [ADR-011: Multi-Segment Data Architecture](./ADR-011-multi-segment-architecture.md) — segment definitions
- [ADR-018: RFP Document Model](./ADR-018-rfp-document-model.md) — RFP has segment field

---

## Context

AP shadow confirmed that expenses must be allocated across segments. The RFP template includes a **segment column**, and shared expenses (salaries, utilities, rent, admin costs) are split across DHPP, DMIE, and OPS.

### What We Know

1. **Direct expenses** — assigned to a single segment (e.g., STPC Fuel RFP → DHPP)
2. **Shared expenses** — must be allocated (e.g., salaries, electricity, rent, water)
3. **RFP segment field** — each RFP has a segment tag
4. **COA suffix** — 00=DHPP, 03=DMIE, 06=OPS determines which GL account is debited
5. **STPC gap** — STPC has no dedicated suffix; uses DHPP accounts

### What We Don't Know Yet (Awaits Alywin)

- **Allocation basis** — is it equal split? Revenue-based? Headcount-based? Vehicle count-based?
- **Who determines** the allocation percentages per expense type
- **When** allocation is applied (at RFP creation or at period-end)
- **Reversal/reallocation** — can allocation be changed after posting?

---

## Decision

Multi-segment allocation for AP is implemented as follows:

### Allocation Types

| Type | Description | Example |
|------|-------------|---------|
| **Direct** | Expense belongs to one segment only | STPC Fuel → DHPP |
| **Split** | Expense allocated at RFP creation by percentage | Salary: 50% DHPP, 30% DMIE, 20% OPS |
| **Periodic** | Allocated at period-end based on formula | Rent: equal split across active segments |

### RFP-Level Allocation

For split RFPs, the RFP form allows multiple charge-to lines:

```
RFP #A0025 — Salary (CNR Short Term Loan)
    Line 1: Dr 6100-00 EXP - Salaries (DHPP)        P 5,000.00  (50%)
    Line 2: Dr 6100-03 EXP - Salaries (DMIE)        P 3,000.00  (30%)
    Line 3: Dr 6100-06 EXP - Salaries (OPS)          P 2,000.00  (20%)
        Cr: Advances to Employees - Current          P 20,000.00
        Cr: AP - CNR                                  P (total - 20,000)  → P 0.00 here
```

Canonical balancing formula per REVIEW-ISSUES-RESOLUTIONS.md #5: Debit total (sum of segment lines) = Advances 20,000 + AP (total − 20,000). If the total is less than P20,000, the AP side is zero and the Advances credit is capped at total (overflow handled via liquidation); example above uses a P10,000 total with the cash variant where the standing credit is capped.

Each line specifies:
- COA account (with segment suffix)
- Amount
- Segment (derived from COA suffix)

### Default Allocation Templates

For recurring shared expenses, the system supports allocation templates:

| Expense Type | Default Allocation | Basis |
|-------------|-------------------|-------|
| Salaries (admin) | 50/30/20 DHPP/DMIE/OPS | TBD from Alywin |
| Electricity | Equal split | TBD |
| Water | Equal split | TBD |
| Telephone/Internet | 100% DHPP | TBD |
| Rent | Equal split | TBD |
| Office Supplies | 100% DHPP | TBD |

### Data Model

```python
class RFPLine:
    rfp: RFP
    account: Account          # Full COA account with segment suffix
    amount: Decimal
    segment: Segment          # Derived from account code suffix
    
class AllocationTemplate:
    name: str                 # e.g., "Admin Salaries Split"
    lines: List[AllocationTemplateLine]
    
class AllocationTemplateLine:
    template: AllocationTemplate
    account: Account
    percentage: Decimal       # e.g., 50.00 = 50%
    segment: Segment
```

---

## Consequences

### Positive
- Direct and split expenses handled uniformly
- Allocation templates reduce repetitive data entry for recurring expenses
- Segment-specific GL accounts ensure correct FS reporting per segment

### Negative
- Allocation percentages are TBD — need Alywin's input
- Wrong allocation templates could misstate segment P&L
- RFP with 3+ allocation lines is more complex to create

### Neutral
- Allocation templates are configurable, not hardcoded
- STPC uses DHPP suffix (00) but its own segment tag — reports must handle this mapping
- Periodic allocations (rent, etc.) may be done as adjusting JEs rather than at RFP creation
