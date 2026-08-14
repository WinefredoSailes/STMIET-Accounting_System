# ADR-031: Cash Flow Statement Generation

**Status:** Accepted
**Date:** 2026-08-14
**Deciders:** Architecture Team

**References:**
- [ADR-028: Weekly Cash Cycle Model](./ADR-028-weekly-cash-cycle-model.md) — cycle data
- [ADR-029: COLLECTIBLES Settlement](./ADR-029-collectibles-settlement.md) — deposits/outflows
- [STATEMENT-OF-CASH-FLOW.xlsx](../excel-files/STATEMENT-OF-CASH-FLOW.xlsx) — template

---

## Context

The `CF` sheet (SUMMARY OF CASH JANUARY 2026.xlsx) shows the monthly cash flow statement structure:

```
CASH FLOWS ARISING FROM OPERATING ACTIVITIES
  Collections from Distribution          42,043,027.00
  Other Cash Collections related         673,859.57
  Payments to Supplier of Petroleum      -40,872,400.00
  RFP of Accounts Payable [incl]         -1,425,020.45
  Cash Withdrawn for PCF Replenishment   -66,223.25
  Other Cash payments relating           -461,000.10
  Net cash flows provided by operations  -107,757.23

CASH FLOWS FROM INVESTING ACTIVITIES
  Purchase of Property, Plant & Equipment -3,040.00
  Net cash flows used in investing        -3,040.00

CASH FLOWS ARISING FROM FINANCING ACTIVITIES
  Funds Borrowed from other accounts      3,517,300.00
  Checks Cleared for Loan / Fuel         -4,348,194.73
  Net cash flows used in financing        -830,894.73

NET INCREASE / (DECREASE) IN CASH        -941,691.96
Add: CASH AT THE BEGINNING OF MONTH      2,412,842.54
Less: ADB, Maintaining Balance           -155,000.00
CASH AVAILABLE AT THE END OF MONTH       1,316,150.58
```

**Source:** The CF sheet aggregates the 5 weekly cycle sheets. January 2026: 42M+ collections, 40.8M supplier payments across the month.

---

## Decision

The Cash Flow Statement is a **derived report** — generated from posted cycle data, never manually typed.

### Mapping: Cycle Activities → CF Sections

| CF Section | Source Cycle Activity (ADR-028) | Formula |
|-----------|--------------------------------|---------|
| Collections from Distribution | `COLLECTION_DIST` | Σ per bank per cycle in month |
| Other Cash Collections | `OTHER_COLLECTION` | Σ |
| Payments to Supplier of Petroleum | `SUPPLIER_PAYMENT` | Σ |
| RFP of Accounts Payable | `RFP_AP` | Σ |
| Cash Withdrawn for PCF Replenishment | `PCF_REPLEN` | Σ |
| Other Cash payments | `OTHER_PAYMENT` | Σ |
| Purchase of PP&E | `CAPEX` | Σ |
| Funds Borrowed from other accounts | `BORROWED` | Σ (financing) |
| Checks Cleared for Loan / Fuel | `LOAN_CLEAR` | Σ (financing) |
| Inter-account transfers | `INTERACCT_TRANSFER` | **Excluded** (cash-to-cash, no P&L) |

### Period Rollup

```
Monthly CF = Σ weekly cycles in the calendar month
Test: NET INCREASE = Ending cash − Beginning cash + ADB adjustments (variance ~0)
```

### Weekly → Monthly Precision

- Standard monthly CF sums the weeks' totals
- The net-cash identity must hold: `Net increase = End cash − Beg cash − ADB restored` (January CF shows exactly this: -941,691.96 = 1,316,150.58 − 2,412,842.54 + 155,000 ✓)

### Reporting Cadence

- **Weekly:** cycle sheet (per-bank detail, ADR-028)
- **Monthly:** CF statement (template match)
- **Quarterly/Annual:** same mapping, longer window

---

## Consequences

### Positive
- CF statement is a pure derived report — zero manual effort
- Identity tests catch data errors automatically (net-cash identity per month)
- Weekly cash visibility feeds management decisions (Quibong currently produces manually)

### Negative
- Requires all cycles in the period to be closed before the month CF is trustworthy
- Classification of a transaction to the correct activity row is essential (data entry discipline)

### Neutral
- 8 cash flow categories from the template map 1:1 to cycle activity rows
- Inter-account transfers excluded from CF (correct per accounting standard: no impact on net cash)
- ADB/maintaining balances are a reporting adjustment, not a real cash outflow