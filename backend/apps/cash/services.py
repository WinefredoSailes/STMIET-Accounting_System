"""Cash services: cycle sheet generation, reconciliation, PCF, transfers, CF statement.

Key rules (ADR-016/026/027/028/030/031):
  - Deposit = state change, NO JE (ADR-016)
  - Weekly Tue->Mon cycle sheet derived from GL (ADR-013/028)
  - Bank recon per cycle per bank; diff = typo + POP + cashier (ADR-026)
  - PCF 3 funds, 85% trigger, imprest model (ADR-027)
  - Inter-account transfer: Dr Cash-To | Cr Cash-From; purpose required (ADR-030)
  - CF statement identity: Net Inc = End - Beg + ADB (ADR-031)
  - CASH SHORT = recon worksheet, NOT a JE; variance needs Alywin approval (ADR-030)
"""

from datetime import date, timedelta
from decimal import Decimal
from collections import defaultdict

from django.conf import settings
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone

from apps.core.exceptions import ValidationError
from apps.core.money import money
from apps.foundation.calendar import cycle_range_for

from .models import (
    ActivityType,
    BankAccount,
    BankReconciliation,
    CashCycleActivity,
    CashFlowStatement,
    CashShortExcessWorksheet,
    CheckDisbursement,
    CollectiblesWorksheet,
    InterAccountTransfer,
    PCFReplenishment,
    PettyCashFund,
    WeeklyCashCycle,
)

# ADR-031 CF sections that take a sign (credit side) in the statement.
CF_INFLOW = {
    ActivityType.COLLECTION_DIST,
    ActivityType.OTHER_COLLECTION,
    ActivityType.BORROWED,
}
# Activities excluded from the CF statement (ADR-031): inter-account transfers.
CF_EXCLUDED = {ActivityType.INTERACCT_TRANSFER}


def _activity_sign(activity_type: str) -> int:
    """+1 inflows, -1 outflows. Inter-account transfers are excluded from CF
    but still move the cycle balance (cash leaves one bank for another)."""
    if activity_type in CF_INFLOW:
        return 1
    return -1


class CashCycleService:
    """Generates the weekly Tue->Mon cash cycle sheet from posted GL (ADR-013/028)."""

    @classmethod
    def generate_cycle(cls, segment, cycle_start: date) -> WeeklyCashCycle:
        """Build or refresh a cycle sheet from posted GL entries."""
        _, cycle_end = cycle_range_for(cycle_start, company=segment.company)
        with transaction.atomic():
            cycle, created = WeeklyCashCycle.objects.update_or_create(
                cycle_start=cycle_start,
                segment=segment,
                defaults={
                    "cycle_end": cycle_end,
                    "status": "open",
                    "closing_balance": Decimal("0.00"),
                },
            )
        cls._recompute_activities(cycle)
        return cycle

    @classmethod
    def _recompute_activities(cls, cycle: WeeklyCashCycle) -> None:
        """Derive ADR-028 activity rows from posted GL for this cycle/segment."""
        from apps.posting.models import GeneralLedger

        # Banks are company-level: every active bank of the company participates
        # in each segment's cycle sheet; the GL row's segment attributes the
        # activity to that segment's cycle.
        bank_ids = list(
            BankAccount.objects.filter(company=cycle.segment.company, is_active=True)
            .values_list("gl_account_id", flat=True)
        )
        if not bank_ids:
            return

        qs = GeneralLedger.objects.filter(
            account_id__in=bank_ids,
            segment=cycle.segment,
            entry__status="posted",
            transaction_date__gte=cycle.cycle_start,
            transaction_date__lte=cycle.cycle_end,
        )

        # (source_doc_type, side) -> ADR-028 activity type.
        activity_map = {
            ("AR", "dr"): ActivityType.COLLECTION_DIST,
            ("TRANSFER", "dr"): ActivityType.INTERACCT_TRANSFER,
            ("TRANSFER", "cr"): ActivityType.INTERACCT_TRANSFER,
            ("RFP", "cr"): ActivityType.RFP_AP,
            ("CV", "cr"): ActivityType.SUPPLIER_PAYMENT,
            ("PCF", "cr"): ActivityType.PCF_REPLEN,
            ("CAPEX", "cr"): ActivityType.CAPEX,
            ("LOAN", "cr"): ActivityType.LOAN_CLEARED,
            ("BORROW", "dr"): ActivityType.BORROWED,
        }

        totals = defaultdict(Decimal)
        net_activity = Decimal("0.00")
        for gl in qs:
            src = gl.entry.source_doc_type or "OTHER"
            amt = gl.debit or gl.credit
            side = "dr" if gl.debit else "cr"
            activity = activity_map.get((src, side), "other_collection" if side == "dr" else "other_payment")
            totals[activity] += amt
            # Cash account: a debit adds cash, a credit removes it. This nets
            # transfer in/out to zero on the closing balance (cash-to-cash).
            net_activity += amt if gl.debit else -amt

        # Persist the activity rows (ADR-028), one row per activity type.
        with transaction.atomic():
            CashCycleActivity.objects.filter(cycle=cycle).delete()
            for activity, amt in totals.items():
                if amt:
                    CashCycleActivity.objects.create(
                        cycle=cycle, activity_type=activity, amount=amt
                    )
        prev = WeeklyCashCycle.objects.filter(
            segment=cycle.segment, cycle_end__lt=cycle.cycle_start
        ).order_by("-cycle_end").first()
        opening = prev.closing_balance if prev else Decimal("0.00")
        cycle.closing_balance = opening + net_activity
        cycle.save(update_fields=["closing_balance", "updated_at"])

    @classmethod
    def generate_range(cls, segment, start_date: date, end_date: date) -> list[WeeklyCashCycle]:
        """Generate all cycles in range (weekly stepping or monthly per company)."""
        monthly = getattr(segment.company, "cash_cycle", "weekly") == "monthly"
        cycles = []
        current = start_date
        while current <= end_date:
            cycle_start, cycle_end = cycle_range_for(current, company=segment.company)
            if cycle_start > end_date:
                break
            cycles.append(cls.generate_cycle(segment, cycle_start))
            if monthly:
                if cycle_start.month == 12:
                    current = date(cycle_start.year + 1, 1, 1)
                else:
                    current = date(cycle_start.year, cycle_start.month + 1, 1)
            else:
                current = cycle_start + timedelta(days=7)
        return cycles


class BankReconService:
    """Bank reconciliation per cycle per bank (ADR-026)."""

    @classmethod
    def reconcile(
        cls,
        *,
        cycle: WeeklyCashCycle,
        bank_account: BankAccount,
        bank_statement_balance,
        user=None,
    ) -> BankReconciliation:
        """Create or update reconciliation for a cycle/bank."""
        from apps.posting.models import GeneralLedger

        book_bal = (
            GeneralLedger.objects.filter(
                account=bank_account.gl_account,
                segment=cycle.segment,
                entry__status="posted",
                transaction_date__lte=cycle.cycle_end,
            ).aggregate(
                bal=Sum("debit") - Sum("credit")
            )["bal"]
        ) or Decimal("0.00")

        bank_stmt = money(bank_statement_balance)
        diff = bank_stmt - book_bal

        recon, _ = BankReconciliation.objects.update_or_create(
            cycle=cycle,
            bank_account=bank_account,
            defaults={
                "book_balance": book_bal,
                "bank_statement_balance": bank_stmt,
                "difference": diff,
                "status": "resolved" if diff == 0 else "open",
                "reconciled_by": user,
                "reconciled_at": timezone.now() if diff == 0 else None,
            },
        )
        return recon


class PCFService:
    """Petty Cash Fund operations (ADR-027). 3 funds, imprest, 85% trigger."""

    @classmethod
    def check_replenishment_needed(cls, fund: PettyCashFund) -> bool:
        """Check if fund consumed >= trigger%."""
        from apps.posting.models import GeneralLedger

        spent = (
            GeneralLedger.objects.filter(
                account=fund.gl_account,
                entry__status="posted",
                credit__gt=0,
            ).aggregate(s=Sum("credit"))["s"]
        ) or Decimal("0.00")
        consumed = spent / fund.imprest_amount
        return consumed >= fund.replenish_trigger_pct

    @classmethod
    def request_replenishment(cls, fund: PettyCashFund, expenses: list[dict], user=None) -> PCFReplenishment:
        """Create replenishment request from liquidation expenses."""
        total = sum(money(e["amount"]) for e in expenses)
        return PCFReplenishment.objects.create(
            fund=fund,
            request_date=date.today(),
            amount=total,
            expenses=expenses,
            status="requested",
            approved_by=user,
        )

    @classmethod
    @transaction.atomic
    def post_replenishment(cls, replen: PCFReplenishment, user=None, *, segment=None) -> PCFReplenishment:
        """Post the replenishment JE: Dr Expense lines | Cr Cash."""
        from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
        from apps.posting.services import PostingService

        seg = segment or replen.fund.company.segments.order_by("code").first()
        entry = JournalEntry.objects.create(
            entry_no=f"PCF-REP-{replen.id}",
            company=replen.fund.company,
            segment=seg,
            transaction_date=replen.request_date,
            status=PostingStatus.DRAFT,
            description=f"PCF replenishment {replen.fund}",
            source_doc_type="PCF",
            source_doc_no=str(replen.id),
            created_by=user,
        )
        line_no = 1
        for exp in replen.expenses:
            from apps.foundation.models import Account
            acc = Account.objects.get(code=exp["account_code"])
            JournalEntryLine.objects.create(
                entry=entry,
                line_no=line_no,
                account=acc,
                debit=money(exp["amount"]),
                description=exp.get("description", ""),
            )
            line_no += 1
        JournalEntryLine.objects.create(
            entry=entry,
            line_no=line_no,
            account=replen.fund.gl_account,
            credit=replen.amount,
            description=f"PCF {replen.fund.fund_code} replenishment",
        )
        entry.recalc_totals()
        PostingService.post(entry, user=user)
        replen.journal_entry = entry
        replen.status = "posted"
        replen.save(update_fields=["journal_entry", "status", "updated_at"])
        return replen


class TransferService:
    """Inter-account transfer (ADR-030): Dr Cash-To | Cr Cash-From; purpose required."""

    @classmethod
    @transaction.atomic
    def transfer(
        cls,
        *,
        from_account: BankAccount,
        to_account: BankAccount,
        amount,
        purpose: str,
        reference: str = "",
        transfer_date: date | None = None,
        segment=None,
        user=None,
    ) -> InterAccountTransfer:
        amount = money(amount)
        if amount <= 0:
            raise ValidationError("Transfer amount must be positive.")
        if from_account == to_account:
            raise ValidationError("From and to accounts must differ.")
        if from_account.company_id != to_account.company_id:
            raise ValidationError("Transfers are only allowed within one company.")

        transfer = InterAccountTransfer.objects.create(
            transfer_date=transfer_date or date.today(),
            from_account=from_account,
            to_account=to_account,
            amount=amount,
            purpose=purpose,
            reference=reference,
            initiated_by=user,
        )

        from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
        from apps.posting.services import PostingService

        seg = segment or from_account.company.segments.order_by("code").first()
        entry = JournalEntry.objects.create(
            entry_no=f"TRF-{transfer.id}",
            company=from_account.company,
            segment=seg,
            transaction_date=transfer.transfer_date,
            status=PostingStatus.DRAFT,
            description=f"Inter-account transfer: {purpose}",
            source_doc_type="TRANSFER",
            source_doc_no=str(transfer.id),
            created_by=user,
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=1, account=from_account.gl_account,
            credit=amount, description=f"Transfer to {to_account.code}"
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=2, account=to_account.gl_account,
            debit=amount, description=f"Transfer from {from_account.code}"
        )
        entry.recalc_totals()
        PostingService.post(entry, user=user)
        transfer.journal_entry = entry
        transfer.save(update_fields=["journal_entry", "updated_at"])
        return transfer


class CashFlowService:
    """Cash Flow Statement from cycle activities (ADR-031).

    Banks are company-level master data, so the statement is COMPANY-WIDE: the
    period's per-segment cycle sheets (ADR-028) are consolidated into one cash
    position, and the ADB maintaining balance is the company's full bank pool.

    Identity (must hold for every generated statement):
        net_change == ending_cash - beginning_cash + adb_adjustments
    (January 2026 reference: -941,691.96 = 1,316,150.58 - 2,412,842.54 + 155,000.)
    """

    @classmethod
    def generate(cls, period_start: date, period_end: date, company) -> CashFlowStatement:
        cycles = list(
            WeeklyCashCycle.objects.filter(
                segment__company=company,
                cycle_start__gte=period_start,
                cycle_end__lte=period_end,
            ).order_by("cycle_start", "segment__code")
        )
        if not cycles:
            raise ValidationError("No cycles in period.")

        # Sum ADR-028 activity rows across the period's cycles.
        totals = dict(
            CashCycleActivity.objects.filter(
                cycle__in=cycles
            ).values_list("activity_type").annotate(total=Sum("amount"))
        )
        totals = {k: v or Decimal("0.00") for k, v in totals.items()}

        collections = (
            totals.get(ActivityType.COLLECTION_DIST, Decimal("0"))
            + totals.get(ActivityType.OTHER_COLLECTION, Decimal("0"))
        )
        operating_outflows = (
            totals.get(ActivityType.SUPPLIER_PAYMENT, Decimal("0"))
            + totals.get(ActivityType.RFP_AP, Decimal("0"))
            + totals.get(ActivityType.PCF_REPLEN, Decimal("0"))
            + totals.get(ActivityType.OTHER_PAYMENT, Decimal("0"))
        )
        capex = totals.get(ActivityType.CAPEX, Decimal("0"))
        borrowed = totals.get(ActivityType.BORROWED, Decimal("0"))
        loan_cleared = totals.get(ActivityType.LOAN_CLEARED, Decimal("0"))

        net_operating = collections - operating_outflows
        net_investing = -capex
        net_financing = borrowed - loan_cleared
        net_change = net_operating + net_investing + net_financing

        beginning_cash = cls._opening_cash(company, period_start)
        adb = cls._adb_total(company)
        # ADR-031 convention: "CASH AVAILABLE AT END" = total closing minus the
        # ADB maintained during the period (kept from the identity test).
        ending_cash = cls._ending_cash(company, period_start, period_end) - adb

        cf = CashFlowStatement.objects.create(
            period_start=period_start,
            period_end=period_end,
            collections=collections,
            payments_to_depot=operating_outflows,
            asset_acquisitions=capex,
            loan_proceeds=borrowed,
            loan_repayments=loan_cleared,
            net_change=net_change,
            beginning_cash=beginning_cash,
            ending_cash=ending_cash,
            adb_adjustments=adb,
        )
        return cf

    @classmethod
    def generate_month(cls, company, year: int, month: int) -> CashFlowStatement:
        """ADR-031 monthly cash flow: aggregate the month's weekly cycles."""
        first = date(year, month, 1)
        if month == 12:
            last = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last = date(year, month + 1, 1) - timedelta(days=1)
        return cls.generate(first, last, company)

    @classmethod
    def _opening_cash(cls, company, first_day: date) -> Decimal:
        """Sum of the closing balances of the latest cycle ENDING BEFORE the
        period, across the company's segments (ADR-031 beginning cash)."""
        prev = WeeklyCashCycle.objects.filter(
            segment__company=company, cycle_end__lt=first_day
        )
        total = Decimal("0.00")
        for sid in set(prev.values_list("segment_id", flat=True)):
            last = prev.filter(segment_id=sid).order_by("-cycle_start").first()
            if last:
                total += last.closing_balance
        return money(total)

    @classmethod
    def _ending_cash(cls, company, period_start: date, period_end: date) -> Decimal:
        """Sum of the closing balances of the latest cycle in the period, across
        the company's segments (ADR-031 ending cash, before ADB)."""
        qs = WeeklyCashCycle.objects.filter(
            segment__company=company,
            cycle_start__gte=period_start,
            cycle_end__lte=period_end,
        )
        total = Decimal("0.00")
        for sid in set(qs.values_list("segment_id", flat=True)):
            last = qs.filter(segment_id=sid).order_by("-cycle_start").first()
            if last:
                total += last.closing_balance
        return money(total)

    @classmethod
    def _adb_total(cls, company) -> Decimal:
        """Sum of required maintaining balances for the company's active banks
        (ADR-031 reporting adjustment, not a real cash outflow)."""
        return (
            BankAccount.objects.filter(company=company, is_active=True).aggregate(
                total=Sum("adb_required")
            )["total"]
        ) or Decimal("0.00")


class CheckDisbursementService:
    """CV lifecycle tracking: created -> signed CNR -> released Quibs -> cleared."""

    @classmethod
    def sign_cnr(cls, cv, user) -> CheckDisbursement:
        disb, _ = CheckDisbursement.objects.get_or_create(cv=cv)
        disb.signed_by_cnr = user
        disb.signed_at = timezone.now()
        disb.status = "signed"
        disb.save(update_fields=["signed_by_cnr", "signed_at", "status", "updated_at"])
        return disb

    @classmethod
    def release_quibs(cls, cv, user) -> CheckDisbursement:
        disb = cv.disbursement
        disb.released_by_quibs = user
        disb.released_at = timezone.now()
        disb.status = "released"
        disb.save(update_fields=["released_by_quibs", "released_at", "status", "updated_at"])
        return disb

    @classmethod
    def clear(cls, cv, bank_account, user) -> CheckDisbursement:
        disb = cv.disbursement
        disb.cleared_at = timezone.now()
        disb.clearing_bank_account = bank_account
        disb.status = "cleared"
        disb.save(update_fields=["cleared_at", "clearing_bank_account", "status", "updated_at"])
        return disb


class CollectiblesService:
    """COLLECTIBLES worksheet (ADR-029): gross mark-up = client paid - depot paid. NO JE.

    Two departments per cycle:
      - Distribution: client collections (AR) vs depot payments (SUPPLIER_PAYMENT)
        -> gross mark-up (Leaslyn's computation, automated here).
      - F&A: client collections gross vs outflows (RFP_AP + PCF_REPLEN + LOAN
        + transfers) -> net cash position (Quibong).
    """

    @classmethod
    def generate(cls, cycle: WeeklyCashCycle) -> list[CollectiblesWorksheet]:
        """Regenerate the COLLECTIBLES worksheet rows for a cycle from its
        persisted ADR-028 activities."""
        activities = {
            a.activity_type: a.amount for a in cycle.activities.all()
        }

        client_paid = (
            activities.get(ActivityType.COLLECTION_DIST, Decimal("0"))
            + activities.get(ActivityType.OTHER_COLLECTION, Decimal("0"))
        )

        results = []
        # Distribution side: gross mark-up = client paid - depot paid.
        depot_paid = activities.get(ActivityType.SUPPLIER_PAYMENT, Decimal("0"))
        ws, _ = CollectiblesWorksheet.objects.update_or_create(
            cycle=cycle,
            department="Distribution",
            defaults={
                "client_paid": client_paid,
                "depot_paid": depot_paid,
                "gross_markup": client_paid - depot_paid,
            },
        )
        results.append(ws)

        # F&A side: net cash position after all outflows.
        outflows = (
            activities.get(ActivityType.RFP_AP, Decimal("0"))
            + activities.get(ActivityType.PCF_REPLEN, Decimal("0"))
            + activities.get(ActivityType.LOAN_CLEARED, Decimal("0"))
            + activities.get(ActivityType.CAPEX, Decimal("0"))
            + activities.get(ActivityType.OTHER_PAYMENT, Decimal("0"))
        )
        ws, _ = CollectiblesWorksheet.objects.update_or_create(
            cycle=cycle,
            department="F&A",
            defaults={
                "client_paid": client_paid,
                "depot_paid": outflows,
                "gross_markup": client_paid - outflows,
            },
        )
        results.append(ws)
        return results


class CashShortService:
    """CASH SHORT worksheet (ADR-029/030): recon, NOT a JE; variance needs approval."""

    @classmethod
    def record_variance(
        cls,
        cycle: WeeklyCashCycle,
        segment,
        expected_cash,
        actual_cash,
        cause: str = "",
        cause_category: str = "",
        user=None,
    ) -> CashShortExcessWorksheet:
        exp = money(expected_cash)
        act = money(actual_cash)
        var = act - exp
        ws = CashShortExcessWorksheet.objects.create(
            cycle=cycle,
            segment=segment,
            expected_cash=exp,
            actual_cash=act,
            variance=var,
            cause=cause,
            cause_category=cause_category,
            status="open",
        )
        return ws

    @classmethod
    def approve(cls, ws: CashShortExcessWorksheet, user) -> CashShortExcessWorksheet:
        ws.approved_by = user
        ws.status = "approved"
        ws.save(update_fields=["approved_by", "status", "updated_at"])
        return ws