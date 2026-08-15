# ADR-034: Fixed Assets

**Status:** Accepted
**Date:** 2026-08-15
**Deciders:** Architecture Team

**References:**
- [POSTING_RULES §9](../POSTING_RULES.md) — asset acquisition / depreciation / disposal JE templates
- [ADR-003: Segment-First Chart](./ADR-003-segment-first-chart.md) — segment-suffixed asset accounts
- [ADR-011: Multi-Segment Data Architecture](./ADR-011-multi-segment-architecture.md) — per-segment asset registers
- [ADR-004: Immutable Journal](./ADR-004-immutable-journal.md) — depreciation JEs are append-only
- [BUILD-PLAN Phase 7](../BUILD-PLAN.md) — asset register, SL depreciation, disposal, Asset↔Vehicle link

---

## Context

Fixed assets (tankers, boom trucks, office vehicles, building, furniture,
office equipment) are booked on the COA under `17000-19966`, with accumulated
depreciation and disposal income accounts per segment (`43070-43096`).
Current state is manual: no register, no depreciation engine, and Alywin has
flagged the **fully-depreciated-still-in-use** case (a vehicle still on the
road after its book life) as a recurring pain.

**Per-category lives (from BUILD-PLAN Phase 7):**

| Category | Useful Life | Primary Segment |
|----------|-------------|-----------------|
| Fuel Tankers | 10-15 y | DHPP (`17010`) |
| Boom Trucks | 10 y | DMIE (`18503`) |
| Office Vehicles | 5-7 y | DHPP (`18600`) |
| Building / Building Improvements | 15-20 y | DHPP (`19700-19750`) |
| Furniture & Fixtures | 5 y | DHPP (`19800`) |
| Office Equipment | 3-5 y | DHPP (`19900-19966`) |

**Posting contracts (POSTING_RULES §9):**

```
9.1 Acquisition   Dr 17xxx-19xxx Asset Account    {cost}
                     Cr 200xx AP / 100xx Cash / 270xx Loans  {cost}
9.2 Depreciation  Dr 50110/51173/616xx Dep Exp   {amount}
                     Cr 17xxx Accumulated Depreciation       {amount}
9.3 Disposal      Dr 100xx Cash (proceeds)       {proceeds}
                  Dr 17xxx Accumulated Dep       {accum_dep}
                     Cr 17xxx Asset Account                  {cost}
                     Cr 43070-43096 Income from Disposal     {gain}
                  (or Dr 6xxx Other Expense {loss} when proceeds < NBV)
```

---

## Decision

Fixed assets are a **self-contained Phase 7 bounded context** (`apps.assets`)
with an asset register, straight-line depreciation engine, and disposal —
all posting through the immutable journal (ADR-004) and the shared
PostingService (ΣDr=ΣCr enforced, ADR-002).

### Data Model

```python
class AssetCategory:
    code: str                     # TANKER, BOOM_TRUCK, VEHICLE, ...
    useful_life_years: int
    asset_account: Account        # default 17xxx-19xxx
    depreciation_expense_account: Account   # 50110/51173/616xx
    accumulated_dep_account: Account        # 17xxx
    segment: Segment | None       # segment-specific defaults

class Asset:
    asset_no: str                 # FA-YYYY-####
    category: AssetCategory
    segment: Segment
    acquisition_date: date
    cost, residual_value: Decimal
    asset_account / dep_exp / accum_dep: Account   # resolved from category, overridable
    funding_source: str           # ap / cash / loan
    financed_loan_reference: str
    acquisition_fees: Decimal
    acquisition_journal: JournalEntry
    status: active / fully_depreciated / disposed
    vehicle: Vehicle | None       # Asset↔Vehicle link (vehicles ARE assets)

    @property depreciable_base  = cost - residual_value
    @property monthly_depreciation = depreciable_base / (life * 12)
    @property accumulated_depreciation = Σ posted schedule rows
    @property net_book_value = cost - accumulated_depreciation

class DepreciationSchedule:
    asset, period_start, period_end, amount
    journal_entry, status: pending / posted
    is_still_in_use: bool         # fully-depreciated-still-in-use flag
    unique (asset, period_start)

class AssetDisposal:
    asset, disposal_date, proceeds, reason, gain
    journal_entry, status: draft / posted
```

### Derivation Rules

| Operation | Rule |
|-----------|------|
| Acquisition JE | `Dr Asset {cost + fees} | Cr funding source` (funding = AP / Cash / Loans per segment) |
| Schedule build | Idempotent: month rows from acquisition to end of useful life; re-run adds no duplicates |
| Depreciation JE | One per month: `Dr dep_exp {amount} | Cr accum_dep {amount}`; idempotent per (asset, period_start) |
| Fully depreciated | When accumulated ≥ depreciable base: status → `fully_depreciated`, `is_still_in_use = True` |
| Disposal | `Dr Cash + Dr Accum Dep | Cr Asset + Cr Gain`; when proceeds < NBV the gain line becomes `Dr 6xxx Loss` |
| Asset↔Vehicle | `Asset.vehicle` OneToOne → fleet.Vehicle; vehicles are the assets 17000-18650 |

### Posting Notes

- Depreciation is straight-line, monthly, 2dp half-up (apps.core.money).
- Every depreciation row links its JE; corrections follow ADR-004 reversal,
  never edit of a posted entry.
- Acquisition/disposal amounts follow the ADR-033 approval gate: JEs above
  `JE_APPROVAL_THRESHOLD` require approval before posting.

---

## Consequences

### Positive
- Full asset register with per-category lives replaces the manual tracking
- Depreciation engine removes hand-computed monthly JE batches
- Fully-depreciated-still-in-use assets stay visible (Alywin's pain solved)
- Disposal computes gain/loss automatically with the correct JE template
- Vehicles link directly to assets, so the fleet register and the books agree

### Negative
- Straight-line only in v1; declining-balance and units-of-production need
  a later extension of DepreciationMethod
- Residual-value conventions per category must be confirmed with Alywin during
  data migration (default 0)
- Disposal JE requires a loss account decision: current default is 62000/62003
  (Impairment Loss); a dedicated "Loss on Disposal" account may be added to
  the COA if management prefers (REVIEW-ISSUES register).

### Neutral
- Accumulated depreciation accounts beyond `18513` (Boom Trucks) are not yet
  present in the 392-account COA; the engine resolves whatever account code
  the category configures, so migration can add segment-specific accum accounts.
- Depreciation cadence is monthly regardless of weekly cycles (ADR-013 cycles
  affect AR/AP; depreciation is a period-level event).
