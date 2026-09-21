"""Accounts Receivable bounded context (BUILD-PLAN Phase 2).

Covers the customer ledger with the cumulative Over/(Short) cycle model
(ADR-013), Acknowledgment Receipts (ACCTG-FOR-005 v3 — the company does NOT
issue official receipts), three-tier pricing with per-cycle snapshots
(ADR-014), bank deposits that post a real JE (supersedes ADR-016), and the
cash short/excess worksheet (ADR-030).

AR receipt lifecycle: draft -> submitted -> posted (Head approval). The
collection posting event is `cash.collection` (RESOLUTION #9):
    Dr segment Cash on Hand 10010/10013/10016 | Cr user credit lines
    (or Cr AR 12020-12030 when the payment is applied to a prior AR invoice).
The Head's Bank Deposit then posts Dr Cash in Bank | Cr segment Cash on Hand.
"""

from decimal import Decimal

from django.db import models

from apps.core.models import AuditableModel, SoftDeleteMixin


class CustomerGroup(models.TextChoices):
    FUEL = "fuel", "Fuel"
    EQUIPMENT = "equipment", "Equipment"
    OPS = "ops", "Operations"


class PricingTier(models.TextChoices):
    REGULAR = "regular", "Regular"
    PATRON = "patron", "Patron"
    VOLUME = "volume", "Volume"


class Customer(SoftDeleteMixin, AuditableModel):
    """Centralized customer master (ADR-007). One-time migration cleans the
    macro-era per-client sheets into a single registry."""

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    group = models.CharField(max_length=16, choices=CustomerGroup.choices, default=CustomerGroup.FUEL)
    segment = models.ForeignKey(
        "foundation.Segment", on_delete=models.PROTECT, related_name="customers"
    )
    pricing_tier = models.CharField(max_length=16, choices=PricingTier.choices, default=PricingTier.REGULAR)
    tin = models.CharField("TIN", max_length=32, blank=True)
    address = models.CharField(max_length=255, blank=True)
    contact_no = models.CharField(max_length=32, blank=True)
    owner_name = models.CharField("Owner", max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} {self.name}"


class PriceSnapshot(AuditableModel):
    """ADR-014: prices are set per cycle (Tuesday-to-Monday) and snapshot for
    the customer, so historical AR never re-prices after the fact. Pricing
    arrives via Viber/Facebook and is entered here (kills ~70% AR rework)."""

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="price_snapshots")
    product_code = models.CharField(max_length=32)  # e.g. RON95, DIESEL, or equipment SKU
    cycle_start = models.DateField(db_index=True)  # Tuesday of the Tue-Mon cycle (ADR-013)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    tier = models.CharField(max_length=16, choices=PricingTier.choices, default=PricingTier.REGULAR)

    class Meta:
        unique_together = ("customer", "product_code", "cycle_start")
        ordering = ["customer", "cycle_start", "product_code"]

    def __str__(self):
        return f"{self.customer} {self.product_code} @ {self.unit_price} (wk {self.cycle_start})"


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Cash"
    CHECK = "check", "Check"
    GCASH = "gcash", "GCash"
    OTHERS = "others", "Others"


class ReceiptStatus(models.TextChoices):
    """AR receipt lifecycle (ADR-015 / new approval workflow).

    draft      -> prepared by staff, editable, no JE yet
    submitted  -> awaiting the Accounting & Finance Head's review
    posted     -> approved by the Head; the collection JE is posted to the GL
    """

    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted for approval"
    POSTED = "posted", "Posted to GL"


class AcknowledgmentReceipt(AuditableModel):
    """AR# (ACCTG-FOR-005 v3, pre-numbered YYYY-SEQ via the sequence registry).

    The Account Distribution grid (``AcknowledgmentReceiptLine``) carries the
    debit/credit lines. The debit side is always the segment's Cash on Hand
    (auto); the credit side is entered by the preparer.

    Lifecycle (draft -> submitted -> posted):
      - the collection JE is built and posted only when the Accounting &
        Finance Head approves the submitted receipt (ADR-033 approval gate);
      - the Head then records a Bank Deposit covering one or more posted
        receipts, which posts Dr Cash in Bank | Cr segment Cash on Hand
        (supersedes ADR-016 "deposit = no JE").
    """

    receipt_no = models.CharField(max_length=32, unique=True)  # AR-YYYY-SEQ
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="receipts")
    transaction_date = models.DateField(db_index=True)
    # Derived total of the distribution lines (debit == credit).
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    payment_method = models.CharField(max_length=8, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    # The Cash on Hand account debited by the collection (auto = segment COH).
    cash_account = models.ForeignKey(
        "foundation.Account", on_delete=models.PROTECT, related_name="ar_receipts", limit_choices_to={"code__startswith": "100"}
    )
    check_no = models.CharField(max_length=32, blank=True)
    # Optional manual payment/transaction reference (legacy monitoring-sheet
    # "TR No"). A free-text cross-reference only — NEVER routed through the
    # DocumentSequence registry, so it cannot collide with generated AR#/CV#/
    # RFP#/JE# numbers. Non-unique: it may repeat across clients/companies.
    transaction_no = models.CharField("Transaction No.", max_length=64, blank=True)
    # Reference PO number (manually entered; not linked to the PO system).
    ref_po_no = models.CharField("Ref. PO No.", max_length=64, blank=True)
    collected_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL)
    segment = models.ForeignKey("foundation.Segment", on_delete=models.PROTECT, related_name="ar_receipts")
    # The journal entry produced by this collection (filled on approval/post).
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="ar_receipts"
    )
    # Applied AR invoice (optional) — when blank the credit goes to Unearned.
    applied_to = models.ForeignKey(
        "ARInvoice", null=True, blank=True, on_delete=models.PROTECT, related_name="receipts"
    )

    # --- approval workflow -------------------------------------------------
    status = models.CharField(
        max_length=16, choices=ReceiptStatus.choices, default=ReceiptStatus.DRAFT, db_index=True
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
    # Proof of deposit / AR attachment the Head checks before approving.
    attachment = models.FileField(upload_to="ar_attachments/", blank=True)
    # The bank deposit this receipt was included in (set when the Head posts it).
    deposit = models.ForeignKey(
        "Deposit", null=True, blank=True, on_delete=models.PROTECT, related_name="receipts"
    )

    class Meta:
        ordering = ["-transaction_date", "-receipt_no"]

    def __str__(self):
        return f"{self.receipt_no} {self.customer} {self.amount}"

    @property
    def is_editable(self) -> bool:
        return self.status == ReceiptStatus.DRAFT

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
        """Refresh ``amount`` from the distribution lines (posting source)."""
        totals = self.lines.aggregate(
            debit=models.Sum("debit"), credit=models.Sum("credit")
        )
        self.amount = totals["debit"] or Decimal("0.00")
        self.save(update_fields=["amount", "updated_at"])


class AcknowledgmentReceiptLine(models.Model):
    """One line of an AR receipt's Account Distribution grid.

    The debit side is normally the segment Cash on Hand (auto-filled by the
    service); credit lines are chosen by the preparer.
    """

    receipt = models.ForeignKey(
        AcknowledgmentReceipt, on_delete=models.PROTECT, related_name="lines"
    )
    line_no = models.PositiveIntegerField()
    account = models.ForeignKey(
        "foundation.Account", on_delete=models.PROTECT, related_name="ar_receipt_lines"
    )
    segment = models.ForeignKey(
        "foundation.Segment", on_delete=models.PROTECT, related_name="ar_receipt_lines"
    )
    cost_center = models.CharField("Cost center", max_length=64, blank=True)
    description = models.CharField(max_length=500, blank=True)
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["line_no"]
        unique_together = ("receipt", "line_no")

    def __str__(self):
        side = "Dr" if self.debit else "Cr"
        amount = self.debit or self.credit
        return f"{self.receipt.receipt_no} #{self.line_no} {side} {self.account.code} {amount}"


class ARInvoice(AuditableModel):
    """Sales invoice / delivery billing (SI# per catalog events #48/#49).

    Booked on delivery-completed. Two posting paths (POSTING_RULES §12):
      - paid on delivery: Dr Cash | Cr Revenue
      - unpaid (credit):  Dr AR 120xx | Cr Revenue
    Payment later applies the receipt to this invoice (Cr AR).
    """

    invoice_no = models.CharField(max_length=32, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="invoices")
    transaction_date = models.DateField(db_index=True)
    segment = models.ForeignKey("foundation.Segment", on_delete=models.PROTECT, related_name="ar_invoices")
    total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    is_paid_on_delivery = models.BooleanField(default=False, db_index=True)
    status = models.CharField(max_length=16, default="open")  # open / partially_paid / paid / posted
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="ar_invoices"
    )
    # Payment-based invoice booking (RESOLUTION #27) — confirmed in Phase 3.
    booked_on_payment = models.BooleanField(default=False)

    class Meta:
        ordering = ["-transaction_date", "-invoice_no"]

    @property
    def amount_paid(self):
        # Exclude receipts whose JE was reversed — the collection was undone,
        # so the invoice balance is restored (ADR-004 reversal recompute).
        return (
            self.receipts.exclude(journal_entry__status="reversed").aggregate(
                paid=models.Sum("amount")
            )["paid"]
            or Decimal("0.00")
        )

    @property
    def balance(self):
        return self.total - self.amount_paid

    def __str__(self):
        return f"{self.invoice_no} {self.customer} {self.total}"


class ARInvoiceLine(models.Model):
    invoice = models.ForeignKey(ARInvoice, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveIntegerField()
    product_code = models.CharField(max_length=32)
    description = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    amount = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ["invoice", "line_no"]
        unique_together = ("invoice", "line_no")

    def __str__(self):
        return f"{self.invoice.invoice_no} L{self.line_no} {self.product_code}"


class Deposit(AuditableModel):
    """Bank deposit covering one or more posted AR receipts.

    Corrected accounting (supersedes ADR-016's "deposit = state change, NO JE"):
    depositing collections moves value from Cash on Hand to a bank account, so
    the Head posts a real journal entry per deposit slip:

        Dr Cash in Bank (bank_account) | Cr segment Cash on Hand

    One deposit may cover many receipts (a single bank deposit slip). The
    recipient bank is the deposit's ``bank_account`` (a 100xx bank GL account);
    the source is each covered receipt's segment Cash on Hand account.
    """

    # The bank GL account receiving the deposit (100xx).
    bank_account = models.ForeignKey(
        "foundation.Account", on_delete=models.PROTECT, related_name="deposits", limit_choices_to={"code__startswith": "100"}
    )
    transaction_date = models.DateField(db_index=True)
    # Optional generated slip number (BD-YYYY-SEQ).
    deposit_no = models.CharField(max_length=32, unique=True, null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    reference = models.CharField(max_length=64, blank=True)
    deposited_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Deposit proof (deposit slip scan/photo).
    attachment = models.FileField(upload_to="ar_deposits/", blank=True)
    # The journal entry posted by this deposit (Dr Bank | Cr Cash on Hand).
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="ar_deposits"
    )
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-transaction_date", "-id"]

    def __str__(self):
        return f"Deposit {self.deposit_no or self.id} {self.bank_account} {self.amount}"


class CashShortExcess(AuditableModel):
    """CASH SHORT sheet (ADR-029/030). Recon worksheet, NOT a JE: the cashier
    expected vs actual variance per cycle; cause is mandatory and variance
    needs approval before any adjustment JE (RESOLUTION: cash short requires
    a NEW COA account, 63210 is 'Other Operating Expenses')."""

    cycle_start = models.DateField(db_index=True)  # Tuesday of the cycle
    segment = models.ForeignKey("foundation.Segment", on_delete=models.PROTECT, related_name="ar_cash_short_excesses")
    expected_cash = models.DecimalField(max_digits=18, decimal_places=2)
    actual_cash = models.DecimalField(max_digits=18, decimal_places=2)
    variance = models.DecimalField(max_digits=18, decimal_places=2)
    cause = models.TextField(blank=True)
    status = models.CharField(max_length=16, default="open")  # open / approved / adjusted
    approval = models.ForeignKey(
        "workflow.ApprovalRequest", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        unique_together = ("cycle_start", "segment")
        ordering = ["-cycle_start"]

    def __str__(self):
        return f"CS/E {self.cycle_start} {self.segment}: {self.variance}"