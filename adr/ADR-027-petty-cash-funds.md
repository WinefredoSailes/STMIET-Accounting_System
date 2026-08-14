# ADR-027: Petty Cash Funds

**Status:** Accepted
**Date:** 2026-08-14
**Deciders:** Architecture Team

**References:**
- [ADR-022: P2,500 Threshold Rule](./ADR-022-p2,500-threshold-rule.md) — PCV path for < P2,500
- [ADR-026: Bank Reconciliation Process](./ADR-026-bank-reconciliation-process.md) — PCF & COH as a column in recon

---

## Context

Quibong shadow confirmed the **three PCFs** and the replenishment trigger:

| Fund | Custodian | Department | Primary Expense Types |
|------|-----------|------------|---------------------|
| **PCF-General** | Leaslyn | General/Admin | General office expenses |
| **PCF-Maintenance** | (Treasury) | Maintenance | Repairs & maintenance |
| **PCF-Technical** | Alywin | Technical | Technical allowances, field expenses |

**Replenishment:** Triggered when **85% of fund consumed** (i.e., ~15% remaining). Not calendar-based — threshold-based.

**Confirmed expenses through PCF:** Repairs & maintenance, technical allowances.

**Current pain points:**
1. Walk-in PCF without supporting docs (Che shadow — categorization issues)
2. Three funds tracked separately, possibly in separate Excel sheets
3. Replenishment requires manual aggregation of all PCVs since last replenishment

---

## Decision

Three PCFs modeled as **imprest funds with threshold-based replenishment**.

### Fund Model

```python
class PettyCashFund:
    code: str                    # PCF-GEN, PCF-MAINT, PCF-TECH
    custodian: User              # Leaslyn / Treasury / Alywin
    department: str              # General / Maintenance / Technical
    imprest_amount: Decimal      # Fixed fund ceiling (per fund)
    replenishment_threshold_pct: Decimal   # 0.85
    current_balance: Decimal     # Computed
    last_replenished_at: date

    @property
    def consumed_pct(self) -> Decimal:
        return 1 - (self.current_balance / self.imprest_amount)
```

### PCV Lifecycle

```
1. Requestor submits PCV — must have PART A (purpose, payee, amount) at minimum
2. Custodian approves (fund balance check)
3. Disbursement — cash given, PCF balance decreases
4. Supporting docs required within 7 days (system flags missing)
5. When consumed_pct ≥ 85% → system alerts custodian + Treasury
6. Replenishment batch → all PCVs since last replenishment aggregated
7. Replenishment RFP created (≥ P2,500) → AP approval chain (ADR-020)
8. Expenses categorized at replenishment → batch JE (ADR-022 rules)
```

### Replenishment JE (per existing practice)

```
Dr: [Various Expense Accounts]    batch total by account
    Cr: Cash in Bank - [PCF Account]    total
```

Expenses are categorized at replenishment time — retained from current practice, with system-enforced requirement that each PCV has a category by the time it enters a replenishment batch.

### Threshold Rules

- **Imprest amounts:** TBD per fund — queried from Quibong (not yet provided; defaults from CASH END sheets show PCF & COH combined at PHP 20,000 maintaining balance)
- **85% threshold:** configurable per fund (system parameter, not hardcoded)
- **Partial replenishment:** allowed — replenish to full imprest or to a target

---

## Consequences

### Positive
- Three funds get unified tracking (no more separate sheets)
- 85% trigger automated — no manual monitoring of balance
- Missing receipts flagged after 7 days (fixes "walk-in PCF without docs")
- Replenishment batch automation reduces manual aggregation

### Negative
- Imprest amounts still TBD from Quibong (placeholder for now)
- Requires discipline: PCV must be created BEFORE cash is handed out
- Three custodians means three training touchpoints

### Neutral
- PCF & COH appears as a single column in bank reconciliation (ADR-026) and cash cycle (ADR-028) — the system splits internally by fund
- Physical cash counts of each fund remain operational practice