"""Fixed Assets bounded context (BUILD-PLAN Phase 7).

Covers the asset register with category lives (tankers 10-15y, boom trucks
10y, vehicles 5-7y, building 15-20y, furniture 5y, office equip 3-5y),
straight-line depreciation (POSTING_RULES §9.2), disposal (POSTING_RULES
§9.3), the depreciation schedule with fully-depreciated-still-in-use flag
(Alywin pain), and the Asset↔Vehicle link (vehicles ARE assets — 17000-18650).

Posting contracts (POSTING_RULES §9):
  9.1 acquisition:  Dr 17xxx-19xxx Asset Account | Cr AP/Cash/Loans
  9.2 depreciation:  Dr 50110/51173/616xx Dep Exp | Cr Accum Dep 17xxx
  9.3 disposal:      Dr Cash (proceeds) + Dr Accum Dep | Cr Asset + Cr Gain
                     (43070-43096); loss leg Dr 6xxx instead of gain.
"""

from decimal import Decimal

from django.db import models

from apps.core.models import AuditableModel


class AssetStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    FULLY_DEPRECIATED = "fully_depreciated", "Fully Depreciated (still in use)"
    DISPOSED = "disposed", "Disposed"


class AssetCategory(AuditableModel):
    """Asset classification with useful life and account defaults.

    Per-category lives from BUILD-PLAN Phase 7. Accounts follow the
    POSTING_RULES §9.2 category mapping; a category carries segment-specific
    defaults so assets created for DHPP/DMIE/OPS pick the right COA accounts.
    """

    code = models.CharField(max_length=32, unique=True)  # TANKER, BOOM_TRUCK, ...
    name = models.CharField(max_length=128)
    useful_life_years = models.PositiveSmallIntegerField()
    # Default accounts (resolved from COA on save by code prefix where needed).
    asset_account = models.ForeignKey(
        "foundation.Account", on_delete=models.PROTECT, related_name="asset_categories_asset"
    )
    depreciation_expense_account = models.ForeignKey(
        "foundation.Account", on_delete=models.PROTECT, related_name="asset_categories_dep_exp"
    )
    accumulated_dep_account = models.ForeignKey(
        "foundation.Account", on_delete=models.PROTECT, related_name="asset_categories_accum"
    )
    segment = models.ForeignKey(
        "foundation.Segment", null=True, blank=True, on_delete=models.SET_NULL, related_name="asset_categories"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} ({self.useful_life_years}y)"


class Asset(AuditableModel):
    """One fixed asset in the register (ADR-xxx Phase 7).

    The acquisition journal debits the asset account 17xxx-19xxx and credits
    the funding source (AP, Cash, or Loans). Depreciation accrues monthly via
    DepreciationSchedule; disposal closes the register row (POSTING_RULES 9.3).
    """

    asset_no = models.CharField(max_length=32, unique=True)  # FA-YYYY-####
    name = models.CharField(max_length=255)
    category = models.ForeignKey(AssetCategory, on_delete=models.PROTECT, related_name="assets")
    segment = models.ForeignKey("foundation.Segment", on_delete=models.PROTECT, related_name="assets")
    acquisition_date = models.DateField(db_index=True)
    cost = models.DecimalField(max_digits=18, decimal_places=2)
    residual_value = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    # COA accounts (POSTING_RULES §9.2 mapping, overridable per asset).
    asset_account = models.ForeignKey(
        "foundation.Account", on_delete=models.PROTECT, related_name="assets_asset"
    )
    depreciation_expense_account = models.ForeignKey(
        "foundation.Account", on_delete=models.PROTECT, related_name="assets_dep_exp"
    )
    accumulated_dep_account = models.ForeignKey(
        "foundation.Account", on_delete=models.PROTECT, related_name="assets_accum_dep"
    )
    # Funding source (9.1): one of AP / Cash / Loans.
    funding_source = models.CharField(max_length=16, default="cash")  # ap / cash / loan
    financed_loan_reference = models.CharField(max_length=64, blank=True)
    acquisition_fees = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    acquisition_journal = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="assets_acquired"
    )
    status = models.CharField(max_length=24, choices=AssetStatus.choices, default=AssetStatus.ACTIVE, db_index=True)
    # Asset↔Vehicle link: vehicles are assets (17000-18650).
    vehicle = models.OneToOneField(
        "fleet.Vehicle", null=True, blank=True, on_delete=models.SET_NULL, related_name="asset"
    )

    class Meta:
        ordering = ["-acquisition_date", "asset_no"]

    @property
    def depreciable_base(self) -> Decimal:
        return self.cost - self.residual_value

    @property
    def monthly_depreciation(self) -> Decimal:
        from apps.core.money import money

        months = self.category.useful_life_years * 12
        return money(self.depreciable_base / months)

    @property
    def accumulated_depreciation(self) -> Decimal:
        from django.db.models import Sum

        return (
            self.depreciation_schedule.filter(journal_entry__status="posted").aggregate(
                total=Sum("amount")
            )["total"]
        ) or Decimal("0.00")

    @property
    def net_book_value(self) -> Decimal:
        return self.cost - self.accumulated_depreciation

    @property
    def is_fully_depreciated(self) -> bool:
        return self.accumulated_depreciation >= self.depreciable_base

    def __str__(self):
        return f"{self.asset_no} {self.name} NBV {self.net_book_value} ({self.status})"


class DepreciationSchedule(AuditableModel):
    """One monthly depreciation row for an asset (straight-line, §9.2).

    Generated for each month from acquisition to end-of-life. The row is
    posted (journal_entry set, status=posted) when its JE is created. The
    `is_still_in_use` flag marks fully-depreciated assets still in operation
    (Alywin's pain point: they no longer accrue but must stay in the register).
    """

    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="depreciation_schedule")
    period_start = models.DateField(db_index=True)  # first day of month
    period_end = models.DateField()  # last day of month
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="depreciation_rows"
    )
    status = models.CharField(max_length=16, default="pending")  # pending / posted
    is_still_in_use = models.BooleanField(default=True)

    class Meta:
        unique_together = ("asset", "period_start")
        ordering = ["asset", "period_start"]

    def __str__(self):
        return f"Dep {self.asset.asset_no} {self.period_start}→{self.period_end} {self.amount}"


class AssetDisposal(AuditableModel):
    """Asset disposal/retirement (POSTING_RULES §9.3).

        Dr Cash (proceeds) + Dr Accum Dep | Cr Asset (cost) + Cr Gain 43070-96
        (loss: Dr 6xxx instead of the gain line).
    """

    asset = models.OneToOneField(Asset, on_delete=models.PROTECT, related_name="disposal")
    disposal_date = models.DateField(db_index=True)
    proceeds = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    reason = models.CharField(max_length=255, blank=True)
    gain = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="asset_disposals"
    )
    status = models.CharField(max_length=16, default="draft")  # draft / posted

    class Meta:
        ordering = ["-disposal_date"]

    def __str__(self):
        return f"Disposal {self.asset.asset_no} {self.disposal_date} proceeds {self.proceeds}"
