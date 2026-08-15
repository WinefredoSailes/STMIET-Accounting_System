"""Accounts Receivable bounded context (BUILD-PLAN Phase 2).

Covers the customer ledger with the cumulative Over/(Short) cycle model
(ADR-013), Acknowledgment Receipts (ACCTG-FOR-005 v3 — the company does NOT
issue official receipts), three-tier pricing with per-cycle snapshots
(ADR-014), deposits (state change, NO JE — ADR-016), and the cash
short/excess worksheet (ADR-030).

The single posting event is `cash.collection` (RESOLUTION #9):
    Dr Cash 100xx | Cr Unearned 21000/21016/21023
    (or Cr AR 12020-12030 when the payment is applied to prior AR).
"""

from decimal import Decimal

from django.db import models

from apps.core.models import AuditableModel


class CustomerGroup(models.TextChoices):
    FUEL = "fuel", "Fuel"
    EQUIPMENT = "equipment", "Equipment"
    OPS = "ops", "Operations"


class PricingTier(models.TextChoices):
    REGULAR = "regular", "Regular"
    PATRON = "patron", "Patron"
    VOLUME = "volume", "Volume"


class Customer(AuditableModel):
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


class AcknowledgmentReceipt(AuditableModel):
    """AR# (ACCTG-FOR-005 v3, pre-numbered YYYY-SEQ via the sequence registry).

    Posting event `cash.collection`:
        Dr Cash (bank/cash account) | Cr Unearned 210xx
    When the payment is applied to a prior AR invoice:
        Dr Cash | Cr AR 12020/12023/12026 (or 12030 fuel)
    """

    receipt_no = models.CharField(max_length=32, unique=True)  # AR-YYYY-SEQ
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="receipts")
    transaction_date = models.DateField(db_index=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    payment_method = models.CharField(max_length=8, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    # Cash account from COA (100xx), e.g. PNB / BDO / cash-on-hand.
    cash_account = models.ForeignKey(
        "foundation.Account", on_delete=models.PROTECT, related_name="ar_receipts", limit_choices_to={"code__startswith": "100"}
    )
    check_no = models.CharField(max_length=32, blank=True)
    collected_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL)
    segment = models.ForeignKey("foundation.Segment", on_delete=models.PROTECT, related_name="ar_receipts")
    # The journal entry produced by this collection (filled on post).
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="ar_receipts"
    )
    # Applied AR invoice (optional) — when blank the credit goes to Unearned.
    applied_to = models.ForeignKey(
        "ARInvoice", null=True, blank=True, on_delete=models.PROTECT, related_name="receipts"
    )

    class Meta:
        ordering = ["-transaction_date", "-receipt_no"]

    def __str__(self):
        return f"{self.receipt_no} {self.customer} {self.amount}"


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
        return self.receipts.aggregate(paid=models.Sum("amount"))["paid"] or Decimal("0.00")

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
    """Bank deposit (ADR-016). A STATE CHANGE, NOT a journal entry: the
    collection JE already debited the cash account; depositing moves value
    between cash-on-hand and the bank account balance for reconciliation."""

    # The cash account receiving the deposit (100xx bank account).
    bank_account = models.ForeignKey(
        "foundation.Account", on_delete=models.PROTECT, related_name="deposits", limit_choices_to={"code__startswith": "100"}
    )
    transaction_date = models.DateField(db_index=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    reference = models.CharField(max_length=64, blank=True)
    deposited_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-transaction_date"]

    def __str__(self):
        return f"Deposit {self.transaction_date} {self.bank_account} {self.amount}"


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