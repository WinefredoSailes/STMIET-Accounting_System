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

from apps.core.constants import COST_CENTER_MAX_LENGTH
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


class ReconFrequency(models.TextChoices):
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"


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
    # Bank Reconciliation Statement cadence (default monthly; flip per
    # account to weekly once the process is stable).
    reconciliation_frequency = models.CharField(
        max_length=8, choices=ReconFrequency.choices, default=ReconFrequency.MONTHLY,
    )

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
    """Bank reconciliation per period per bank account (ADR-026 + statement module).

    Weekly path: one row per weekly cycle (``cycle`` + ``period_*`` = cycle
    bounds, ``frequency='weekly'``). Monthly path (default): ``cycle`` is the
    anchor (last weekly cycle in the month) while ``period_start/end`` span
    the calendar month. Target: <15 min/bank.
    """

    cycle = models.ForeignKey(WeeklyCashCycle, on_delete=models.PROTECT, related_name="reconciliations")
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="reconciliations")
    # Statement period (calendar month for monthly; cycle bounds for weekly).
    period_start = models.DateField(null=True, blank=True, db_index=True)
    period_end = models.DateField(null=True, blank=True, db_index=True)
    frequency = models.CharField(
        max_length=8, choices=ReconFrequency.choices, default=ReconFrequency.MONTHLY,
    )
    book_balance = models.DecimalField(max_digits=18, decimal_places=2)
    bank_statement_balance = models.DecimalField(max_digits=18, decimal_places=2)
    difference = models.DecimalField(max_digits=18, decimal_places=2)
    # Difference breakdown (legacy aggregate root-cause buckets).
    typo_adjustment = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    pop_adjustment = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    cashier_adjustment = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    unresolved = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    # --- Bank Reconciliation Statement fields --------------------------------
    # Unadjusted balances are captured ONCE (GL snapshot for books, statement
    # figure for bank) and then locked; later GL postings must not move them.
    unadjusted_book_balance = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
    )
    unadjusted_bank_balance = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
    )
    is_balances_captured = models.BooleanField(default=False)
    # Computed from the statement formula (BankReconLine rows).
    adjusted_bank_balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    adjusted_book_balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    # Status: legacy (open / resolved / escalated) + statement workflow
    # (draft / submitted / pre_approved / approved).
    status = models.CharField(max_length=16, default="open")
    reconciled_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reconciled_at = models.DateTimeField(null=True, blank=True)
    # Statement approval: staff prepares -> submitted -> head pre-approves
    # (temporary) -> head final-approves.
    prepared_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    prepared_at = models.DateTimeField(null=True, blank=True)
    pre_approved_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    pre_approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_note = models.TextField(blank=True)

    class Meta:
        unique_together = ("cycle", "bank_account")
        ordering = ["cycle", "bank_account"]
        constraints = [
            models.UniqueConstraint(
                fields=["bank_account", "period_start", "period_end"],
                name="uniq_recon_bank_period",
            ),
        ]

    def __str__(self):
        return f"Recon {self.cycle} {self.bank_account}: diff {self.difference}"

    @property
    def variance(self) -> Decimal:
        """Adjusted bank balance minus adjusted book balance (must be 0)."""
        return (self.adjusted_bank_balance or Decimal("0.00")) - (
            self.adjusted_book_balance or Decimal("0.00")
        )

    @property
    def is_locked(self) -> bool:
        return self.status == "approved"


class BankReconLine(AuditableModel):
    """One statement line of a bank reconciliation (formula requirement c).

    Bank side: Deposit in Transit / Bank Error (add) / Outstanding Checks /
    Bank Error (less). Book side: Bank Interest Earned / Book Error (add) /
    Bank Service Charge / NSF-DAIF Charges / Book Error (less).
    """

    class Side(models.TextChoices):
        BANK = "bank", "Bank Side"
        BOOK = "book", "Book Side"

    class Category(models.TextChoices):
        DEPOSIT_IN_TRANSIT = "deposit_in_transit", "Deposit in Transit"
        BANK_ERROR_ADD = "bank_error_add", "Bank Error (Add)"
        OUTSTANDING_CHECKS = "outstanding_checks", "Outstanding Checks"
        BANK_ERROR_LESS = "bank_error_less", "Bank Error (Less)"
        BANK_INTEREST_EARNED = "bank_interest_earned", "Bank Interest Earned"
        BOOK_ERROR_ADD = "book_error_add", "Book Error (Add)"
        BANK_SERVICE_CHARGE = "bank_service_charge", "Bank Service Charge"
        NSF_DAIF_CHARGES = "nsf_daif_charges", "NSF/DAIF Charges"
        BOOK_ERROR_LESS = "book_error_less", "Book Error (Less)"

    #: Which categories belong to which side of the statement.
    BANK_CATEGORIES = frozenset({
        "deposit_in_transit", "bank_error_add",
        "outstanding_checks", "bank_error_less",
    })
    BOOK_CATEGORIES = frozenset({
        "bank_interest_earned", "book_error_add",
        "bank_service_charge", "nsf_daif_charges", "book_error_less",
    })
    #: Categories that ADD to their side's unadjusted balance.
    ADD_CATEGORIES = frozenset({
        "deposit_in_transit", "bank_error_add",
        "bank_interest_earned", "book_error_add",
    })

    recon = models.ForeignKey(BankReconciliation, on_delete=models.CASCADE, related_name="lines")
    side = models.CharField(max_length=4, choices=Side.choices)
    category = models.CharField(max_length=24, choices=Category.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    reference = models.CharField(max_length=128, blank=True)  # check #, deposit slip #, etc.
    description = models.TextField(blank=True)
    match_status = models.CharField(
        max_length=16, default="unmatched",
        choices=[
            ("unmatched", "Unmatched"),
            ("matched", "Matched"),
            ("adjusted", "Adjusted"),
        ],
    )
    adjustment_je = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="bank_recon_lines",
    )

    class Meta:
        ordering = ["recon", "side", "category", "id"]

    def __str__(self):
        return f"{self.recon_id} {self.side}/{self.category} {self.amount}"


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
    payable_account = models.ForeignKey(
        "foundation.Account",
        on_delete=models.PROTECT,
        related_name="pcf_funds_payable",
        null=True,
        blank=True,
        help_text="Payable credit account for PCF replenishment JEs (null = default 21100)",
    )
    company = models.ForeignKey("foundation.Company", on_delete=models.PROTECT, related_name="pcf_funds")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["fund_code"]

    def __str__(self):
        return f"{self.name or self.fund_code} ({self.imprest_amount})"

    def get_payable_account(self):
        """Return the payable account for this fund (override or default 21100)."""
        if self.payable_account_id:
            return self.payable_account
        from apps.foundation.models import Account
        return Account.objects.get(code="21100")


class PCFReplenishment(AuditableModel):
    """PCF replenishment request and posting."""

    fund = models.ForeignKey(PettyCashFund, on_delete=models.PROTECT, related_name="replenishments")
    request_date = models.DateField(db_index=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    # ACCTG-FOR-002 PAYEE INFORMATION: who received / is reimbursed.
    payee_name = models.CharField(max_length=255, blank=True)
    reference = models.CharField(max_length=64, blank=True)
    # Who requested the petty cash
    requested_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Customer/client name for whom the petty cash is intended
    customer_name = models.CharField("Customer Name", max_length=255, blank=True)
    # ACCTG-FOR-002 voucher number (ADR-032, per company/year: PCV-2026-0001).
    voucher_no = models.CharField(max_length=32, blank=True, db_index=True)
    # ACCTG-FOR-002 cost centre / reference (ADR-032, matching the RFP
    # "Cost Center/Ref" concept — the same display value, kept in sync via
    # COST_CENTER_MAX_LENGTH).
    cost_center = models.CharField(
        "Cost Center/Ref",
        max_length=COST_CENTER_MAX_LENGTH,
        blank=True,
        help_text="e.g. OS, GEN-FUEL",
    )
    # Expense breakdown from liquidation receipts
    expenses = models.JSONField(default=list)  # [{account_code, amount, description}]
    # Auto-CONSO integration (ADR-038 §7c): approval batches the replenishment
    # to a CONSO batch; posting happens when the batch is posted.
    conso = models.ForeignKey(
        "ap.CONSOBatch", null=True, blank=True, on_delete=models.PROTECT, related_name="pcf_replenishments"
    )
    conso_line_no = models.PositiveSmallIntegerField(null=True, blank=True)
    # A check voucher may be issued against a posted replenishment to document
    # the treasury drawdown that settles it (ACCTG-FOR-010).
    cv = models.ForeignKey(
        "ap.CheckVoucher", null=True, blank=True,
        on_delete=models.PROTECT, related_name="pcf_cvs"
    )
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="pcf_replenishments"
    )
    status = models.CharField(
        max_length=16, default="draft",
        choices=[
            ("draft", "Draft"),
            ("requested", "Requested"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("posted", "Posted"),
        ],
    )  # draft / requested / approved / rejected / posted
    approved_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="rejected_pcf_replenishments"
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-request_date"]

    def __str__(self):
        return f"Replenish {self.fund} {self.amount} ({self.status})"


class InterAccountTransfer(AuditableModel):
    """Inter-account transfer (ADR-030): Dr Cash-To | Cr Cash-From; purpose required."""

    transfer_date = models.DateField(db_index=True)
    voucher_no = models.CharField(max_length=32, blank=True, db_index=True)
    from_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="transfers_out")
    to_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="transfers_in")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    purpose = models.CharField(max_length=500)
    reference = models.CharField(max_length=64, blank=True)
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="transfers"
    )
    initiated_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # ADR-030 lifecycle (same shape as JE/RFP/CV): requested (preparer, DRAFT
    # JE) -> submitted (awaiting head) -> approved (JE posted to GL), with a
    # rejected branch the preparer revises and resubmits.
    status = models.CharField(
        max_length=16, default="requested",
        choices=[
            ("requested", "Requested"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
    )
    approved_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_transfers"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="rejected_transfers"
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_note = models.TextField(blank=True)
    check_no = models.CharField(max_length=32, blank=True, help_text="Check number (optional)")
    cost_center = models.CharField(
        max_length=64, blank=True, help_text="Cost center / ref (e.g. OS — offsite, GEN-FUEL)",
    )

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