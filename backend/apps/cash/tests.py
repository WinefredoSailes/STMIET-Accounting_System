"""Cash contract tests (BUILD-PLAN Phase 4).

- Weekly Tue->Mon cycle sheet from GL (ADR-013/028)
- Bank recon per cycle per bank; diff = typo + POP + cashier (ADR-026)
- PCF 3 funds, imprest, 85% trigger (ADR-027)
- Inter-account transfer: Dr Cash-To | Cr Cash-From; purpose required (ADR-030)
- CF statement identity: Net Inc = End - Beg + ADB (ADR-031)
- CASH SHORT = recon worksheet, NOT a JE; variance needs approval (ADR-030)
- Check disbursement lifecycle: created -> signed CNR -> released Quibs -> cleared
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.cash.models import (
    BankAccount,
    BankReconciliation,
    CashShortExcessWorksheet,
    CheckDisbursement,
    InterAccountTransfer,
    PCFReplenishment,
    PettyCashFund,
    WeeklyCashCycle,
)
from apps.cash.services import (
    BankReconService,
    CashCycleService,
    CashFlowService,
    CashShortService,
    CheckDisbursementService,
    CollectiblesService,
    PCFService,
    TransferService,
)
from apps.core.exceptions import ValidationError
from apps.foundation.calendar import cycle_range_for
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus, GeneralLedger
from apps.posting.services import PostingService


@pytest.fixture
def bank_account(db, segment, accounts):
    """Create a bank account with GL account 10010."""
    from apps.foundation.models import Account

    acc = accounts["10010"]
    return BankAccount.objects.create(
        code="BDO-DHPP", name="BDO Checking DHPP", account_type="checking",
        bank_name="BDO", bank_code="BDO", gl_account=acc, segment=segment,
    )


@pytest.fixture
def pcf_fund(db, segment, accounts):
    """Create a PCF fund with GL account."""
    from apps.foundation.models import Account

    acc = Account.objects.create(
        code="10000", name="Petty Cash Fund-DHPP", account_type="asset", segment="DHPP"
    )
    from django.contrib.auth import get_user_model

    User = get_user_model()
    custodian = User.objects.create_user(username="leaslyn", password="x")
    return PettyCashFund.objects.create(
        fund_code="general", name="PCF-General (Leaslyn)",
        custodian=custodian, imprest_amount=Decimal("20000.00"),
        replenish_trigger_pct=Decimal("0.85"),
        gl_account=acc, segment=segment,
    )


@pytest.fixture
def posted_je(db, company, segment, accounts):
    """Create a posted JE with bank account activity AND GL entries."""
    je = JournalEntry.objects.create(
        entry_no="TEST-001", company=company, segment=segment,
        transaction_date=date(2026, 1, 15), status=PostingStatus.POSTED,
        description="test", source_doc_type="AR",
    )
    JournalEntryLine.objects.create(entry=je, line_no=1, account=accounts["10010"], debit="1000.00")
    JournalEntryLine.objects.create(entry=je, line_no=2, account=accounts["21000"], credit="1000.00")
    je.recalc_totals()
    # Create GL entries
    GeneralLedger.objects.create(
        entry=je, line=je.lines.get(line_no=1), account=accounts["10010"],
        company=segment.company, segment=segment,
        transaction_date=date(2026, 1, 15), debit="1000.00", credit="0.00",
    )
    GeneralLedger.objects.create(
        entry=je, line=je.lines.get(line_no=2), account=accounts["21000"],
        company=segment.company, segment=segment,
        transaction_date=date(2026, 1, 15), debit="0.00", credit="1000.00",
    )
    return je


class TestCashCycle:
    def test_generate_cycle_from_gl(self, segment, bank_account, posted_je):
        cycle = CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        assert cycle.cycle_start == date(2026, 1, 13)
        assert cycle.cycle_end == date(2026, 1, 19)
        assert cycle.closing_balance == Decimal("1000.00")  # net collection

    def test_cycle_range_tue_mon(self):
        start, end = cycle_range_for(date(2026, 1, 15))
        assert start == date(2026, 1, 13)
        assert end == date(2026, 1, 19)

    def test_generate_range(self, segment, bank_account, posted_je):
        cycles = CashCycleService.generate_range(segment, date(2026, 1, 13), date(2026, 2, 2))
        assert len(cycles) == 3


class TestBankReconciliation:
    def test_reconcile_matches_book_balance(self, segment, bank_account, posted_je):
        cycle = CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        recon = BankReconService.reconcile(
            cycle=cycle, bank_account=bank_account,
            bank_statement_balance="1000.00",
        )
        assert recon.difference == Decimal("0.00")
        assert recon.status == "resolved"

    def test_reconcile_flags_difference(self, segment, bank_account, posted_je):
        cycle = CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        recon = BankReconService.reconcile(
            cycle=cycle, bank_account=bank_account,
            bank_statement_balance="1050.00",
        )
        assert recon.difference == Decimal("50.00")
        assert recon.status == "open"


class TestPCF:
    def test_replenishment_trigger(self, pcf_fund, segment, company):
        # Post a PCF spending (credit PCF account) of 18,000 = 90% of 20,000.
        from apps.posting.models import GeneralLedger

        je = JournalEntry.objects.create(
            entry_no="TEST-PCF-1", company=company, segment=segment,
            transaction_date=date(2026, 1, 15), status=PostingStatus.POSTED,
            description="PCF spending", source_doc_type="PCF",
        )
        line = JournalEntryLine.objects.create(
            entry=je, line_no=1, account=pcf_fund.gl_account, credit="18000.00",
        )
        je.recalc_totals()
        GeneralLedger.objects.create(
            entry=je, line=line, account=pcf_fund.gl_account,
            company=segment.company, segment=segment,
            transaction_date=date(2026, 1, 15), debit=Decimal("0"), credit=Decimal("18000.00"),
        )
        assert PCFService.check_replenishment_needed(pcf_fund) is True

    def test_replenishment_creates_je(self, pcf_fund):
        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        assert replen.amount == Decimal("10000.00")
        assert replen.status == "requested"

        replen = PCFService.post_replenishment(replen)
        assert replen.status == "posted"
        assert replen.journal_entry is not None
        je = replen.journal_entry
        assert je.is_balanced
        lines = {l.line_no: l for l in je.lines.all()}
        assert lines[1].debit == Decimal("10000.00")  # Dr Expense
        assert lines[2].credit == Decimal("10000.00")  # Cr PCF


class TestTransfers:
    def test_transfer_posts_je(self, segment, bank_account, accounts):
        to_acc = BankAccount.objects.create(
            code="PNB-DHPP", name="PNB DHPP", account_type="checking",
            bank_name="PNB", bank_code="PNB", gl_account=accounts["10110"], segment=segment,
        )
        tr = TransferService.transfer(
            from_account=bank_account, to_account=to_acc,
            amount="5000.00", purpose="Fund transfer", user=None,
        )
        assert tr.journal_entry.is_balanced
        lines = {l.line_no: l for l in tr.journal_entry.lines.all()}
        assert lines[1].credit == Decimal("5000.00")  # Cr from
        assert lines[2].debit == Decimal("5000.00")  # Dr to

    def test_transfer_same_account_rejected(self, bank_account):
        with pytest.raises(ValidationError):
            TransferService.transfer(
                from_account=bank_account, to_account=bank_account,
                amount="1000.00", purpose="Self", user=None,
            )


class TestCashCycleActivities:
    def test_activity_rows_derived(self, segment, bank_account, posted_je):
        cycle = CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        activities = {a.activity_type: a.amount for a in cycle.activities.all()}
        # posted_je debits bank account 10010 with source_doc_type "AR".
        from apps.cash.models import ActivityType

        assert activities[ActivityType.COLLECTION_DIST] == Decimal("1000.00")
        assert cycle.closing_balance == Decimal("1000.00")

    def test_activity_rows_recomputed_on_regenerate(self, segment, bank_account, posted_je):
        cycle = CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        count1 = cycle.activities.count()
        cycle = CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        assert cycle.activities.count() == count1


class TestCashFlow:
    def test_cf_generation(self, segment, bank_account, posted_je):
        CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        cf = CashFlowService.generate(date(2026, 1, 13), date(2026, 1, 19), segment)
        assert cf.collections == Decimal("1000.00")
        assert cf.net_change == Decimal("1000.00")

    def test_cf_identity_holds(self, segment, bank_account, posted_je):
        CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        cf = CashFlowService.generate(date(2026, 1, 13), date(2026, 1, 19), segment)
        assert cf.identity_holds
        # ADR-031: net_change = ending - beginning + adb
        assert (
            cf.net_change
            == cf.ending_cash - cf.beginning_cash + cf.adb_adjustments
        )

    def test_cf_excludes_inter_account_transfers(self, segment, bank_account, accounts):
        # Build two bank accounts and a transfer between them (cash-to-cash).
        from apps.cash.models import ActivityType

        to_acc = BankAccount.objects.create(
            code="PNB-DHPP", name="PNB DHPP", account_type="checking",
            bank_name="PNB", bank_code="PNB", gl_account=accounts["10110"], segment=segment,
        )
        CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        TransferService.transfer(
            from_account=bank_account, to_account=to_acc,
            amount="5000.00", purpose="Fund transfer",
            transfer_date=date(2026, 1, 15), user=None,
        )
        cycle = CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        acts = {a.activity_type: a.amount for a in cycle.activities.all()}
        # Both transfer legs land in the same activity row (5k out + 5k in).
        assert acts.get(ActivityType.INTERACCT_TRANSFER) == Decimal("10000.00")
        cf = CashFlowService.generate(date(2026, 1, 13), date(2026, 1, 19), segment)
        # Inter-account transfers do not affect net cash (ADR-031).
        assert cf.net_change == Decimal("0.00")


class TestCollectibles:
    def test_gross_markup_generated(self, segment, bank_account, posted_je):
        cycle = CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        rows = {w.department: w for w in CollectiblesService.generate(cycle)}
        dist = rows["Distribution"]
        assert dist.client_paid == Decimal("1000.00")
        assert dist.depot_paid == Decimal("0.00")
        assert dist.gross_markup == Decimal("1000.00")


class TestCheckDisbursement:
    def test_lifecycle(self, segment, bank_account, accounts):
        from apps.ap.models import CheckVoucher, Supplier

        supplier = Supplier.objects.create(code="S900", name="Test Payee", default_segment=segment)
        cv = CheckVoucher.objects.create(
            cv_number="CV-2026-0001", cv_date=date(2026, 1, 15),
            payee=supplier,
            bank_account=accounts["10010"],  # Account, not BankAccount
            gross_amount="10000.00",
            net_amount="10000.00", status="created",
        )
        CheckDisbursementService.sign_cnr(cv, None)
        cv.refresh_from_db()
        assert cv.disbursement.status == "signed"

        CheckDisbursementService.release_quibs(cv, None)
        cv.refresh_from_db()
        assert cv.disbursement.status == "released"

        CheckDisbursementService.clear(cv, bank_account, None)
        cv.refresh_from_db()
        assert cv.disbursement.status == "cleared"


class TestCashShort:
    def test_record_variance(self, segment):
        cycle = CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        ws = CashShortService.record_variance(
            cycle, segment, "10000.00", "9950.00",
            cause="Cashier error", cause_category="cashier",
        )
        assert ws.variance == Decimal("-50.00")
        assert ws.status == "open"

    def test_approve_variance(self, segment):
        cycle = CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        ws = CashShortService.record_variance(
            cycle, segment, "10000.00", "9950.00",
            cause="Cashier error", cause_category="cashier",
        )
        CashShortService.approve(ws, None)
        assert ws.status == "approved"