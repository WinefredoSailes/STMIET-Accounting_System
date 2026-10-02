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
from io import StringIO

import pytest
from django.core.management import call_command

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
        bank_name="BDO", bank_code="BDO", gl_account=acc, company=segment.company,
    )


@pytest.fixture
def pcf_fund(db, segment, accounts):
    """Create a PCF fund with GL account."""
    from apps.foundation.models import Account

    acc = accounts["10000"]
    from django.contrib.auth import get_user_model

    User = get_user_model()
    custodian = User.objects.create_user(username="leaslyn", password="x")
    return PettyCashFund.objects.create(
        fund_code="general", name="PCF-General (Leaslyn)",
        custodian=custodian, imprest_amount=Decimal("20000.00"),
        replenish_trigger_pct=Decimal("0.85"),
        gl_account=acc, company=segment.company,
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

    def test_request_creates_a_draft_not_queued(self, pcf_fund):
        """The voucher form saves a preparer-side draft (mirrors RFP
        ``prepared``): it must not be approvable, postable, or in the Head's
        queue until it is submitted (``requested``)."""
        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        assert replen.amount == Decimal("10000.00")
        assert replen.status == "draft"
        with pytest.raises(ValidationError):
            PCFService.approve_replenishment(replen)
        with pytest.raises(ValidationError):
            PCFService.reject_replenishment(replen, user=None, note="x")
        with pytest.raises(ValidationError):
            PCFService.post_replenishment(replen)

    def test_submit_moves_draft_to_requested(self, pcf_fund, user):
        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
            user=user,
        )
        PCFService.submit_replenishment(replen, user=user)
        replen.refresh_from_db()
        assert replen.status == "requested"
        # submitting twice is refused (only drafts can be submitted)
        with pytest.raises(ValidationError):
            PCFService.submit_replenishment(replen, user=user)

    def test_replenishment_creates_je(self, pcf_fund, accounts):
        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        assert replen.status == "draft"
        PCFService.submit_replenishment(replen)
        replen = PCFService.post_replenishment(replen)
        assert replen.status == "posted"
        assert replen.journal_entry is not None
        je = replen.journal_entry
        assert je.is_balanced
        lines = {l.line_no: l for l in je.lines.all()}
        assert lines[1].debit == Decimal("10000.00")  # Dr Expense
        # Credit is now A/Payable-Other Current (21100)
        assert lines[2].credit == Decimal("10000.00")
        assert lines[2].account.code == "21100"

    def test_approve_creates_conso_batch(self, pcf_fund):
        """ADR-038 §7c: approval auto-creates a CONSO batch entry."""
        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        PCFService.submit_replenishment(replen)
        PCFService.approve_replenishment(replen)
        replen.refresh_from_db()
        assert replen.status == "approved"
        assert replen.conso is not None
        assert replen.conso.batch_no.startswith("CONSO-")
        assert replen.conso.total_amount == Decimal("10000.00")
        assert list(replen.conso.pcf_replenishments.all()) == [replen]

    def test_approve_then_conso_post_posts_je(self, pcf_fund, user):
        """The batched PCF posts its JE when the CONSO batch posts."""
        from apps.ap.services import CONSOService
        from apps.posting.models import GeneralLedger

        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        PCFService.submit_replenishment(replen)
        PCFService.approve_replenishment(replen, user=user)
        batch = replen.conso
        CONSOService.post_batch(batch, user=user)
        replen.refresh_from_db()
        assert batch.status == "posted"
        assert replen.status == "posted"
        assert replen.journal_entry is not None
        je = replen.journal_entry
        assert je.is_balanced
        assert je.is_posted
        gl = GeneralLedger.objects.filter(entry=je)
        assert gl.filter(debit=Decimal("10000.00")).count() == 1

    def test_approve_twice_rejected(self, pcf_fund):
        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        PCFService.submit_replenishment(replen)
        PCFService.approve_replenishment(replen)
        with pytest.raises(ValidationError):
            PCFService.approve_replenishment(replen)  # already approved/batched

    def test_post_rejected_once_batched(self, pcf_fund):
        """Direct posting is refused once the replenishment is batched."""
        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        PCFService.submit_replenishment(replen)
        PCFService.approve_replenishment(replen)
        with pytest.raises(ValidationError):
            PCFService.post_replenishment(replen)

    def test_reject_flips_to_rejected_with_note(self, pcf_fund, user):
        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        PCFService.submit_replenishment(replen)
        PCFService.reject_replenishment(replen, user=user, note="Missing receipts")
        replen.refresh_from_db()
        assert replen.status == "rejected"
        assert replen.rejected_by_id == user.id
        assert replen.rejected_at is not None
        assert replen.rejection_note == "Missing receipts"

    def test_reject_requires_note(self, pcf_fund, user):
        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        PCFService.submit_replenishment(replen)
        with pytest.raises(ValidationError):
            PCFService.reject_replenishment(replen, user=user, note="  ")

    def test_reject_only_from_requested(self, pcf_fund, user):
        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        PCFService.submit_replenishment(replen)
        PCFService.approve_replenishment(replen)
        with pytest.raises(ValidationError):
            PCFService.reject_replenishment(replen, user=user, note="Too late")

    def test_rejected_cannot_be_approved_or_posted(self, pcf_fund, user):
        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        PCFService.submit_replenishment(replen)
        PCFService.reject_replenishment(replen, user=user, note="Fix the lines")
        with pytest.raises(ValidationError):
            PCFService.approve_replenishment(replen)
        with pytest.raises(ValidationError):
            PCFService.post_replenishment(replen)

    def test_revise_reopens_and_clears_rejection(self, pcf_fund, user):
        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        PCFService.submit_replenishment(replen)
        PCFService.reject_replenishment(replen, user=user, note="Fix the lines")
        PCFService.revise_replenishment(replen, user=user)
        replen.refresh_from_db()
        assert replen.status == "requested"
        assert replen.rejected_by_id is None
        assert replen.rejected_at is None
        assert replen.rejection_note == ""
        # back in the head's queue: approval works again
        PCFService.approve_replenishment(replen)
        replen.refresh_from_db()
        assert replen.status == "approved"

    def test_revise_only_from_rejected(self, pcf_fund, user):
        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        with pytest.raises(ValidationError):
            PCFService.revise_replenishment(replen, user=user)

    def test_conso_reject_member_unassigns_replenishment(self, pcf_fund, user):
        """A batched (approved) replenishment can be rejected from its CONSO
        batch: it returns to the custodian and leaves the batch. The
        dedicated one-voucher batch retires once emptied."""
        from django.contrib.auth import get_user_model

        from apps.ap.models import CONSOBatch
        from apps.ap.services import CONSOService
        from apps.foundation.models import UserProfile

        head = get_user_model().objects.create_user(username="pcfhead", password="x")
        UserProfile.objects.create(user=head, approval_role="head")
        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        PCFService.submit_replenishment(replen, user=user)
        PCFService.approve_replenishment(replen, user=head)
        batch = replen.conso
        assert batch is not None

        batch = CONSOService.reject_member(
            batch, replen=replen, user=head, note="Receipts don't add up"
        )

        replen.refresh_from_db()
        assert replen.status == "rejected"
        assert replen.conso_id is None
        assert replen.approved_by_id is None
        assert replen.approved_at is None
        assert replen.rejected_by_id == head.id
        assert replen.rejection_note == "Receipts don't add up"
        assert batch.is_active is False
        assert CONSOBatch.objects.count() == 0
        # the custodian can revise and the head can approve again (new batch)
        PCFService.revise_replenishment(replen, user=user)
        PCFService.approve_replenishment(replen, user=head)
        replen.refresh_from_db()
        assert replen.status == "approved"
        assert replen.conso_id is not None

    def test_conso_reject_replenishment_requires_head(self, pcf_fund, user):
        from apps.ap.services import CONSOService

        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        PCFService.submit_replenishment(replen, user=user)
        PCFService.approve_replenishment(replen, user=user)
        with pytest.raises(ValidationError):
            CONSOService.reject_member(replen.conso, replen=replen, user=user, note="Nope")
        replen.refresh_from_db()
        assert replen.status == "approved"
        assert replen.conso_id is not None

    def test_conso_reject_rfp_keeps_pcf_member(self, pcf_fund, user, segment, accounts):
        """Mixed batch, both sides: the RFP is rejected out while the PCF
        replenishment stays batched and posts with the batch — neither side
        floats (rejected RFP is revisable, kept PCF gets its JE)."""
        from datetime import date
        from decimal import Decimal

        from django.contrib.auth import get_user_model

        from apps.ap.models import Supplier
        from apps.ap.services import CONSOService, RFPService
        from apps.foundation.models import UserProfile

        head = get_user_model().objects.create_user(username="mixhead", password="x")
        UserProfile.objects.create(user=head, approval_role="head")
        supplier = Supplier.objects.create(code="S901", name="Mixed Supplier", default_segment=segment)
        rfp = RFPService.create_rfp(
            ap_number="A90101", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "15000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "15000.00"},
            ],
            user=user,
        )
        for role in ("checked", "acctg_approved", "fin_approved"):
            rfp = RFPService.advance_step(rfp, role=role, user=head)
        replen = PCFService.request_replenishment(
            pcf_fund, [{"account_code": "61100", "amount": "10000.00", "description": "Supplies"}],
        )
        PCFService.submit_replenishment(replen, user=user)
        PCFService.approve_replenishment(replen, user=head)
        batch = replen.conso
        rfp.conso = batch
        rfp.save(update_fields=["conso", "updated_at"])
        batch.total_amount = Decimal("25000.00")
        batch.save(update_fields=["total_amount", "updated_at"])

        CONSOService.reject_member(batch, rfp=rfp, user=head, note="Wrong charge account")
        CONSOService.post_batch(batch, user=head)

        rfp.refresh_from_db()
        replen.refresh_from_db()
        batch.refresh_from_db()
        assert rfp.status == "rejected"
        assert rfp.conso_id is None
        assert batch.status == "posted"
        assert batch.total_amount == Decimal("10000.00")
        assert replen.status == "posted"
        assert replen.journal_entry is not None
        assert replen.journal_entry.is_posted
        assert replen.journal_entry.is_balanced


class TestTransfers:
    def test_transfer_requests_then_head_approves_and_posts(self, segment, bank_account, accounts):
        to_acc = BankAccount.objects.create(
            code="PNB-DHPP", name="PNB DHPP", account_type="checking",
            bank_name="PNB", bank_code="PNB", gl_account=accounts["10110"], company=segment.company,
        )
        tr = TransferService.transfer(
            from_account=bank_account, to_account=to_acc,
            amount="5000.00", purpose="Fund transfer", user=None,
        )
        # Request stage: DRAFT JE, nothing in the GL yet — no threshold bypass.
        assert tr.status == "requested"
        assert tr.journal_entry.status == PostingStatus.DRAFT
        assert tr.journal_entry.is_balanced
        lines = {l.line_no: l for l in tr.journal_entry.lines.all()}
        assert lines[1].debit == Decimal("5000.00")  # Dr to (debits first on vouchers)
        assert lines[2].credit == Decimal("5000.00")  # Cr from
        # The preparer submits, then head approval posts the JE whatever the
        # amount (threshold removed).
        tr = TransferService.submit(tr, user=None)
        assert tr.status == "submitted"
        tr = TransferService.approve(tr, user=None)
        assert tr.status == "approved"
        assert tr.journal_entry.status == PostingStatus.POSTED

    def test_transfer_approve_requires_submitted(self, segment, bank_account, accounts):
        to_acc = BankAccount.objects.create(
            code="PNB-DHPP2", name="PNB DHPP 2", account_type="checking",
            bank_name="PNB", bank_code="PNB", gl_account=accounts["10110"], company=segment.company,
        )
        tr = TransferService.transfer(
            from_account=bank_account, to_account=to_acc,
            amount="5000.00", purpose="Fund transfer", user=None,
        )
        # Cannot approve before the preparer submits.
        with pytest.raises(ValidationError, match="submitted"):
            TransferService.approve(tr, user=None)
        TransferService.submit(tr, user=None)
        TransferService.approve(tr, user=None)
        # Cannot approve twice.
        with pytest.raises(ValidationError, match="submitted"):
            TransferService.approve(tr, user=None)

    def test_transfer_reject_revise_resubmit(self, segment, bank_account, accounts):
        to_acc = BankAccount.objects.create(
            code="PNB-DHPP3", name="PNB DHPP 3", account_type="checking",
            bank_name="PNB", bank_code="PNB", gl_account=accounts["10110"], company=segment.company,
        )
        tr = TransferService.transfer(
            from_account=bank_account, to_account=to_acc,
            amount="5000.00", purpose="Fund transfer", user=None,
        )
        TransferService.submit(tr, user=None)
        # A rejection note is required.
        with pytest.raises(ValidationError, match="note"):
            TransferService.reject(tr, user=None, note="")
        tr = TransferService.reject(tr, user=None, note="wrong account")
        assert tr.status == "rejected"
        assert tr.rejection_note == "wrong account"
        # Rejected transfers can be revised (reopened) and resubmitted.
        tr = TransferService.revise(tr, user=None)
        assert tr.status == "requested"
        tr = TransferService.submit(tr, user=None)
        assert tr.status == "submitted"
        tr = TransferService.approve(tr, user=None)
        assert tr.status == "approved"

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
        cf = CashFlowService.generate(date(2026, 1, 13), date(2026, 1, 19), segment.company)
        assert cf.collections == Decimal("1000.00")
        assert cf.net_change == Decimal("1000.00")

    def test_cf_identity_holds(self, segment, bank_account, posted_je):
        CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        cf = CashFlowService.generate(date(2026, 1, 13), date(2026, 1, 19), segment.company)
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
            bank_name="PNB", bank_code="PNB", gl_account=accounts["10110"], company=segment.company,
        )
        CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        tr = TransferService.transfer(
            from_account=bank_account, to_account=to_acc,
            amount="5000.00", purpose="Fund transfer",
            transfer_date=date(2026, 1, 15), user=None,
        )
        TransferService.submit(tr, user=None)
        TransferService.approve(tr, user=None)
        cycle = CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        acts = {a.activity_type: a.amount for a in cycle.activities.all()}
        # Both transfer legs land in the same activity row (5k out + 5k in).
        assert acts.get(ActivityType.INTERACCT_TRANSFER) == Decimal("10000.00")
        cf = CashFlowService.generate(date(2026, 1, 13), date(2026, 1, 19), segment.company)
        # Inter-account transfers do not affect net cash (ADR-031).
        assert cf.net_change == Decimal("0.00")

    def test_generate_month_aggregates_cycles(self, segment, bank_account, posted_je):
        # ADR-031 monthly cadence: the month's weekly cycles roll up into one CF
        # statement. Cycle 1/13-1/19 sits inside January.
        CashCycleService.generate_cycle(segment, date(2026, 1, 13))
        cf = CashFlowService.generate_month(segment.company, 2026, 1)
        assert cf.period_start == date(2026, 1, 1)
        assert cf.period_end == date(2026, 1, 31)
        assert cf.collections == Decimal("1000.00")
        assert cf.net_change == Decimal("1000.00")
        assert cf.identity_holds

    def test_generate_month_december_span(self, segment, bank_account, posted_je):
        # December runs 12/1-12/31; no cycles exist there -> ValidationError
        # ("No cycles in period") proves the month range was built correctly.
        with pytest.raises(ValidationError):
            CashFlowService.generate_month(segment.company, 2025, 12)


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


class TestImportBanks:
    def test_creates_and_idempotent(self, tmp_path, company, accounts):
        acc_bdo = accounts["10110"]  # BDO Checking from conftest COA slice
        acc_coh = accounts["10010"]  # Cash on Hand
        path = tmp_path / "banks.csv"
        import csv
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["CODE", "NAME", "TYPE", "BANK NAME", "BANK CODE", "GL ACCOUNT", "ADB REQUIRED"])
            writer.writerow(["BK1", "BDO Checking", "checking", "BDO", "BDO", acc_bdo.code, "5000"])
            writer.writerow(["BK2", "Petty Cash", "coh", "", "", acc_coh.code, "0"])
        call_command("import_banks", file=str(path), stdout=StringIO())

        bk1 = BankAccount.objects.get(code="BK1")
        assert bk1.account_type == "checking"
        assert bk1.gl_account_id == acc_bdo.id
        assert float(bk1.adb_required) == 5000.00
        assert BankAccount.objects.get(code="BK2").account_type == "pcf_coh"

        call_command("import_banks", file=str(path), stdout=StringIO())
        assert BankAccount.objects.filter(code="BK1").count() == 1

    def test_gl_conflict_is_skipped(self, tmp_path, company, accounts):
        acc = accounts["10010"]
        BankAccount.objects.create(
            code="EXIST", name="Existing", account_type="checking",
            gl_account=acc, company=company,
        )
        path = tmp_path / "banks.csv"
        import csv
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["CODE", "NAME", "TYPE", "GL ACCOUNT"])
            writer.writerow(["NEWBK", "New Bank", "checking", acc.code])
        out = StringIO()
        call_command("import_banks", file=str(path), stdout=out)
        assert not BankAccount.objects.filter(code="NEWBK").exists()
        assert "already used" in out.getvalue()