"""Foundation: legal entities, segments, fiscal calendar, and the COA.

Modeled from ADR-003 (segment-first chart), ADR-013 (Tue-Mon cycles) and the
canonical 5-digit COA in /excel-files/COA-STMIET-2026.xlsx:

    [1][2][3][4][5]  where digit 5 (and the 10s group) encodes the segment:
    00/03/06...90/93/96 -> 0x00=DHPP, 0x03=DMIE, 0x06=OPS, 0x90/93/96 splits.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import AuditableModel, SoftDeleteMixin

# Segment tags (ADR-003). 0=DHPP, 3=DMIE, 6=OPS, and the 4th segment (STPC) is
# carried via due-from/payable placeholder accounts 15500/25500 rather than a
# COA suffix.
SEGMENT_CHOICES = [
    ("DHPP", "DHPP (0x00/0x03/0x06 base)"),
    ("DMIE", "DMIE"),
    ("OPS", "OPS"),
    ("ALL", "Shared / consolidated"),
]


class Company(SoftDeleteMixin, AuditableModel):
    """Legal entities the books are kept for (ADR-014 master data)."""

    class CashCycleType(models.TextChoices):
        WEEKLY = "weekly", "Weekly (Tue->Mon)"
        MONTHLY = "monthly", "Monthly (calendar)"

    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=255)
    tin = models.CharField("TIN", max_length=32, blank=True)
    address = models.CharField(max_length=255, blank=True)
    rdo_code = models.CharField("RDO", max_length=8, blank=True)
    # Cash-cycle shape (ADR-013). STMIET runs the classic weekly Tue->Mon sheet;
    # other companies may adopt a monthly calendar cycle or different weekdays.
    cash_cycle = models.CharField(
        max_length=16, choices=CashCycleType.choices, default=CashCycleType.WEEKLY
    )
    cycle_start_weekday = models.PositiveSmallIntegerField(default=1)  # 1 = Tuesday
    cycle_end_weekday = models.PositiveSmallIntegerField(default=0)  # 0 = Monday

    class Meta:
        verbose_name_plural = "companies"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class Segment(SoftDeleteMixin, AuditableModel):
    """Business segments (cost centers) used in GL reporting (ADR-003)."""

    code = models.CharField(max_length=8, unique=True)
    name = models.CharField(max_length=64)
    coa_key_digit = models.PositiveSmallIntegerField(
        "COA key digit (last digit / 10s group)", null=True, blank=True
    )
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="segments")

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class FiscalYear(AuditableModel):
    """One fiscal year for a company."""

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="fiscal_years")
    code = models.CharField(max_length=9)  # "2026", "FY2026"
    start_date = models.DateField()
    end_date = models.DateField()
    is_closed = models.BooleanField(default=False)

    class Meta:
        unique_together = ("company", "code")
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.company.code} {self.code}"


class FiscalPeriod(AuditableModel):
    """Accounting period (month) within a fiscal year.

    13th period reserved for year-end adjustments, per the classic enterprise
    close cycle in BUILD-PLAN Phase 8.
    """

    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.PROTECT, related_name="periods")
    period_no = models.PositiveSmallIntegerField()  # 1..13
    # ADR-013: daily-arbitrary cycles (Tue->Mon) are tracked on journal entries
    # themselves; the period is the monthly window that contains them.
    start_date = models.DateField()
    end_date = models.DateField()
    is_closed = models.BooleanField(default=False, db_index=True)

    class Meta:
        unique_together = ("fiscal_year", "period_no")
        ordering = ["period_no"]

    def __str__(self):
        return f"{self.fiscal_year} P{self.period_no}"


class AccountType(models.TextChoices):
    ASSET = "asset", "Asset"
    LIABILITY = "liability", "Liability"
    EQUITY = "equity", "Equity"
    REVENUE = "revenue", "Revenue"
    EXPENSE = "expense", "Expense"
    CONTRA_ASSET = "contra_asset", "Contra-Asset"
    CONTRA_LIABILITY = "contra_liability", "Contra-Liability"
    CONTRA_REVENUE = "contra_revenue", "Contra-Revenue"
    CONTRA_EQUITY = "contra_equity", "Contra-Equity"


NORMAL_BALANCE = {
    AccountType.ASSET: "debit",
    AccountType.CONTRA_ASSET: "credit",
    AccountType.LIABILITY: "credit",
    AccountType.CONTRA_LIABILITY: "debit",
    AccountType.EQUITY: "credit",
    AccountType.CONTRA_EQUITY: "debit",
    AccountType.REVENUE: "credit",
    AccountType.CONTRA_REVENUE: "debit",
    AccountType.EXPENSE: "debit",
}


class Account(SoftDeleteMixin, AuditableModel):
    """One chart-of-accounts node (5-digit code, hierarchy, segment key).

    ADR-003: the last digit is the segment tag for 1xxx/2xxx rollups; for
    5-digit codes the segment lives in the final digit (0=DHPP, 3=DMIE, 6=OPS).
    """

    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=24, choices=AccountType.choices)
    normal_balance = models.CharField(max_length=8, blank=True)
    segment = models.CharField(max_length=8, choices=SEGMENT_CHOICES, default="ALL")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    is_control = models.BooleanField("header account", default=False)
    is_postable = models.BooleanField(default=True)
    # STMIET extensions (from COA workbook + REVIEW-ISSUES register):
    # - is_cash_equivalent, is_bank (treasury), is_receivable, is_payable
    # are needed for AR/AP bridge; keep minimal here, extend in later phases.
    description = models.TextField(blank=True)
    # COA workbook (COA-STMIET-2026.xlsx) columns D-G, carried verbatim so the
    # Trial Balance export reproduces the workbook's CLASSIFICATION / CATEGORY /
    # Sub-Accounts / Major Accounts columns exactly.
    classification = models.CharField(max_length=64, blank=True)
    category = models.CharField(max_length=64, blank=True)
    sub_accounts = models.CharField(max_length=64, blank=True)
    major_accounts = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["code"]

    def save(self, *args, **kwargs):
        if not self.normal_balance:
            self.normal_balance = NORMAL_BALANCE.get(self.account_type, "debit")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} {self.name}"

    @classmethod
    def segment_for_code(cls, code: str) -> str:
        """Derive segment tag from the 5-digit code per ADR-003."""
        digits = code.zfill(5)
        last = int(digits[-1])
        if last in (0, 3, 6):
            return {0: "DHPP", 3: "DMIE", 6: "OPS"}[last]
        return "ALL"


class SegmentAccountMap(AuditableModel):
    """Data-driven segment default accounts (Phase 2).

    Replaces the hardcoded per-segment account dicts in ap/assets services with
    COA master links: a `role` names the accounting intent (ap, cash, loans,
    disposal gain/loss, withholding tax) and each (segment, role) resolves to
    exactly one postable COA account. Rows are seeded from the COA importer, so
    account codes exist only as DB data; services never hardcode COA codes.
    """

    ROLE_AP = "ap"
    ROLE_AP_WHT = "ap_wht"
    ROLE_CASH = "cash"
    ROLE_LOANS = "loans"
    ROLE_DISPOSAL_GAIN = "disposal_gain"
    ROLE_DISPOSAL_LOSS = "disposal_loss"
    ROLE_INCOME_TAX = "income_tax"
    ROLE_VAT_OUTPUT = "vat_output"
    ROLE_OPENING_EQUITY = "opening_equity"
    ROLE_CHOICES = [
        (ROLE_AP, "Accounts payable (CV Dr)"),
        (ROLE_AP_WHT, "Withholding tax expanded (CV Cr)"),
        (ROLE_CASH, "Cash default (proceeds / funding)"),
        (ROLE_LOANS, "Loans payable (financed acquisition)"),
        (ROLE_DISPOSAL_GAIN, "Gain on asset disposal"),
        (ROLE_DISPOSAL_LOSS, "Loss on asset disposal"),
        (ROLE_INCOME_TAX, "Income tax payable (provision Cr)"),
        (ROLE_VAT_OUTPUT, "Output VAT payable (SI extraction Cr)"),
        (ROLE_OPENING_EQUITY, "Opening balance plug (asset register seeding)"),
    ]

    segment = models.ForeignKey(Segment, on_delete=models.PROTECT, related_name="account_maps")
    role = models.CharField(max_length=24, choices=ROLE_CHOICES)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("segment", "role")
        ordering = ["segment__code", "role"]

    def __str__(self):
        return f"{self.segment.code}:{self.role} -> {self.account.code}"


def resolve_segment_account(segment, role) -> Account:
    """The COA account a segment uses for an accounting role (Phase 2).

    The data lives in SegmentAccountMap (seeded by import_coa); services pass
    the segment and role, never a hardcoded COA code. A missing row is a master
    data problem and fails loudly.
    """
    from apps.core.exceptions import ValidationError

    code = segment.code if hasattr(segment, "code") else str(segment)
    try:
        mapping = SegmentAccountMap.objects.get(segment__code=code, role=role)
    except SegmentAccountMap.DoesNotExist as exc:
        raise ValidationError(
            f"Segment {code} has no mapped account for role '{role}'."
        ) from exc
    return mapping.account


class UserProfile(AuditableModel):
    """Holds the approval role of a login (ADR-020, ADR-036).

    Three positions drive every approval:
      - `staff`  : accounting assistant / bookkeeper / accounting staff /
                   cashier — prepares and submits documents (same access).
      - `head`   : the Accounting & Finance Head (Alywin Aidan D. Baje in
                   the demo seed). He checks, and approves as accounting
                   head AND finance head — every RFP, every CV.
      - `coo`    : the COO, who acts as CNR approver for RFPs above P100k.

    The "My Approvals" inbox and the role gates on the approve endpoints
    are driven exclusively by this mapping.
    """

    class ApprovalRole(models.TextChoices):
        STAFF = "staff", "Accounting Staff / Assistant / Bookkeeper / Cashier"
        HEAD = "head", "Accounting & Finance Head"
        COO = "coo", "COO (CNR)"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    approval_role = models.CharField(
        max_length=16, choices=ApprovalRole.choices, blank=True, default=""
    )

    class Meta:
        ordering = ["user__username"]

    def __str__(self):
        return f"{self.user} — {self.get_approval_role_display() or 'no role'}"

