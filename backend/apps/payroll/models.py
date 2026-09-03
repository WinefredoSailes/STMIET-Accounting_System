"""Payroll GL feed (BUILD-PLAN Phase 6, ADR-033).

STMIET's payroll/HR lives in a separate vendor-owned system. This app owns the
GL feed contract: the payroll system emits a fixed-schema feed file
(SUMMARY + JE LINES sheets), the accounting system validates it, shows an
immutable JE preview, and REVIEWER approval posts it to the GL (ADR-005). The
feed file is archived with the batch (audit trail), and batch-reference linkage
ties the posted JE back to the payroll run.

`PayrollFeed` is the archived batch + workflow state; `PayrollFeedLine` is one
JE line (one of Debit/Credit must be zero). Posting is a single immutable JE of
all lines (POSTING_RULES §14.1 gross-to-net + ER shares as their own lines).
"""

import uuid

from django.db import models

from apps.core.models import AuditableModel


class PayrollFeedStatus(models.TextChoices):
    UPLOADED = "uploaded", "Uploaded"
    VALIDATED = "validated", "Validated"
    REVIEWED = "reviewed", "Reviewed (ready to post)"
    POSTED = "posted", "Posted"
    REJECTED = "rejected", "Rejected"


class PayrollFeed(AuditableModel):
    """One archived payroll GL feed batch (ADR-033)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch_reference = models.CharField(max_length=64, unique=True)
    schema_version = models.CharField(max_length=16, default="v1")
    period_start = models.DateField()
    period_end = models.DateField()
    entity = models.CharField(max_length=8)
    company = models.ForeignKey(
        "foundation.Company", on_delete=models.PROTECT, related_name="payroll_feeds"
    )
    segment = models.ForeignKey(
        "foundation.Segment", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="payroll_feeds",
    )
    cost_center = models.CharField(max_length=8, blank=True)
    net_pay_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    er_share_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    remittance_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    status = models.CharField(
        max_length=16, choices=PayrollFeedStatus.choices, default=PayrollFeedStatus.UPLOADED
    )
    archived_file = models.FileField(upload_to="payroll_feeds/", blank=True)
    validation_error = models.TextField(blank=True)
    review_user = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="payroll_feeds",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-period_start", "-batch_reference"]

    def __str__(self):
        return f"{self.batch_reference} [{self.status}]"

    @property
    def is_balanced(self):
        return sum(l.debit for l in self.lines.all()) == sum(l.credit for l in self.lines.all())


class PayrollFeedLine(models.Model):
    """One JE line inside a payroll feed batch (feed's JE LINES sheet)."""

    feed = models.ForeignKey(PayrollFeed, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveIntegerField()
    segment = models.ForeignKey(
        "foundation.Segment", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    cost_center = models.CharField(max_length=8, blank=True)
    gl_account = models.ForeignKey("foundation.Account", on_delete=models.PROTECT, related_name="+")
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["feed", "line_no"]

    def __str__(self):
        return f"{self.feed.batch_reference} #{self.line_no}"