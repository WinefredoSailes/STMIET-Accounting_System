"""Reversal UI/workflow: request -> head approve/reject, inbox, source badge.

The service layer is covered in apps/posting/test_reversal.py; these tests pin
the HTTP flow the user actually drives (ADR-004 maker-checker).
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.posting.models import (
    JournalEntry,
    JournalEntryLine,
    PostingStatus,
    ReversalRequest,
)
from apps.posting.services import PostingService

pytestmark = pytest.mark.django_db


def _posted(company, segment, accounts, ref="JE-UI-REV-1"):
    je = JournalEntry.objects.create(
        entry_no=ref, company=company, segment=segment,
        transaction_date=date(2026, 9, 10), status=PostingStatus.DRAFT,
        description="ui reversal test", created_by=None,
    )
    JournalEntryLine.objects.create(
        entry=je, line_no=1, account=accounts["10010"], debit=Decimal("100.00")
    )
    JournalEntryLine.objects.create(
        entry=je, line_no=2, account=accounts["41010"], credit=Decimal("100.00")
    )
    je.recalc_totals()
    je.status = PostingStatus.APPROVED
    je.save(update_fields=["status", "updated_at"])
    PostingService.post(je)
    return je


def test_request_then_head_approve_from_detail(client, company, segment, accounts, role_users):
    je = _posted(company, segment, accounts)

    client.force_login(role_users["staff"])
    resp = client.post(f"/journal/{je.id}/reverse/", {"reason": "Wrong account"})
    assert resp.status_code == 302
    req = ReversalRequest.objects.get(entry=je)
    assert req.status == ReversalRequest.Status.REQUESTED

    # Requester sees the pending banner.
    body = client.get(f"/journal/{je.id}/").content.decode()
    assert "Reversal requested" in body
    assert "Wrong account" in body

    # Head approves → original reversed, mirror posted, banner switches.
    client.force_login(role_users["head"])
    resp = client.post(f"/journal/reversal/{req.id}/approve/")
    assert resp.status_code == 302
    je.refresh_from_db()
    req.refresh_from_db()
    assert je.status == PostingStatus.REVERSED
    assert req.status == ReversalRequest.Status.APPROVED
    body = client.get(f"/journal/{je.id}/").content.decode()
    assert "Reversing entry" in body


def test_staff_cannot_approve_reversal(client, company, segment, accounts, role_users):
    je = _posted(company, segment, accounts)
    client.force_login(role_users["staff"])
    client.post(f"/journal/{je.id}/reverse/", {"reason": "x"})
    req = ReversalRequest.objects.get(entry=je)

    resp = client.post(f"/journal/reversal/{req.id}/approve/", follow=True)
    je.refresh_from_db()
    assert je.status == PostingStatus.POSTED  # unchanged
    assert b"Accounting" in resp.content or b"not moved" in resp.content


def test_head_rejects_reversal_note_required(client, company, segment, accounts, role_users):
    je = _posted(company, segment, accounts)
    client.force_login(role_users["staff"])
    client.post(f"/journal/{je.id}/reverse/", {"reason": "x"})
    req = ReversalRequest.objects.get(entry=je)

    client.force_login(role_users["head"])
    client.post(f"/journal/reversal/{req.id}/reject/", {"note": ""})
    req.refresh_from_db()
    assert req.status == ReversalRequest.Status.REQUESTED  # note required

    client.post(f"/journal/reversal/{req.id}/reject/", {"note": "keep it"})
    req.refresh_from_db()
    je.refresh_from_db()
    assert req.status == ReversalRequest.Status.REJECTED
    assert je.status == PostingStatus.POSTED


def test_pending_reversal_in_head_inbox(company, segment, accounts, role_users):
    from apps.core.approvals import pending_approval_queue
    from apps.posting.services import ReversalService

    je = _posted(company, segment, accounts)
    ReversalService.request(je, reason="inbox", user=role_users["staff"])
    items = [i for i in pending_approval_queue(role_users["head"]) if i["kind"] == "reversal"]
    assert len(items) == 1
    assert items[0]["action"][0] == "ui:je_reversal_approve"


def test_source_document_shows_reversed_banner(client, company, segment, accounts, role_users):
    from apps.cash.models import BankAccount
    from apps.cash.services import TransferService

    b_from = BankAccount.objects.create(
        code="1VB-RB", name="First Valley", account_type="checking",
        bank_name="First Valley", bank_code="1VB", gl_account=accounts["10110"], company=company,
    )
    b_to = BankAccount.objects.create(
        code="MB-RB", name="Metrobank", account_type="checking",
        bank_name="Metrobank", bank_code="MB", gl_account=accounts["10010"], company=company,
    )
    transfer = TransferService.transfer(
        from_account=b_from, to_account=b_to, amount="1000.00",
        purpose="to reverse", transfer_date="2026-09-10", segment=segment,
        user=role_users["staff"],
    )
    TransferService.submit(transfer, user=role_users["staff"])
    TransferService.approve(transfer, user=role_users["head"])

    from apps.posting.services import ReversalService

    req = ReversalService.request(transfer.journal_entry, reason="dup", user=role_users["staff"])
    ReversalService.approve(req, user=role_users["head"])

    client.force_login(role_users["staff"])
    body = client.get(f"/cash/transfers/{transfer.id}/").content.decode()
    assert "has been reversed" in body