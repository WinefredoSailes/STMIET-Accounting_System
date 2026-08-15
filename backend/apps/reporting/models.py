"""Financial Statement reporting bounded context (BUILD-PLAN Phase 8).

Reproduces the six workbook templates exactly from posted GL data:

  - Income Statement (IS MARCH 2026): per-segment columns + GRAND TOTAL,
    GPM / Expense Ratio / NPM, and the 10% R&M / 10% Tithing appropriations.
  - Statement of Financial Position (YEAR END): current/NC split, ratios,
    capital = Assets - Liabilities.
  - Statement of Cost of Sales: DHPP 12 lines / DMIE 18 / OPS 5 + liters.
  - Statement of Total Expenses (CGSE): COGS + operating + non-operating.
  - Statement of Changes in Equity (SOCE).
  - Cash Flow Statement: reused from apps.cash.CashFlowService (ADR-031).

Statements are derived reports, never hand-edited. StatementTemplates are
config (stored, not hardcoded — ADR-004 style): each StatementLineDef maps a
COA account prefix range (or a formula over sibling lines) to one statement
row. FinancialStatement persists a generated snapshot (JSON rows + identity
flag) so a statement can be versioned and audited against the posted GL.
"""

from decimal import Decimal

from django.db import models

from apps.core.models import AuditableModel


class StatementType(models.TextChoices):
    TRIAL_BALANCE = "tb", "Trial Balance"
    INCOME_STATEMENT = "is", "Income Statement"
    BALANCE_SHEET = "sfp", "Statement of Financial Position"
    COST_OF_SALES = "cos", "Statement of Cost of Sales"
    TOTAL_EXPENSES = "te", "Statement of Total Expenses"
    SOCE = "soce", "Statement of Changes in Equity"
    CASH_FLOW = "cf", "Cash Flow Statement"


class StatementLineMode(models.TextChoices):
    # Sum of posted balances for the accounts whose code is in account_codes
    # or starts with any prefix in account_prefixes (sign-adjusted by the
    # account's normal balance: debit-normal and credit-normal both come out
    # positive, then multiplied by `sign`).
    ACCOUNT = "account", "Sum of accounts by code/prefix"
    # Subtotal of child lines (all line defs with parent=this row).
    SUM = "sum", "Sum of child lines"
    # left_ref - right_ref (e.g. Gross Profit = Net Sales - COGS).
    DIFFERENCE = "difference", "Difference of two lines"
    # Ratio of left_ref / right_ref expressed as percent (metrics).
    RATIO = "ratio", "Ratio of two lines (percent)"
    # Fixed percent of the base line (appropriations: 10% of net income).
    PERCENT = "percent", "Fixed percent of the base line"
    # Quantity field carried verbatim (liters) — supplied, not computed.
    QUANTITY = "quantity", "Quantity (liters)"
    # Value injected by the caller (e.g. IS net profit fed into SOCE).
    INPUT = "input", "Value injected by the caller"


class BalanceBasis(models.TextChoices):
    # GL rows within [period_start, period_end] (income statement, CoS, TE).
    ACTIVITY = "activity", "Period activity"
    # GL rows strictly before period_start (SOCE beginning capital).
    OPENING = "opening", "Opening balance (before period)"
    # GL rows through period_end (statement of financial position).
    ENDING = "ending", "Ending balance (through period end)"


class StatementTemplate(AuditableModel):
    """One financial statement layout (mirrors the workbook template)."""

    statement_type = models.CharField(
        max_length=8, choices=StatementType.choices, unique=True
    )
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["statement_type"]

    def __str__(self):
        return f"{self.get_statement_type_display()} ({self.name})"


class StatementLineDef(models.Model):
    """One row of a statement template: how its value is computed.

    Modes:
      - account:    SUM over the matching GL accounts for the period, signed
                    by each account's normal balance, then multiplied by
                    `sign` (+1/-1, used for contra accounts such as sales
                    discounts or accumulated depreciation). Matching = exact
                    code in account_codes OR code startswith a prefix in
                    account_prefixes.
      - sum:        total of all child lines (parent=this row).
      - difference: line[left_ref] - line[right_ref].
      - ratio:      line[left_ref] / line[right_ref] * 100 (metrics).
      - percent:    base line (left_ref) * weight (appropriations).
      - quantity:   a supplied amount placed into the row verbatim (liters).

    Every row is computed per segment column (DHPP / DMIE / OPS) plus GRAND
    TOTAL, so one template reproduces the workbook's segment-column layout.
    """

    template = models.ForeignKey(
        StatementTemplate, on_delete=models.PROTECT, related_name="lines"
    )
    line_no = models.PositiveIntegerField()
    key = models.CharField(max_length=64)  # machine key, e.g. "gross_profit"
    title = models.CharField(max_length=255)
    mode = models.CharField(max_length=16, choices=StatementLineMode.choices)
    # ACCOUNT mode only: which GL window to sum over (ADR-013 period rules).
    balance_basis = models.CharField(
        max_length=16, choices=BalanceBasis.choices, default=BalanceBasis.ACTIVITY
    )
    # ACCOUNT mode: exact COA codes and/or code prefixes to aggregate.
    account_codes = models.JSONField(default=list)
    account_prefixes = models.JSONField(default=list)
    # +1 (adds) or -1 (reverses the normal-balance sign, e.g. contra lines).
    sign = models.DecimalField(
        max_digits=2, decimal_places=0, default=Decimal("1")
    )
    # SUM mode: parent line (is_subtotal=True) that sums its children.
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    is_subtotal = models.BooleanField(default=False)
    is_section = models.BooleanField(default=False)
    # Operand-only rows used by difference/percent formulas but not displayed
    # (e.g. the gross and accumulated-depreciation legs of a "net" line).
    is_hidden = models.BooleanField(default=False)
    # formula refs: left_ref (minuend / numerator / base) and right_ref
    # (subtrahend / denominator).
    left_ref = models.CharField(max_length=64, blank=True)
    right_ref = models.CharField(max_length=64, blank=True)
    weight = models.DecimalField(
        max_digits=8, decimal_places=4, default=Decimal("0.0000")
    )

    class Meta:
        ordering = ["template", "line_no"]
        unique_together = ("template", "line_no")

    def __str__(self):
        return f"{self.template.get_statement_type_display()} L{self.line_no} {self.title}"


class FinancialStatement(AuditableModel):
    """A generated statement snapshot for a period (optionally per segment).

    `data` stores the computed rows (JSON) exactly as served to the UI:
        [
          {"key": "sales", "title": "Sales", "line_no": 1,
           "amounts": {"DHPP": "0.00", "DMIE": "0.00", "OPS": "0.00",
                       "GRAND": "0.00"}, "is_subtotal": false, ...},
          ...
        ]
    `identity_ok` records whether the statement's balancing identities hold
    (SFP: Assets == Liabilities + Equity; IS: GPM/Expense ratio math; etc.).
    """

    statement_type = models.CharField(max_length=8, choices=StatementType.choices)
    company = models.ForeignKey(
        "foundation.Company", on_delete=models.PROTECT, related_name="statements"
    )
    segment = models.ForeignKey(
        "foundation.Segment", null=True, blank=True, on_delete=models.PROTECT,
        related_name="statements",
    )
    period_start = models.DateField(db_index=True)
    period_end = models.DateField(db_index=True)
    data = models.JSONField(default=list)
    identity_ok = models.BooleanField(default=True)
    identity_note = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, default="draft")  # draft / final
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_end", "statement_type", "segment"]
        indexes = [
            models.Index(fields=["statement_type", "company", "period_start", "period_end"]),
        ]

    def __str__(self):
        return f"{self.get_statement_type_display()} {self.period_start}–{self.period_end} {self.segment or 'GRAND'}"

    def rows_by_key(self) -> dict:
        return {row["key"]: row for row in self.data}


class MonthEndClose(AuditableModel):
    """Month-end close workflow (BUILD-PLAN Phase 8, ADR-013).

    Sequence: accruals -> reconciliations -> close -> appropriations.
    Each step is a state (pending/in_progress/done); a period can only be
    closed when all four steps are done. Closing locks the fiscal period so
    no further entries can back-post into it (posting rules §17).
    """

    fiscal_period = models.OneToOneField(
        "foundation.FiscalPeriod", on_delete=models.PROTECT, related_name="month_end_close"
    )
    company = models.ForeignKey(
        "foundation.Company", on_delete=models.PROTECT, related_name="month_end_closes"
    )
    # step -> status
    steps = models.JSONField(
        default=dict,
        help_text='{"accruals": "pending", "recon": "pending", "close": "pending", "appropriations": "pending"}',
    )
    status = models.CharField(max_length=16, default="open")  # open / closed
    notes = models.TextField(blank=True)
    closed_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-fiscal_period__period_no"]

    def __str__(self):
        return f"Close {self.fiscal_period} ({self.status})"

    @property
    def is_ready(self) -> bool:
        return all(v == "done" for v in (self.steps or {}).values())

    def step_status(self, step: str) -> str:
        return (self.steps or {}).get(step, "pending")
