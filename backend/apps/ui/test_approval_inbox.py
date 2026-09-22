"""Approval inbox hygiene (Phase 1 + 3): the head's "My Approvals" queue.

- ``je_queue`` = manual (un-owned) Journal Entries *submitted* only. Managed JEs
  (CV / RFP / Transfer / Billing / PCF / AR) surface under their own document
  kind, never as "Journal Entries". A transfer JE leaks into the queue as a
  "transfer" item only after ``submit``.
- ``pcf_queue`` = Petty Cash Replenishments awaiting head approval
  (``status="requested"``), head-only, dropped once approved.
"""

from datetime import date

import pytest

from apps.cash.models import BankAccount, PCFReplenishment, PettyCashFund
from apps.cash.services import TransferService
from apps.core.approvals import pending_approval_queue
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def banks(company, segment, accounts):
    b_from = BankAccount.objects.create(
        code="1VB-CHK", name="First Valley Bank",
        account_type="checking", bank_name="First Valley Bank", bank_code="1VB",
        gl_account=accounts["10110"], company=company,
    )
    b_to = BankAccount.objects.create(
        code="MB-CHK", name="Metrobank",
        account_type="checking", bank_name="Metrobank", bank_code="MB",
        gl_account=accounts["10010"], company=company,
    )
    return b_from, b_to


@pytest.fixture
def transfer(banks, segment, role_users):
    b_from, b_to = banks
    return TransferService.transfer(
        from_account=b_from,
        to_account=b_to,
        amount="150000.00",
        purpose="Fund transfer to Metrobank",
        reference="REF-INBOX",
        transfer_date="2026-09-17",
        segment=segment,
        user=role_users["staff"],
    )


def _manual(company, segment, fiscal_period, accounts, *, status=PostingStatus.SUBMITTED):
    je = JournalEntry.objects.create(
        company=company, segment=segment, fiscal_period=fiscal_period,
        transaction_date=date(2026, 1, 15), status=status, description="manual JE",
    )
    JournalEntryLine.objects.create(entry=je, line_no=1, account=accounts["10010"], debit="100.00")
    JournalEntryLine.objects.create(entry=je, line_no=2, account=accounts["20000"], credit="100.00")
    je.recalc_totals()
    return je


def _je_items(items):
    return [i for i in items if i["kind"] == "je"]


def _pcf(fund, *, user, status="requested"):
    return PCFReplenishment.objects.create(
        fund=fund,
        request_date=date(2026, 9, 2),
        amount="500.00",
        payee_name="Clerk",
        reference="REF",
        voucher_no="PCV-Q1",
        requested_by=user,
        status=status,
    )


def _fund(company, accounts):
    return PettyCashFund.objects.create(
        fund_code="PCF-Q1", name="Queue Fund", custodian_name="Custodian",
        imprest_amount="20000.00", gl_account=accounts["10010"],
        company=company, is_active=True,
    )


class TestJeQueueHygiene:
    def test_manual_submitted_je_appears(self, company, segment, fiscal_period, accounts, role_users):
        je = _manual(company, segment, fiscal_period, accounts)
        items = pending_approval_queue(role_users["head"])
        assert [i["doc"].id for i in _je_items(items)] == [je.id]

    def test_draft_manual_je_does_not_appear(self, company, segment, fiscal_period, accounts, role_users):
        _manual(company, segment, fiscal_period, accounts, status=PostingStatus.DRAFT)
        items = pending_approval_queue(role_users["head"])
        assert _je_items(items) == []

    def test_transfer_je_never_surfaces_as_je_even_if_forced_submitted(self, transfer, role_users):
        entry = transfer.journal_entry
        entry.status = PostingStatus.SUBMITTED
        entry.save(update_fields=["status", "updated_at"])
        items = pending_approval_queue(role_users["head"])
        assert _je_items(items) == []

    def test_submitted_transfer_surfaces_as_transfer_kind_not_je(self, transfer, role_users):
        TransferService.submit(transfer, user=role_users["staff"])
        items = pending_approval_queue(role_users["head"])
        assert "je" not in {i["kind"] for i in items}
        transfer_items = [i for i in items if i["kind"] == "transfer"]
        assert [i["doc"].id for i in transfer_items] == [transfer.id]

    def test_approved_transfer_leaves_queue_entirely(self, transfer, role_users):
        TransferService.submit(transfer, user=role_users["staff"])
        TransferService.approve(transfer, user=role_users["head"])
        items = pending_approval_queue(role_users["head"])
        assert all(i["doc"].id != transfer.id for i in items)


class TestPcfQueue:
    def test_requested_pcf_appears_for_head_only(self, company, segment, accounts, role_users):
        replen = _pcf(_fund(company, accounts), user=role_users["staff"])
        items = pending_approval_queue(role_users["head"])
        pcf = [i for i in items if i["kind"] == "pcf"]
        assert [i["doc"].id for i in pcf] == [replen.id]
        assert pcf[0]["action"] == ("ui:pcf_replenishment_approve", replen.id)
        assert pcf[0]["detail"] == ("ui:pcf_replenishment_detail", replen.id)
        assert all(i["kind"] != "pcf" for i in pending_approval_queue(role_users["staff"]))
        assert all(i["kind"] != "pcf" for i in pending_approval_queue(role_users["coo"]))

    def test_drops_after_approve(self, company, segment, accounts, role_users):
        from apps.cash.services import PCFService

        replen = _pcf(_fund(company, accounts), user=role_users["staff"])
        PCFService.approve_replenishment(replen, user=role_users["head"])
        items = pending_approval_queue(role_users["head"])
        assert all(i["kind"] != "pcf" for i in items)

    def test_posted_pcf_not_queued(self, company, segment, accounts, role_users):
        from apps.cash.models import PCFReplenishment

        replen = _pcf(_fund(company, accounts), user=role_users["staff"])
        PCFReplenishment.objects.filter(pk=replen.pk).update(status="posted")
        items = pending_approval_queue(role_users["head"])
        assert all(i["kind"] != "pcf" for i in items)

    def test_pcf_number_is_voucher_no(self, company, segment, accounts, role_users):
        replen = _pcf(_fund(company, accounts), user=role_users["staff"])
        items = pending_approval_queue(role_users["head"])
        pcf = [i for i in items if i["kind"] == "pcf"]
        assert pcf and pcf[0]["number"] == replen.voucher_no


class TestKindLabelsDropdown:
    def test_my_approvals_filter_includes_pcf(self, client, company, segment, accounts, role_users):
        _pcf(_fund(company, accounts), user=role_users["staff"])
        client.force_login(role_users["head"])
        body = client.get("/approvals/").content.decode()
        assert 'value="pcf"' in body
        assert "Petty Cash Replenishments" in body