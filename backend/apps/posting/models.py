"""Posting engine domain.

Core accounting objects per ADR-004 (immutable journal), ADR-005 (balance
sheet / income statement tracking) and ADR-002 (no force-balance):

- JournalEntry / JournalEntryLine : the immutable record of a transaction.
- GeneralLedger : a posted line's effect on an account (balance derived).
- PostingRule / PostingRuleLine  : configurable mapping from business events
  to journal lines (ADR-004: rules stored, not hardcoded).
- PostingService : the engine that validates, balances-checkes and posts.

Design invariants (tested in apps/posting/tests/):
1. Journal entries are append-only. Once posted, lines may never be edited;
   corrections are made with reversing entries.
2. Debits must equal credits before posting. The system NEVER auto-adjusts:
   it raises UnbalancedEntryError and surfaces the difference (ADR-002).
3. All money values are Decimal, 2dp, half-up (apps.core.money).
"""

from decimal import Decimal

from django.db import models, transaction

from apps.core.money import money
from apps.core.models import AuditableModel


class PostingStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted for approval"
    APPROVED = "approved", "Approved (posting eligible)"
    POSTED = "posted", "Posted"
    REVERSED = "reversed", "Reversed (matched by reversing entry)"
    REJECTED = "rejected", "Rejected"


class JournalEntry(AuditableModel):
    """One business event, journalized. Immutable once POSTED (ADR-004)."""

    # Prefixes documented in ADR-032 (CV/PCV/RFP/AR#/SI#/PR#/PO#/PB#/CE#/BR#...).
    entry_no = models.CharField(max_length=32, unique=True)
    company = models.ForeignKey(
        "foundation.Company", on_delete=models.PROTECT, related_name="journal_entries"
    )
    segment = models.ForeignKey(
        "foundation.Segment", on_delete=models.PROTECT, related_name="journal_entries"
    )
    fiscal_period = models.ForeignKey(
        "foundation.FiscalPeriod", on_delete=models.PROTECT, related_name="journal_entries",
        null=True, blank=True,
    )
    # ADR-013: a journal entry belongs to a Tue->Mon accounting cycle, derived
    # from its transaction date by apps.foundation.calendar.cycle_range_for.
    transaction_date = models.DateField(db_index=True)
    status = models.CharField(max_length=16, choices=PostingStatus.choices, default=PostingStatus.DRAFT, db_index=True)
    description = models.CharField(max_length=500)
    # References back to the originating document (voucher no., SI no., ...).
    source_doc_type = models.CharField(max_length=16, blank=True)
    source_doc_no = models.CharField(max_length=32, blank=True, db_index=True)
    # ADR-033: payroll and external feeds post with a file provenance.
    source_file = models.CharField(max_length=255, blank=True)
    # Reconciliation: set on the reversing entry; both get the same token.
    reversal_token = models.CharField(max_length=40, blank=True, db_index=True)
    total_debit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    total_credit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["-transaction_date", "-id"]
        indexes = [
            models.Index(fields=["company", "transaction_date"]),
            models.Index(fields=["status", "source_doc_type"]),
        ]

    def __str__(self):
        return f"{self.entry_no} ({self.status})"

    @property
    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit

    @property
    def is_posted(self) -> bool:
        return self.status == PostingStatus.POSTED

    def recalc_totals(self) -> None:
        totals = self.lines.aggregate(
            debit=models.Sum("debit"), credit=models.Sum("credit")
        )
        self.total_debit = totals["debit"] or Decimal("0.00")
        self.total_credit = totals["credit"] or Decimal("0.00")
        self.save(update_fields=["total_debit", "total_credit", "updated_at"])


class JournalEntryLine(models.Model):
    """One side of a journal entry. Append-only; never edited after posting."""

    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveIntegerField()
    account = models.ForeignKey("foundation.Account", on_delete=models.PROTECT, related_name="je_lines")
    description = models.CharField(max_length=500, blank=True)
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    # Optional operational tagging (AR/AP subledger refs, payroll event no.):
    reference = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["line_no"]
        unique_together = ("entry", "line_no")

    def __str__(self):
        side = "Dr" if self.debit else "Cr"
        return f"{self.entry.entry_no} #{self.line_no} {side} {self.account.code} {self.debit or self.credit}"


class GeneralLedger(models.Model):
    """A posted line's effect on a ledger account.

    ALWAYS derived from JournalEntryLine — this table is a projection for fast
    querying and audit queries, never a source of truth. Balance computation
    per account = SUM(debit) - SUM(credit) with sign by normal balance.
    """

    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="gl_lines")
    line = models.OneToOneField(JournalEntryLine, on_delete=models.PROTECT, related_name="gl")
    account = models.ForeignKey("foundation.Account", on_delete=models.PROTECT, related_name="gl_lines")
    company = models.ForeignKey("foundation.Company", on_delete=models.PROTECT, related_name="gl_lines")
    segment = models.ForeignKey("foundation.Segment", on_delete=models.PROTECT, related_name="gl_lines")
    fiscal_period = models.ForeignKey("foundation.FiscalPeriod", on_delete=models.PROTECT, null=True, blank=True)
    transaction_date = models.DateField(db_index=True)
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["transaction_date", "id"]
        indexes = [
            models.Index(fields=["account", "transaction_date"]),
            models.Index(fields=["company", "segment", "transaction_date"]),
        ]

    def __str__(self):
        return f"{self.transaction_date} {self.account.code} {self.debit or self.credit}"


class PostingRule(AuditableModel):
    """Configurable business-event -> JE template (ADR-004).

    A rule has one or more PostingRuleLines, each carrying a share (0..1) of
    the transaction amount and a debit/credit side. PostingService applies the
    rule, runs balance checks, and produces a balanced draft JE. The rule's
    lines therefore NEVER need to balance by themselves — e.g. the RFP rule
    produces Dr TOTAL / Cr 20k advances / Cr AP remainder (ADR-018/023).
    """

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=128)
    event = models.CharField(max_length=64, db_index=True)  # business event name
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.event}"


class PostingRuleLine(models.Model):
    rule = models.ForeignKey(PostingRule, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveIntegerField()
    # "debit" or "credit"
    side = models.CharField(max_length=8)
    # Fixed account code (resolved at apply time) — must exist in COA.
    account_code = models.CharField(max_length=10)
    # A fixed absolute amount for this line (e.g. the 20,000 advances leg of
    # the RFP rule). Takes precedence over share when > 0.
    fixed_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    # Fraction of the transaction amount for this line (0..1). Ignored when
    # fixed_amount is set or use_balance is true.
    share = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("1.0000"))
    use_balance = models.BooleanField("take remainder", default=False)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["rule", "line_no"]
        unique_together = ("rule", "line_no")

    def __str__(self):
        return f"{self.rule.code} L{self.line_no} {self.side} {self.account_code}"