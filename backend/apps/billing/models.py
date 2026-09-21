"""Billing bounded context (BUILD-PLAN — Billing Module).

Two billing transaction types drive this module:
  * Intercompany Billing - STPC   (``billing_type == "stpc"``)
  * Third-Party Billing           (``billing_type == "third_party"``)

A ``BillingDocument`` is a manually prepared billing whose Account
Distribution grid (``BillingLine``) carries exactly the fields the finance
team asked for:

    COA | Account Name | Segment | Cost Center | Description | Debit | Credit

The counterparty is picked from the existing AR customers + AP suppliers
masters (one shared picker); Intercompany billing defaults it to STPC.

When an RFP is used as the basis of the billing, the posted Journal Entry
captures the RFP number in its Note/Reference field (``ref_number`` and the
header description), and — for credit lines on the "unbilled" receivable
accounts 15550 / 15560 — the per-line reference records the RFP number and
the amount being billed so the entry traces back to the originating RFP.

Lifecycle (ADR-020-style, mirrors the Journal Entry approval):
    draft -> submitted -> approved (Accounting & Finance Head) -> posted (JE)
A rejected billing returns to draft with a rejection note.
"""

from decimal import Decimal

from django.db import models

from apps.core.constants import COST_CENTER_MAX_LENGTH
from apps.core.models import AuditableModel

# Credit lines on these "unbilled" receivable accounts carry the originating
# RFP number AND the amount being billed in their Note/Reference field so the
# billing can be traced back to the RFP (requirement 4).
UNBILLED_CREDIT_ACCOUNTS = ("15550", "15560")


class BillingType(models.TextChoices):
    INTERCOMPANY_STPC = "stpc", "Intercompany Billing - STPC"
    THIRD_PARTY = "third_party", "Third-Party Billing"


class BillingStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted for approval"
    APPROVED = "approved", "Approved (ready to post)"
    POSTED = "posted", "Posted to GL"


class BillingDocument(AuditableModel):
    """A prepared, journalized billing transaction (STPC or third-party)."""

    billing_no = models.CharField(max_length=32, unique=True)  # BI-YYYY-SEQ
    billing_type = models.CharField(
        max_length=16, choices=BillingType.choices, default=BillingType.THIRD_PARTY,
        db_index=True,
    )
    billing_date = models.DateField(db_index=True)
    company = models.ForeignKey(
        "foundation.Company", on_delete=models.PROTECT, related_name="billing_documents"
    )
    segment = models.ForeignKey(
        "foundation.Segment", on_delete=models.PROTECT, related_name="billing_documents"
    )
    # Counterparty (shared customer/supplier picker). Plain name so the JE
    # header and General Journal show it without a stale master copy; the
    # optional links keep the subledger trace when the party is a known master.
    party_name = models.CharField(max_length=255)
    customer = models.ForeignKey(
        "ar.Customer", null=True, blank=True, on_delete=models.PROTECT,
        related_name="billing_documents",
    )
    supplier = models.ForeignKey(
        "ap.Supplier", null=True, blank=True, on_delete=models.PROTECT,
        related_name="billing_documents",
    )
    # The RFP this billing is based on (optional). Its number is captured in the
    # posted JE's Note/Reference field.
    rfp = models.ForeignKey(
        "ap.RFPDocument", null=True, blank=True, on_delete=models.PROTECT,
        related_name="billing_documents",
    )
    # Manual cross-reference (invoice no., client ref) when there is no RFP.
    reference = models.CharField(max_length=128, blank=True)
    particulars = models.CharField(max_length=500, blank=True)
    # Total of the debit lines (the amount billed). Credit lines balance it.
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(
        max_length=16, choices=BillingStatus.choices, default=BillingStatus.DRAFT, db_index=True
    )
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT,
        related_name="billing_documents",
    )
    approved_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_note = models.TextField(blank=True)
    revision_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-billing_date", "-billing_no"]

    def __str__(self):
        return f"{self.billing_no} {self.party_name} {self.amount} ({self.status})"

    @property
    def is_editable(self) -> bool:
        return self.status == BillingStatus.DRAFT

    @property
    def debit_total(self):
        return sum((l.debit for l in self.lines.all()), Decimal("0.00"))

    @property
    def credit_total(self):
        return sum((l.credit for l in self.lines.all()), Decimal("0.00"))

    @property
    def is_balanced(self) -> bool:
        return self.debit_total == self.credit_total

    def recalc_totals(self) -> None:
        """Refresh ``amount`` from the debit lines (posting source)."""
        totals = self.lines.aggregate(
            debit=models.Sum("debit"), credit=models.Sum("credit")
        )
        self.amount = totals["debit"] or Decimal("0.00")
        self.save(update_fields=["amount", "updated_at"])


class BillingLine(models.Model):
    """One line of a billing's Account Distribution grid.

    Each row is a single line carrying exactly one side (Dr or Cr). The posted
    Journal Entry is built from these rows as entered and must balance.
    """

    class Side(models.TextChoices):
        DEBIT = "dr", "Dr"
        CREDIT = "cr", "Cr"

    billing = models.ForeignKey(
        BillingDocument, on_delete=models.CASCADE, related_name="lines"
    )
    line_no = models.PositiveIntegerField()
    side = models.CharField(max_length=2, choices=Side.choices, default=Side.DEBIT)
    segment = models.ForeignKey(
        "foundation.Segment", on_delete=models.PROTECT, related_name="billing_lines"
    )
    account = models.ForeignKey(
        "foundation.Account", on_delete=models.PROTECT, related_name="billing_lines"
    )
    cost_center = models.CharField(
        "Cost Center/Ref", max_length=COST_CENTER_MAX_LENGTH, blank=True
    )
    description = models.CharField(max_length=500, blank=True)
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["billing", "line_no"]
        unique_together = ("billing", "line_no")

    def __str__(self):
        side = "Dr" if self.debit else "Cr"
        amount = self.debit or self.credit
        return f"{self.billing.billing_no} #{self.line_no} {side} {self.account.code} {amount}"