"""Cash & Banks bounded context (BUILD-PLAN Phase 4).

Covers treasury operations per ADR-026/027/028/030/031:
  - BankAccount master: 12 accounts / 9 banks + PCF&COH, ADB maintaining balances
  - Weekly Tue→Mon cash cycle sheet (11 columns, 8 activity rows)
  - Bank reconciliation per cycle (target <15 min/bank)
  - Petty Cash: 3 funds (Leaslyn/Treasury/Alywin), 85% replenishment trigger
  - Inter-account transfer (Dr Cash-To | Cr Cash-From; purpose required)
  - Cash Flow Statement from cycles (identity: Net Inc = End − Beg + ADB adj)
  - Check disbursement tracking (CV lifecycle)
  - COLLECTIBLES + CASH SHORT worksheets from posted data

Deposit = state change, NO JE (ADR-016). Cash short/excess requires cause + Alywin approval (ADR-030).
"""

from decimal import Decimal

from django.db import models

from apps.core.models import AuditableModel, SoftDeleteMixin


class BankAccountType(models.TextChoices):
    SAVINGS = "savings", "Savings"
    CHECKING = "checking", "Checking"
    PCF_COH = "pcf_coh", "Petty Cash & Cash on Hand"


class ActivityType(models.TextChoices):
    """ADR-028 cycle activity rows. Each posted transaction maps to exactly one
    activity type; inter-account transfers are tracked but excluded from CF
    (ADR-031: cash-to-cash has no P&L impact)."""

    COLLECTION_DIST = "collection_dist", "Collections from Distribution"
    OTHER_COLLECTION = "other_collection", "Other Cash Collections"
    BORROWED = "borrowed", "Funds Borrowed from other accounts"
    SUPPLIER_PAYMENT = "supplier_payment", "Payments to Supplier of Petroleum"
    RFP_AP = "rfp_ap", "RFP of Accounts Payable [incl loans]"
    CAPEX = "capex", "Disbursement for CAPEX"
    PCF_REPLEN = "pcf_replen", "Cash Withdrawn for PCF Replenishment"
    INTERACCT_TRANSFER = "interacct_transfer", "Inter-account fund transfer"
    OTHER_PAYMENT = "other_payment", "Other Cash payments"
    LOAN_CLEARED = "loan_cleared", "Checks Cleared for Loan / Fuel"


class BankAccount(SoftDeleteMixin, AuditableModel):
    """One bank account or PCF/COH fund (ADR-026). 12 accounts / 9 banks + PCF&COH.

    Banks are COMPANY-LEVEL master data: a shared bank (checking/savings) serves
    every segment of the company, and its activity is attributed per posted GL
    segment inside each segment's cash cycle sheet (ADR-028).
    """

    code = models.CharField(max_length=16, unique=True)  # e.g. PNB-CHK, PNB-SAV
    name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=16, choices=BankAccountType.choices)
    bank_name = models.CharField(max_length=128, blank=True)
    bank_code = models.CharField(max_length=16, blank=True)  # e.g. PNB, BDO, 1VB
    account_number = models.CharField(max_length=64, blank=True, default="", db_index=True)
    branch = models.CharField(max_length=128, blank=True)
    signatories = models.JSONField(default=list, blank=True)
    gl_account = models.OneToOneField(
        "foundation.Account", on_delete=models.PROTECT, related_name="bank_account"
    )
    company = models.ForeignKey("foundation.Company", on_delete=models.PROTECT, related_name="bank_accounts")
    # ADB maintaining balance requirement
    adb_required = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("5000.00"))
    # For PCF funds: custodian
    custodian = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["bank_name", "code"]

    def __str__(self):
        return f"{self.code} ({self.bank_name})"


class WeeklyCashCycle(AuditableModel):
    """Weekly cash cycle Tue→Mon (ADR-013/028). One row per cycle per segment.
    Derived from posted JEs; 11 columns (9 banks + PCF&COH), 8 activity rows.
    """

    cycle_start = models.DateField(db_index=True)  # Tuesday
    cycle_end = models.DateField()  # Monday
    segment = models.ForeignKey("foundation.Segment", on_delete=models.PROTECT, related_name="cash_cycles")
    # Opening balances per bank account (derived)
    # Activity rows (derived from GL):
    # 1. Collections (Dr Cash)
    # 2. Check disbursements (Cr Cash)
    # 3. Inter-account transfers in/out
    # 4. PCF replenishments
    # 5. Bank charges/interest
    # 6. Other receipts
    # 7. Other payments
    # 8. ADB adjustments
    # Closing balance = Opening + sum(activities)
    closing_balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=16, default="open")  # open / reconciled / locked
    reconciled_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reconciled_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ("cycle_start", "segment")
        ordering = ["-cycle_start"]

    def __str__(self):
        return f"Cycle {self.cycle_start}–{self.cycle_end} {self.segment}"


class CashCycleActivity(AuditableModel):
    """One ADR-028 activity row per cycle (optionally per bank). Derived from
    posted transactions, never hand-entered. Inter-account transfers are
    recorded here but excluded from the CF statement (ADR-031)."""

    cycle = models.ForeignKey(WeeklyCashCycle, on_delete=models.PROTECT, related_name="activities")
    activity_type = models.CharField(max_length=24, choices=ActivityType.choices)
    # Optional per-bank breakdown; null = segment-wide aggregate.
    bank_account = models.ForeignKey(
        BankAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="cycle_activities"
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        unique_together = ("cycle", "activity_type", "bank_account")
        ordering = ["cycle", "activity_type"]

    def __str__(self):
        return f"{self.cycle} {self.get_activity_type_display()} {self.amount}"


class BankReconciliation(AuditableModel):
    """Bank reconciliation per cycle per bank account (ADR-026).
    Target: <15 min/bank. Difference causes = typo/POP/cashier.
    """

    cycle = models.ForeignKey(WeeklyCashCycle, on_delete=models.PROTECT, related_name="reconciliations")
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="reconciliations")
    book_balance = models.DecimalField(max_digits=18, decimal_places=2)
    bank_statement_balance = models.DecimalField(max_digits=18, decimal_places=2)
    difference = models.DecimalField(max_digits=18, decimal_places=2)
    # Difference breakdown
    typo_adjustment = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    pop_adjustment = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    cashier_adjustment = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    unresolved = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=16, default="open")  # open / resolved / escalated
    reconciled_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reconciled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("cycle", "bank_account")
        ordering = ["cycle", "bank_account"]

    def __str__(self):
        return f"Recon {self.cycle} {self.bank_account}: diff {self.difference}"


class PettyCashFund(SoftDeleteMixin, AuditableModel):
    """Petty Cash fund (ADR-027). Imprest model, 85% replenishment trigger.

    Funds are data-driven (not a fixed enums set) so custodians can be added,
    removed or re-float'd without code or COA changes. Each custodian owns one
    PettyCashFund; all funds share the single company-level 'Petty Cash Fund'
    COA account (10000) via a ForeignKey, so the aggregate PCF balance always
    ties to one GL while per-custodian float + replenishment history is tracked
    on each fund row. `fund_code` is a free unique string (e.g. PCF-Ethelane);
    `custodian_name` is the human label, independent of the linked user account.
    """

    fund_code = models.CharField(max_length=24, unique=True)
    name = models.CharField(max_length=128)
    custodian_name = models.CharField("Custodian", max_length=128, blank=True)
    custodian = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="pcf_funds",
    )
    imprest_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("20000.00"))
    replenish_trigger_pct = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.8500"))
    gl_account = models.ForeignKey(
        "foundation.Account", on_delete=models.PROTECT, related_name="pcf_funds"
    )
    company = models.ForeignKey("foundation.Company", on_delete=models.PROTECT, related_name="pcf_funds")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["fund_code"]

    def __str__(self):
        return f"{self.name or self.fund_code} ({self.imprest_amount})"


class PCFReplenishment(AuditableModel):
    """PCF replenishment request and posting."""

    fund = models.ForeignKey(PettyCashFund, on_delete=models.PROTECT, related_name="replenishments")
    request_date = models.DateField(db_index=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    # ACCTG-FOR-002 PAYEE INFORMATION: who received / is reimbursed.
    payee_name = models.CharField(max_length=255, blank=True)
    reference = models.CharField(max_length=64, blank=True)
    # Expense breakdown from liquidation receipts
    expenses = models.JSONField(default=list)  # [{account_code, amount, description}]
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="pcf_replenishments"
    )
    status = models.CharField(max_length=16, default="requested")  # requested / approved / posted
    approved_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-request_date"]

    def __str__(self):
        return f"Replenish {self.fund} {self.amount} ({self.status})"


class InterAccountTransfer(AuditableModel):
    """Inter-account transfer (ADR-030): Dr Cash-To | Cr Cash-From; purpose required."""

    transfer_date = models.DateField(db_index=True)
    from_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="transfers_out")
    to_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="transfers_in")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    purpose = models.CharField(max_length=255)
    reference = models.CharField(max_length=64, blank=True)
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="transfers"
    )
    initiated_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-transfer_date"]

    def __str__(self):
        return f"Transfer {self.from_account} → {self.to_account} {self.amount}"


class CashFlowStatement(AuditableModel):
    """Cash Flow Statement generated from weekly cycles (ADR-031).
    Identity test: Net Inc = End − Beg + ADB adjustments.
    """

    period_start = models.DateField()
    period_end = models.DateField()
    # Operating activities
    collections = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    payments_to_depot = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    operating_expenses = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    gross_markup = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    # Investing activities
    asset_acquisitions = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    asset_disposals = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    # Financing activities
    loan_proceeds = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    loan_repayments = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    # Net change
    net_change = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    beginning_cash = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    ending_cash = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    adb_adjustments = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    # Identity: Net Income = Ending - Beginning + ADB
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_end"]

    @property
    def identity_holds(self) -> bool:
        """ADR-031: net_change == ending_cash - beginning_cash + adb_adjustments."""
        return (
            self.net_change
            == self.ending_cash - self.beginning_cash + self.adb_adjustments
        )

    def __str__(self):
        return f"CF {self.period_start}–{self.period_end}"


class CheckDisbursement(AuditableModel):
    """Check disbursement tracking (CV lifecycle): created → signed CNR → released Quibs → cleared."""

    cv = models.OneToOneField("ap.CheckVoucher", on_delete=models.PROTECT, related_name="disbursement")
    signed_by_cnr = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    signed_at = models.DateTimeField(null=True, blank=True)
    released_by_quibs = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    released_at = models.DateTimeField(null=True, blank=True)
    cleared_at = models.DateTimeField(null=True, blank=True)
    clearing_bank_account = models.ForeignKey(BankAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=16, default="created")  # created / signed / released / cleared

    def __str__(self):
        return f"Disbursement {self.cv.cv_number} ({self.status})"


class CollectiblesWorksheet(AuditableModel):
    """COLLECTIBLES worksheet generated from posted data (ADR-029). Two-department
    (Distribution vs F&A); gross mark-up = client paid − depot paid. NO JE.
    """

    cycle = models.ForeignKey(WeeklyCashCycle, on_delete=models.PROTECT, related_name="collectibles")
    department = models.CharField(max_length=32)  # Distribution / F&A
    client_paid = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    depot_paid = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    gross_markup = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("cycle", "department")
        ordering = ["cycle", "department"]

    def __str__(self):
        return f"Collectibles {self.cycle} {self.department}: markup {self.gross_markup}"


class CashShortExcessWorksheet(AuditableModel):
    """CASH SHORT sheet (ADR-029/030). Recon worksheet, NOT a JE: cashier expected
    vs actual variance per cycle; cause mandatory; variance needs approval before
    any adjustment JE. 63210 is 'Other Operating Expenses' — cash short needs NEW COA account.
    """

    cycle = models.ForeignKey(WeeklyCashCycle, on_delete=models.PROTECT, related_name="cash_short_excesses")
    segment = models.ForeignKey("foundation.Segment", on_delete=models.PROTECT, related_name="cash_short_excesses")
    expected_cash = models.DecimalField(max_digits=18, decimal_places=2)
    actual_cash = models.DecimalField(max_digits=18, decimal_places=2)
    variance = models.DecimalField(max_digits=18, decimal_places=2)
    cause = models.TextField(blank=True)
    cause_category = models.CharField(max_length=32, blank=True)  # typo / pop / cashier / other
    status = models.CharField(max_length=16, default="open")  # open / approved / adjusted
    approved_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approval = models.ForeignKey("workflow.ApprovalRequest", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        unique_together = ("cycle", "segment")
        ordering = ["-cycle"]

    def __str__(self):
        return f"CASH SHORT {self.cycle} {self.segment}: {self.variance}"