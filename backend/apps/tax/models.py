"""Tax & Compliance bounded context (BUILD-PLAN Phase 9).

Satisfies the "bana-bana" elimination goals:
  - VAT at SI level (12% VAT-inclusive -> output VAT derived; value flows to
    the output VAT payable via the data-driven SegmentAccountMap `vat_output`
    role — no VAT GL accounts unless Alywin approves).
  - WHT (expanded 2307 / compensation 2316) surfaced from the AP/CV module and
    the payroll feed for BIR 2307/2306/2316 prep.
  - Income tax provision (Dr 64600 tax expense | Cr income tax payable).
  - Tax calendar + filing tracking.

This module is thin and data-driven: it derives compliance figures from the
already-posted GL (SI invoices from AR, CV withholding from AP), never
re-computes a source of truth, and posts provisions through the standard
posting engine + SegmentAccountMap roles.
"""

from decimal import Decimal

from django.db import models

from apps.core.models import AuditableModel


class FilingStatus(models.TextChoices):
    NOT_DUE = "not_due", "Not due"
    DUE = "due", "Due"
    FILED = "filed", "Filed"
    PAID = "paid", "Paid"
    OVERDUE = "overdue", "Overdue"


class TaxCalendar(AuditableModel):
    """One BIR filing obligation (form + filing period + due date + status).

    Removes the "bana-bana" (by-guess-and-by-gosh) estimation: the calendar
    lists what must be filed when, and tracks filed/paid state.
    """

    BIR_FORMS = [
        ("2307", "2307 — Certificate of Creditable Tax Withheld at Source"),
        ("2306", "2306 — Certificate of Final Tax Withheld at Source"),
        ("2316", "2316 — Certificate of Compensation Payment/Tax Withheld"),
        ("2550Q", "2550Q — Monthly Quarterly VAT Return"),
        ("2551Q", "2551Q — Percentage Tax Return"),
        ("1702Q", "1702Q — Quarterly Income Tax Return"),
        ("1702", "1702 — Annual Income Tax Return"),
    ]

    form = models.CharField(max_length=8, choices=BIR_FORMS)
    company = models.ForeignKey("foundation.Company", on_delete=models.PROTECT, related_name="tax_calendar")
    filing_period = models.CharField(max_length=16)  # e.g. "Jan 2026" or "Q1 2026"
    due_date = models.DateField()
    status = models.CharField(max_length=16, choices=FilingStatus.choices, default=FilingStatus.NOT_DUE)
    filed_date = models.DateField(null=True, blank=True)
    paid_date = models.DateField(null=True, blank=True)
    amount_due = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["due_date", "form"]
        unique_together = ("form", "company", "filing_period")

    def __str__(self):
        return f"{self.form} {self.filing_period} due {self.due_date} ({self.status})"


class VATComputation(AuditableModel):
    """SI-level output VAT extraction (Phase 9: declare what's on the SI).

    When an ARInvoice is booked we derive the VAT-inclusive output VAT (12%)
    using the standard PH formula, and record the split so the VAT return can
    be built (and to remove manual estimation). This is a derived compliance
    record — the revenue JE itself is unchanged (no VAT GL per Q1).
    """

    invoice = models.OneToOneField(
        "ar.ARInvoice", on_delete=models.PROTECT, related_name="vat_computation"
    )
    segment = models.ForeignKey("foundation.Segment", on_delete=models.PROTECT, related_name="vat_computations")
    vat_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.1200"))
    gross_amount = models.DecimalField(max_digits=18, decimal_places=2)
    net_amount = models.DecimalField(max_digits=18, decimal_places=2)
    output_vat = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ["invoice__transaction_date", "invoice__invoice_no"]

    def __str__(self):
        return f"VAT {self.invoice.invoice_no}: out {self.output_vat}"

    @property
    def is_balanced(self) -> bool:
        return self.gross_amount == self.net_amount + self.output_vat


class WithholdingCertificate(AuditableModel):
    """A BIR withholding certificate row (2307 / 2306) — derived from the
    AP/CV module's posted withholding, so 2307/2306 prep is one query, not a
    manual tally. Compensation (2316) data comes from the payroll feed.
    """

    CERT_TYPES = [
        ("2307", "2307 — Expanded (creditable) withholding"),
        ("2306", "2306 — Final withholding"),
    ]

    cert_type = models.CharField(max_length=8, choices=CERT_TYPES)
    form = models.ForeignKey(
        "TaxCalendar", null=True, blank=True, on_delete=models.SET_NULL, related_name="certificates"
    )
    segment = models.ForeignKey("foundation.Segment", on_delete=models.PROTECT, related_name="wht_certificates")
    payee = models.ForeignKey(
        "ap.Supplier", null=True, blank=True, on_delete=models.SET_NULL, related_name="wht_certificates"
    )
    tin = models.CharField("TIN", max_length=32, blank=True)
    gross_amount = models.DecimalField(max_digits=18, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2)
    # Reference of the CV that carried this withholding.
    cv_number = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ["-cv_number", "segment__code"]

    def __str__(self):
        return f"{self.cert_type} {self.tin or self.payee} tax {self.tax_amount}"


class IncomeTaxProvision(AuditableModel):
    """A posted income-tax provision run (Phase 9).

    Dr 64600 (tax expense) | Cr income tax payable, per segment, from a
    taxable-income basis. Immutable once posted; reversal allowed.
    """

    segment = models.ForeignKey("foundation.Segment", on_delete=models.PROTECT, related_name="income_tax_provisions")
    filing_period = models.CharField(max_length=16)
    taxable_income = models.DecimalField(max_digits=18, decimal_places=2)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=4)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2)
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="income_tax_provisions"
    )

    class Meta:
        ordering = ["-filing_period"]

    def __str__(self):
        return f"Income tax {self.segment.code} {self.filing_period}: {self.tax_amount}"
