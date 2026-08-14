# ADR-028: Weekly Cash Cycle Model

**Status:** Accepted
**Date:** 2026-08-14
**Deciders:** Architecture Team

**References:**
- [ADR-013: Cycle-Based Ledger](./ADR-013-cycle-based-ledger.md) — Tue-Mon cycle as AR grouping unit
- [ADR-026: Bank Reconciliation Process](./ADR-026-bank-reconciliation-process.md) — recon per bank
- [ADR-029: COLLECTIBLES Settlement](./ADR-029-collectibles-settlement.md) — two-department reconciliation
- [ADR-031: Cash Flow Statement Generation](./ADR-031-cash-flow-statement-generation.md) — cycle → month rollup

---

## Context

The `SUMMARY OF CASH JANUARY 2026.xlsx` weekly sheets document the exact per-cycle cash model. Five cycles in January: `JAN 01-05`, `JAN 06-12`, `JAN 13-19`, `JAN 20-26`, `JAN 27-31` (year-end cycle truncated).

### Cycle Sheet Structure (CASH FOR THE CYCLE)

**11 columns:** PNB, PSBC-S, PSBC-C, KB, 1VB, BDO, MBTC, RCBC, CHINA BANK, E.TAN/STPC, PCF & COH

**Per-bank vertical flow:**
```
Beg. Balances (cycle start)
Less: ADB / Maintaining           (PNB 50k, MBTC 50k, others 5k, PCF&COH 20k, E.TAN 0)
= Available Cash in Bank
Add: Deposits                     (sum of collections per bank)
Less: Checks Issued / Withdrawals
= Available Cash, End
Add: ADB / Maintaining            (restored for reporting)
= TOTAL CASH
```

**Activity rows (cycle breakdown):**

| Activity Row | Source Domain |
|--------------|--------------|
| Collections from Distribution | AR (Mich) |
| Other Cash Collections | AR (misc) |
| Funds Borrowed from other accounts | CASH SHORT / inter-account (ADR-030) |
| Payments to Supplier of Petroleum | AP / Fuel procurement |
| RFP of Accounts Payable [incl. loans] | AP (Che RFP batch) |
| Disbursement for CAPEX | Fixed Assets |
| Cash Withdrawn for PCF Replenishment | PCF (ADR-027) |
| Inter-account fund transfer | CASH SHORT (ADR-030) |
| Other Cash payments | Misc |
| Checks Cleared for Loan / Fuel | Financing (loans) |

Each row carries a per-bank amount; the GRAND TOTAL column sums the cycle.

**Reconciliation check:** per-bank `TOTAL` row = `ENDING - BEGINNING`, and `T-ENDING` matches `ENDING` (variance row ~0, e.g., `-1.11e-10` — floating point noise).

---

## Decision

The weekly cycle is modeled as a **first-class cash dimension** alongside the GL period.

### Cycle Model

```python
class CashCycle:
    code: str                  # "JAN 06-12 2026"
    start_date: date           # Tuesday
    end_date: date             # Monday
    is_closed: bool            # Cycle ends production postings

class CycleBankLine:           # One row per bank per cycle
    cycle: CashCycle
    bank: BankCode             # 11 values incl. PCF&COH
    beginning_balance: Decimal
    adb_maintaining: Decimal   # Per bank (configurable)
    deposits: Decimal          # Computed from AR collections
    checks_issued: Decimal     # Computed from AP/CV disbursements
    ending_balance: Decimal    # Computed
    total_cash: Decimal        # ending + ADB

class CycleActivityLine:       # Activity rows (per bank or per bank×type)
    cycle: CashCycle
    bank: BankCode
    activity_type: str         # COLLECTION_DIST / OTHER_COLLECTION / BORROWED /
                               # SUPPLIER_PAYMENT / RFP_AP / CAPEX / PCF_REPLEN /
                               # INTERACCT_TRANSFER / OTHER_PAYMENT / LOAN_CLEARED
    amount: Decimal
```

### Derivation Rules

| Activity | Computed From |
|----------|--------------|
| Collections from Distribution | Sum of Mich's collections per bank in cycle (ADR-013) |
| Payments to Supplier of Petroleum | AP supplier payments per bank in cycle |
| RFP of AP | Approved RFP postings in cycle |
| Checks Cleared for Loans | Check release records (Quibong) |
| Funds Borrowed / Inter-account transfer | ADR-030 transfers in cycle |

The activity rows are **derived from posted transactions**, not re-entered. The cycle sheet is a **report**, not a data-entry form. Beginning/ending balances are computed from bank transaction register + recon.

### Cycle Closure

- Cycles close per GL period rules (weekly cycle ≠ fiscal period; multiple cycles per month)
- Closed cycle = read-only; corrections via reversal (ADR-005)
- Month-end close operates on the set of cycles in the month

---

## Consequences

### Positive
- Weekly cash visibility per bank (matches current practice exactly)
- Elimination of manual re-entry — cycle sheet generated from transactions
- Variances become visible immediately (ending mismatch = system flags)
- Rolling 12 cycles per year → strong cash trend analytics

### Negative
- Weekly cycle adds a dimension most accounting software lacks (see ADR-025 matrix — QB scores Weak here)
- Requires bank-column discipline on all collections/payments (already exists in practice)

### Neutral
- ADB/maintaining balances remain configured per bank (PNB/MBTC 50k, others 5k — changes configurable)
- E.TAN/STPC column is effectively intercompany (0 balances in Jan cycles shown)