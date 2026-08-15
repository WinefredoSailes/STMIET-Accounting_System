# ADR-035: Financial Statements & Reporting

**Status:** Accepted
**Date:** 2026-08-15
**Deciders:** Architecture Team

**References:**
- [ADR-005: General Ledger Projection](../adr/ADR-005-general-ledger-projection.md) — TB is recomputed from posted GL, never a stored source of truth
- [ADR-004: Immutable Journal](../adr/ADR-004-immutable-journal.md) — statements are derived from posted entries only
- [ADR-013: Fiscal Calendar & Cycles](../adr/ADR-013-fiscal-calendar-and-cycles.md) — period windows (activity / opening / ending)
- [ADR-031: Cash Flow Statement Generation](../adr/ADR-031-cash-flow-statement-generation.md) — CF is handled separately by an indirect-method engine
- [BUILD-PLAN Phase 8](../BUILD-PLAN.md) — the six workbook statement layouts

---

## Context

STMIET produces five periodic statements from posted GL data — Income
Statement (MARCH layout), Statement of Financial Position (YEAR END),
Statement of Cost of Sales, Statement of Total Expenses (CGSE), and
Statement of Changes in Equity — each with per-segment columns (DHPP / DMIE
/ OPS) plus a GRAND TOTAL. A sixth statement (Cash Flow) is covered by the
ADR-031 engine, so the reporting module seeds five templates.

Today these are built by hand in Excel. The goal is to reproduce the
workbook layouts exactly, from posted journal data only (ADR-004), so that
"the month-end pack" is one click from the GL with no manual transcription.

### Workbook requirements distilled

| Statement | Window | Notes |
|-----------|--------|-------|
| Income Statement | period activity | GPM / Expense Ratio / NPM metrics; 10% R&M, 10% Tithing, 80% remaining appropriations |
| Statement of Financial Position | ending balances | Assets == Liabilities + Equity identity; Debt & Current ratios |
| Statement of Cost of Sales | period activity | DHPP (12 lines) / DMIE (18) / OPS (5) + liters quantities |
| Statement of Total Expenses | period activity | COGS + operating + non-operating (CGSE) |
| Statement of Changes in Equity | opening + activity | Beginning → +Additional + Net Profit − Drawings = Ending |

---

## Decision

Reporting is a **self-contained Phase 8 bounded context** (`apps.reporting`).
Statement layouts are **configuration, not code**: each template is a
`StatementTemplate` with ordered `StatementLineDef` rows that know how to
aggregate accounts (`account_codes` exact match, `account_prefixes` prefix
match), which balance window to use, and how to combine children (sum /
difference / ratio / percent). The generator runs a template against the GL
and persists a JSON snapshot (`FinancialStatement`).

### Data Model

```python
class StatementType(TextChoices):
    TB = "tb"; IS = "is"; SFP = "sfp"
    COS = "cos"; TE = "te"; SOCE = "soce"; CF = "cf"

class StatementLineMode(TextChoices):
    ACCOUNT, SUM, DIFFERENCE, RATIO, PERCENT, QUANTITY, INPUT

class BalanceBasis(TextChoices):
    ACTIVITY      # period activity window
    OPENING       # balance before the period
    ENDING        # balance at period end

class StatementTemplate:
    statement_type: unique
    name, description

class StatementLineDef:                       # unique (template, line_no)
    template: FK, line_no, key, title
    mode: StatementLineMode
    balance_basis: BalanceBasis = ACTIVITY
    account_codes: JSON[list]                 # exact codes
    account_prefixes: JSON[list]              # prefix matches
    sign: Decimal = 1                         # contra handling
    parent: FK self (null)                    # SUM children tree
    left_ref / right_ref: str                 # for DIFFERENCE / RATIO / PERCENT
    weight: Decimal                           # PERCENT multiplier
    is_subtotal / is_section / is_hidden: bool

class FinancialStatement:
    statement_type, company, segment: null    # None = all segments
    period_start, period_end: date
    data: JSON                                # [ {key, title, line_no, mode,
                                              #   is_subtotal, is_section, is_hidden,
                                              #   amounts: {DHPP|DMIE|OPS|GRAND: str}} ]
    identity_ok: bool, identity_note: str
    status: draft / final
    generated_at, created_by

class MonthEndClose:
    fiscal_period: OneToOne, company
    steps: JSON                               # {accruals|recon|close|appropriations: pending|in_progress|done}
    status: open / closed, closed_by, closed_at
    @property is_ready                        # all steps done
```

### Computation Rules

1. **Windows (ADR-013):** `activity` = GL with `start..end`; `opening` =
   GL with `end` before `period_start`; `ending` = GL through `period_end`.
   A line's `balance_basis` selects which window it reads.
2. **Signing (ADR-005):** balances are signed by each account's normal
   balance (debit-normal → Dr−Cr, credit-normal → Cr−Dr) so all normal
   balances read positive; contra accounts carry `sign=-1` or net as
   `gross − accumulated` DIFFERENCE rows.
3. **Columns:** every row emits DHPP / DMIE / OPS columns plus `GRAND` =
   Σ segments. `INPUT` rows accept per-segment or scalar values (e.g. IS
   net profit fed into SFP `eq_net_profit` and SOCE `soce_net_profit`);
   an `INPUT` with `left_ref` defaults to that computed row (e.g.
   `app_basis` defaults to `net_profit`).
4. **SUM** reads children via `parent`; **DIFFERENCE** = `left − right`;
   **RATIO** = `left/right×100` (metrics, GPM, ratios); **PERCENT** =
   `left × weight` (10/10/80 appropriations).
5. **Identity checks** are computed at generation time:
   - SFP: `total_assets == total_liab_equity`
   - SOCE: `ending == total − drawings`
   `identity_ok` is stored on the snapshot and exposed to the API.
6. **Idempotence:** `generate()` uses `update_or_create` keyed on
   (statement_type, company, segment, period_start, period_end), so re-runs
   refresh the snapshot instead of duplicating rows.

### Month-End Close

Close order is fixed: **accruals → recon → close → appropriations**. Each
step moves from `pending` to `done` and advances the next to `in_progress`.
`complete()` rejects while any step is pending and, on success, flips the
`FiscalPeriod.is_closed` flag — locking the period so no back-posting is
possible (posting §17).

---

## Consequences

### Positive
- The six statements are regenerable from posted GL at any time — no manual
  transcription; the pack is always reproducible and auditable.
- Layouts are data (`StatementLineDef`), so adjusting a workbook row is an
  admin change, not a code change.
- Per-segment columns + GRAND match the workbook exactly.
- SFP and SOCE identities are machine-checked at generation time, catching
  posting errors before the pack goes out.
- Month-end close gives a hard gate that enforces no back-posting.

### Negative
- Statements are only as good as the seeded templates; new account codes
  outside a line's `account_codes`/`account_prefixes` are invisible until the
  template is updated (prefix coverage is the mitigation).
- `INPUT` rows (`eq_net_profit`, `soce_net_profit`) require the caller to
  chain IS → SFP/SOCE in the right order; the API `run_all` action does this
  automatically.
- CF is not seeded here (per ADR-031); the two engines must agree on the
  same posted-GL basis.

### Neutral
- Quantity rows (liters in CoS) accept external `quantities` inputs; the
  volume feed source (metered dispatch) is a later phase concern.
- Only one template per statement type is seeded today; the model allows
  versioned variants (e.g. monthly vs annual layouts) without schema change.
