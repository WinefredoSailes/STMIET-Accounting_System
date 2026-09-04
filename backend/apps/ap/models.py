"""Accounts Payable bounded context (BUILD-PLAN Phase 3).

Implements the purchase-to-pay chain (ADR-017):
  PR -> PO -> RR -> Supplier Invoice -> RFP -> CONSO -> CV

The RFP (ACCTG-FOR-012) is the central document (ADR-018):
  - A#### sequential numbering with LAST AP per-vendor gap tracking (ADR-019)
  - 4-level approval chain (ADR-020): Prepared -> Checked (Alywin) ->
    Acctg Manager -> Finance Manager; >P100k escalates to CNR
  - P2,500 payment threshold: >= RFP, < petty cash voucher (ADR-022)
  - Distribution lines carry an explicit Dr/Cr side; the posted JE is built
    exactly from the lines as entered and must balance (Dr total = Cr total).
    Credit accounts (AP, payables to officers, advances clearing, WHT) are
    entered as lines like any debit/expense account.
  - CONSO batch grading approval by Accounting Head posts all RFPs' JEs
    together (POSTING_RULES 7.2/7.3)

The Check Voucher (ACCTG-FOR-010) clears AP with WHT split (7.4):
      Dr AP {gross} | Cr Cash {net} + Cr WHT 64110-26 {tax}
"""

from decimal import Decimal

from django.db import models

from apps.core.models import AuditableModel, SoftDeleteMixin


class SupplierType(models.TextChoices):
    DEPOT = "depot", "Depot"
    EQUIPMENT = "equipment", "Equipment"
    SERVICE = "service", "Service"
    GOVT = "govt", "Government"
    OTHER = "other", "Other"


class Supplier(SoftDeleteMixin, AuditableModel):
    """Supplier/Vendor master (ADR-024). LAST AP is auto-tracked (pain #5).

    Columns mirror the finance head's LIST-OF-SUPPLIERS master (Sept 2026),
    which is the authoritative source for the supplier model.
    """

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    supplier_type = models.CharField(max_length=16, choices=SupplierType.choices, default=SupplierType.OTHER)
    tin = models.CharField("TIN", max_length=32, blank=True)
    address = models.CharField(max_length=255, blank=True)
    contact_no = models.CharField(max_length=255, blank=True)
    owner_name = models.CharField("Owner/Representative/President", max_length=255, blank=True)
    email = models.EmailField("Email Address", blank=True)
    contact_person = models.CharField("Contact Person", max_length=255, blank=True)
    position = models.CharField("Position", max_length=128, blank=True)
    attachments_required = models.BooleanField(
        "Attachment Needed (BIR-COR, DTI/SEC, Business Permit)", default=False
    )
    # Per-vendor numbering: previous RFP for this supplier (ADR-019 gap tracking).
    last_ap = models.CharField(max_length=16, blank=True)
    default_segment = models.ForeignKey(
        "foundation.Segment", null=True, blank=True, on_delete=models.SET_NULL, related_name="suppliers"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} {self.name}"


class RFPDocument(AuditableModel):
    """Request for Payment (ACCTG-FOR-012). The JE is embedded in the RFP
    (ADR-018); it is NOT produced by a generic posting rule."""

    ap_number = models.CharField(max_length=16, unique=True)  # A####
    last_ap = models.CharField(max_length=16, blank=True)  # per-vendor previous A####
    rfp_date = models.DateField(db_index=True)
    payee = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="rfps")
    # Mirrors the first distribution line's description (the form has no
    # separate "purpose of payment" box); used for register/detail display.
    particulars = models.CharField(max_length=500, blank=True)
    purpose = models.CharField(max_length=128, blank=True)
    segment = models.ForeignKey("foundation.Segment", on_delete=models.PROTECT, related_name="rfps")
    # Total of the DEBIT lines (the amount being paid). Credit lines balance it.
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    # ADR-018 status chain.
    status = models.CharField(max_length=24, default="draft", db_index=True)
    # Dr/Cr distribution lines (ADR-023): every line names a COA account and
    # its side; debits must equal credits so the posted JE balances.
    conso = models.ForeignKey(
        "CONSOBatch", null=True, blank=True, on_delete=models.PROTECT, related_name="rfps"
    )
    conso_line_no = models.PositiveSmallIntegerField(null=True, blank=True)
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="rfps"
    )
    created_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    checked_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_by_acctg = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_by_fin = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_by_cnr = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-rfp_date", "-ap_number"]

    def __str__(self):
        return f"{self.ap_number} {self.payee} {self.amount} ({self.status})"


class RFPLine(models.Model):
    """One Dr/Cr distribution line of the RFP (ADR-023). The sum of debit
    lines is the RFP total; the sum of credit lines must equal it. Each line
    names the COA account and its side — the posted JE is built exactly from
    these lines."""

    class Side(models.TextChoices):
        DEBIT = "dr", "Dr"
        CREDIT = "cr", "Cr"

    rfp = models.ForeignKey(RFPDocument, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveIntegerField()
    side = models.CharField(max_length=2, choices=Side.choices, default=Side.DEBIT)
    segment = models.ForeignKey("foundation.Segment", on_delete=models.PROTECT, related_name="rfp_lines")
    account = models.ForeignKey("foundation.Account", on_delete=models.PROTECT, related_name="rfp_lines")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["rfp", "line_no"]
        unique_together = ("rfp", "line_no")

    def __str__(self):
        return f"{self.rfp.ap_number} L{self.line_no} {self.account.code} {self.amount}"


class CONSOBatch(AuditableModel):
    """Consolidated voucher batch (ADR-018): RFPs are batched, reviewed by the
    Accounting Head, and on approval ALL RFPs in the batch post their JEs
    atomically (POSTING_RULES 7.3)."""

    batch_no = models.CharField(max_length=16, unique=True)  # e.g. CONSO-YYYY-##
    conso_date = models.DateField(db_index=True)
    status = models.CharField(max_length=16, default="open")  # open / reviewed / posted / rejected
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    reviewed_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-conso_date", "-batch_no"]

    def __str__(self):
        return f"{self.batch_no} {self.status} {self.total_amount}"


class CheckVoucher(AuditableModel):
    """Check Voucher (ACCTG-FOR-010). Clears AP with optional WHT split
    (POSTING_RULES 7.4). Created before the check is signed/released."""

    cv_number = models.CharField(max_length=16, unique=True)  # CV-YYYY-####
    cv_date = models.DateField(db_index=True)
    rfp = models.ForeignKey(RFPDocument, on_delete=models.PROTECT, related_name="cv", null=True, blank=True)
    payee = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="cv")
    bank_account = models.ForeignKey(
        "foundation.Account", on_delete=models.PROTECT, related_name="cv",
        limit_choices_to={"code__startswith": "100"},
    )
    gross_amount = models.DecimalField(max_digits=18, decimal_places=2)
    withheld_tax = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    net_amount = models.DecimalField(max_digits=18, decimal_places=2)
    check_no = models.CharField(max_length=32, blank=True)
    # lifecycle: created -> signed (CNR) -> released (Quibs) -> cleared
    status = models.CharField(max_length=16, default="created")
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="cv"
    )
    signed_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    released_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-cv_date", "-cv_number"]

    def __str__(self):
        return f"{self.cv_number} {self.payee} net {self.net_amount} ({self.status})"


class AdvanceToEmployee(AuditableModel):
    """Advances to Employees ledger (ADR-021). Tracks the standing advance
    (default P20,000 clearing from every RFP of an officer/employee) through
    grant -> liquidation -> aging. Also covers salary advances and
    reimbursements."""

    EMPLOYEE = "employee"
    OFFICER = "officer"
    SALARY_ADVANCE = "salary_advance"
    REIMBURSEMENT = "reimbursement"

    KIND_CHOICES = [
        (EMPLOYEE, "Employee reimbursement"),
        (OFFICER, "Officer advance"),
        (SALARY_ADVANCE, "Salary advance"),
        (REIMBURSEMENT, "Reimbursement"),
    ]

    employee_name = models.CharField(max_length=255)
    rfp = models.ForeignKey(RFPDocument, null=True, blank=True, on_delete=models.SET_NULL, related_name="advances")
    kind = models.CharField(max_length=24, choices=KIND_CHOICES, default=EMPLOYEE)
    segment = models.ForeignKey("foundation.Segment", on_delete=models.PROTECT, related_name="advances")
    granted_date = models.DateField(db_index=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    # Lifecycle: granted -> liquidated (with receipts) -> closed (refund/top-up).
    status = models.CharField(max_length=16, default="granted")
    liquidated_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    liquidated_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-granted_date"]

    @property
    def outstanding(self):
        return self.amount - self.liquidated_amount

    def __str__(self):
        return f"{self.employee_name} {self.amount} {self.status}"