"""Maker-checker reversal of posted Journal Entries (ADR-004/013).

Covers the reversal engine, the request/approve/reject workflow, role and
same-user gates, cycle allocation, and that the GL nets to zero (the original
is REVERSED and its mirror is POSTED; both are summed by GL readers).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db.models import Sum

from apps.core.exceptions import PostingError, ValidationError
from apps.foundation.calendar import cycle_range_for
from apps.posting.models import (
    GL_EFFECTIVE_STATUSES,
    GeneralLedger,
    JournalEntry,
    JournalEntryLine,
    PostingStatus,
    ReversalRequest,
)
from apps.posting.services import PostingService, ReversalService

pytestmark = pytest.mark.django_db


def _posted(company, segment, accounts, ref="JE-REV-1", amount="100.00"):
    je = JournalEntry.objects.create(
        entry_no=ref, company=company, segment=segment,
        transaction_date=date(2026, 1, 15), status=PostingStatus.DRAFT,
        description="reversal test",
    )
    JournalEntryLine.objects.create(
        entry=je, line_no=1, account=accounts["10010"], debit=Decimal(amount)
    )
    JournalEntryLine.objects.create(
        entry=je, line_no=2, account=accounts["41010"], credit=Decimal(amount)
    )
    je.recalc_totals()
    je.status = PostingStatus.APPROVED
    je.save(update_fields=["status", "updated_at"])
    PostingService.post(je)
    return je


def _account_net(account):
    agg = GeneralLedger.objects.filter(
        account=account, entry__status__in=GL_EFFECTIVE_STATUSES
    ).aggregate(dr=Sum("debit"), cr=Sum("credit"))
    return (agg["dr"] or Decimal("0.00")) - (agg["cr"] or Decimal("0.00"))


def test_reverse_nets_gl_to_zero_and_marks_original(company, segment, accounts):
    je = _posted(company, segment, accounts)
    assert _account_net(accounts["10010"]) == Decimal("100.00")

    rev = PostingService.reverse(je, reason="wrong account", reversal_date=date(2026, 1, 20))
    rev.refresh_from_db()
    je.refresh_from_db()

    assert je.status == PostingStatus.REVERSED
    assert rev.status == PostingStatus.POSTED
    assert rev.reversal_token == je.reversal_token
    # Original + mirror are both summed → the pair nets to zero.
    assert _account_net(accounts["10010"]) == Decimal("0.00")
    assert _account_net(accounts["41010"]) == Decimal("0.00")


def test_reversal_uses_current_open_cycle_then_advances_when_locked(
    company, segment, accounts
):
    from apps.cash.models import WeeklyCashCycle

    je = _posted(company, segment, accounts)
    today = date.today()
    start, end = cycle_range_for(today, company=company)
    # Open cycle → reversal posts to today (inside the open cycle).
    WeeklyCashCycle.objects.create(
        cycle_start=start, cycle_end=end, segment=segment, status="open",
        closing_balance=Decimal("0.00"),
    )
    rev = PostingService.reverse(je, reason="open cycle")
    assert rev.transaction_date == today

    # Locked cycle → advance to the next cycle's first day.
    cycle = WeeklyCashCycle.objects.get(segment=segment, cycle_start=start)
    cycle.status = "locked"
    cycle.save(update_fields=["status", "updated_at"])
    je2 = _posted(company, segment, accounts, ref="JE-REV-2")
    rev2 = PostingService.reverse(je2, reason="locked cycle")
    assert rev2.transaction_date == end + timedelta(days=1)


def test_request_requires_posted_entry_and_reason(company, segment, accounts):
    je = _posted(company, segment, accounts)
    with pytest.raises(PostingError):
        ReversalService.request(je, reason="")
    # A draft can't be reversed.
    je.status = PostingStatus.DRAFT
    je.save(update_fields=["status", "updated_at"])
    with pytest.raises(PostingError):
        ReversalService.request(je, reason="x")


def test_request_then_head_approve_posts_mirror(company, segment, accounts, role_users):
    je = _posted(company, segment, accounts)
    req = ReversalService.request(je, reason="duplicate posting", user=role_users["staff"])
    assert req.status == ReversalRequest.Status.REQUESTED

    approved = ReversalService.approve(req, user=role_users["head"])
    approved.refresh_from_db()
    je.refresh_from_db()
    assert approved.status == ReversalRequest.Status.APPROVED
    assert approved.reversal_entry_id is not None
    assert je.status == PostingStatus.REVERSED
    assert _account_net(accounts["10010"]) == Decimal("0.00")


def test_head_can_approve_own_request(company, segment, accounts, role_users):
    je = _posted(company, segment, accounts)
    req = ReversalService.request(je, reason="self", user=role_users["head"])
    # The Head is the only one who can approve reversals, so they must be able
    # to approve a request they raised themselves (otherwise it would be stuck).
    approved = ReversalService.approve(req, user=role_users["head"])
    approved.refresh_from_db()
    je.refresh_from_db()
    assert approved.status == ReversalRequest.Status.APPROVED
    assert je.status == PostingStatus.REVERSED
    assert approved.requested_by_id == approved.approved_by_id == role_users["head"].id


def test_only_head_can_approve(company, segment, accounts, role_users):
    je = _posted(company, segment, accounts)
    req = ReversalService.request(je, reason="needs head", user=role_users["staff"])
    with pytest.raises(ValidationError):
        ReversalService.approve(req, user=role_users["staff"])


def test_reject_requires_note_and_keeps_entry_posted(company, segment, accounts, role_users):
    je = _posted(company, segment, accounts)
    req = ReversalService.request(je, reason="maybe", user=role_users["staff"])

    with pytest.raises(PostingError):
        ReversalService.reject(req, user=role_users["head"], note="")
    rejected = ReversalService.reject(req, user=role_users["head"], note="keep it")
    rejected.refresh_from_db()
    je.refresh_from_db()
    assert rejected.status == ReversalRequest.Status.REJECTED
    assert rejected.reject_note == "keep it"
    assert je.status == PostingStatus.POSTED  # not reversed


def test_cannot_double_request_or_reverse(company, segment, accounts, role_users):
    je = _posted(company, segment, accounts)
    ReversalService.request(je, reason="first", user=role_users["staff"])
    with pytest.raises(PostingError):
        ReversalService.request(je, reason="second", user=role_users["staff"])

    req = ReversalService.pending().get()
    ReversalService.approve(req, user=role_users["head"])
    je.refresh_from_db()
    with pytest.raises(PostingError):
        ReversalService.request(je, reason="again", user=role_users["staff"])


def test_reversal_regenerates_open_cash_cycle(company, segment, accounts, role_users):
    """The cash cycle the reversal lands in reflects the contra row."""
    from apps.cash.models import BankAccount, CashCycleActivity, WeeklyCashCycle

    # Register the bank account so the cycle activity recognises its GL rows.
    bank_account = accounts["10110"]
    BankAccount.objects.create(
        code="BDO-REV", name="BDO Reversal", account_type="checking",
        bank_name="BDO", bank_code="BDO", gl_account=bank_account, company=company,
    )
    je = JournalEntry.objects.create(
        entry_no="JE-REV-3", company=company, segment=segment,
        transaction_date=date.today(), status=PostingStatus.DRAFT, description="bank move",
    )
    JournalEntryLine.objects.create(
        entry=je, line_no=1, account=bank_account, debit=Decimal("500.00")
    )
    JournalEntryLine.objects.create(
        entry=je, line_no=2, account=accounts["41010"], credit=Decimal("500.00")
    )
    je.recalc_totals()
    je.status = PostingStatus.APPROVED
    je.save(update_fields=["status", "updated_at"])
    PostingService.post(je)

    start, _ = cycle_range_for(date.today(), company=company)
    cycle = WeeklyCashCycle.objects.create(
        cycle_start=start, cycle_end=cycle_range_for(start, company=company)[1],
        segment=segment, status="open", closing_balance=Decimal("0.00"),
    )
    from apps.cash.services import CashCycleService

    CashCycleService.generate_cycle(segment, start)
    cycle.refresh_from_db()
    assert cycle.closing_balance == Decimal("500.00")

    # Reverse → both the original and the contra are summed in the cycle.
    req = ReversalService.request(je, reason="undo bank move", user=role_users["staff"])
    ReversalService.approve(req, user=role_users["head"])
    cycle.refresh_from_db()
    assert cycle.closing_balance == Decimal("0.00")
    assert CashCycleActivity.objects.filter(cycle=cycle).count() >= 1