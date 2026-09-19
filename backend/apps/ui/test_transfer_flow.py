"""Inter-account transfer full lifecycle tests (ADR-030).

Mirrors the RFP/JE/CV flow: create ``requested`` with a DRAFT JE, preparer
submits, head approves (posts to GL) or rejects with a required note; a
rejected transfer is revised and resubmitted. Covers the service layer, the
HTTP workflow, the approval inbox, the audit trail and the create/edit forms.
"""

from decimal import Decimal

import pytest

from apps.cash.models import BankAccount
from apps.cash.services import TransferService

pytestmark = pytest.mark.django_db


@pytest.fixture
def banks(company, segment, accounts):
    b_from = BankAccount.objects.create(
        code="1VB-FLOW", name="First Valley Bank", account_type="checking",
        bank_name="First Valley Bank", bank_code="1VB",
        gl_account=accounts["10110"], company=company,
    )
    b_to = BankAccount.objects.create(
        code="MB-FLOW", name="Metrobank", account_type="checking",
        bank_name="Metrobank", bank_code="MB",
        gl_account=accounts["10010"], company=company,
    )
    return b_from, b_to


@pytest.fixture
def transfer(banks, segment, role_users):
    b_from, b_to = banks
    return TransferService.transfer(
        from_account=b_from, to_account=b_to, amount="150000.00",
        purpose="Cycle sweep", reference="REF-1", check_no="123456",
        transfer_date="2026-09-17", segment=segment, user=role_users["staff"],
    )


# --- Service lifecycle -----------------------------------------------------


def test_create_is_requested_with_draft_je(transfer):
    from apps.posting.models import PostingStatus

    assert transfer.status == "requested"
    assert transfer.journal_entry.status == PostingStatus.DRAFT
    assert transfer.journal_entry.total_debit == Decimal("150000.00")
    assert transfer.journal_entry.total_credit == Decimal("150000.00")
    assert transfer.check_no == "123456"
    # FTV source designation (like RFP/CV carry their document number).
    assert transfer.journal_entry.source_doc_type == "FTV"
    assert transfer.journal_entry.source_doc_no == transfer.voucher_no


def test_create_does_not_post_to_gl(transfer):
    from apps.posting.models import GeneralLedger

    assert GeneralLedger.objects.filter(entry=transfer.journal_entry).count() == 0


def test_submit_moves_to_submitted_and_keeps_draft(transfer, role_users):
    from apps.posting.models import PostingStatus

    TransferService.submit(transfer, user=role_users["staff"])
    transfer.refresh_from_db()
    assert transfer.status == "submitted"
    assert transfer.journal_entry.status == PostingStatus.DRAFT


def test_approve_after_submit_posts_je(transfer, role_users):
    from apps.posting.models import GeneralLedger, PostingStatus

    TransferService.submit(transfer, user=role_users["staff"])
    TransferService.approve(transfer, user=role_users["head"])
    transfer.refresh_from_db()
    assert transfer.status == "approved"
    assert transfer.approved_by_id == role_users["head"].id
    assert transfer.journal_entry.status == PostingStatus.POSTED
    assert GeneralLedger.objects.filter(entry=transfer.journal_entry).count() == 2


def test_approve_before_submit_is_rejected(transfer, role_users):
    from apps.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        TransferService.approve(transfer, user=role_users["head"])


def test_reject_requires_note_then_revise_resubmit(transfer, role_users):
    from apps.core.exceptions import ValidationError
    from apps.posting.models import PostingStatus

    TransferService.submit(transfer, user=role_users["staff"])
    with pytest.raises(ValidationError):
        TransferService.reject(transfer, user=role_users["head"], note="")

    TransferService.reject(transfer, user=role_users["head"], note="wrong bank")
    transfer.refresh_from_db()
    assert transfer.status == "rejected"
    assert transfer.rejection_note == "wrong bank"
    assert transfer.rejected_by_id == role_users["head"].id

    TransferService.revise(transfer, user=role_users["staff"])
    transfer.refresh_from_db()
    assert transfer.status == "requested"
    assert transfer.rejection_note == ""

    TransferService.submit(transfer, user=role_users["staff"])
    TransferService.approve(transfer, user=role_users["head"])
    transfer.refresh_from_db()
    assert transfer.status == "approved"
    assert transfer.journal_entry.status == PostingStatus.POSTED


def test_edit_rebuilds_draft_je(transfer, banks, role_users):
    b_from, b_to = banks
    TransferService.update(
        transfer,
        from_account=b_from,
        to_account=b_to,
        amount="99999.00",
        purpose="Corrected sweep",
        reference="REF-2",
        check_no="777",
        transfer_date="2026-09-17",
        user=role_users["staff"],
    )
    transfer.refresh_from_db()
    assert transfer.amount == Decimal("99999.00")
    assert transfer.purpose == "Corrected sweep"
    assert transfer.reference == "REF-2"
    assert transfer.check_no == "777"
    lines = list(transfer.journal_entry.lines.order_by("line_no"))
    assert [line.description for line in lines] == ["Corrected sweep", "Corrected sweep"]
    assert transfer.journal_entry.total_debit == Decimal("99999.00")
    assert transfer.journal_entry.total_credit == Decimal("99999.00")


def test_edit_blocked_after_submit(transfer, banks, role_users):
    from apps.core.exceptions import ValidationError

    b_from, b_to = banks
    TransferService.submit(transfer, user=role_users["staff"])
    with pytest.raises(ValidationError):
        TransferService.update(
            transfer, from_account=b_from, to_account=b_to, amount="1.00",
            purpose="x", user=role_users["staff"],
        )


def test_audit_trail_records_lifecycle(transfer, role_users):
    from apps.ap.models import ActionLog

    TransferService.submit(transfer, user=role_users["staff"])
    TransferService.reject(transfer, user=role_users["head"], note="nope")
    TransferService.revise(transfer, user=role_users["staff"])
    actions = list(
        ActionLog.objects.filter(
            doc_type=ActionLog.DocType.TRANSFER, doc_id=transfer.id
        ).order_by("created_at", "id").values_list("action", flat=True)
    )
    assert actions == ["created", "submitted", "rejected", "revised"]


def test_approval_inbox_only_shows_submitted(transfer, role_users):
    from apps.core.approvals import pending_approval_queue

    assert all(
        i["kind"] != "transfer"
        for i in pending_approval_queue(role_users["head"])
    )
    TransferService.submit(transfer, user=role_users["staff"])
    items = [
        i for i in pending_approval_queue(role_users["head"]) if i["kind"] == "transfer"
    ]
    assert len(items) == 1
    assert items[0]["doc"].id == transfer.id
    assert items[0]["action"] == ("ui:transfer_approve", transfer.id)


# --- HTTP workflow ---------------------------------------------------------


def test_http_full_flow(client, transfer, role_users):
    from apps.posting.models import PostingStatus

    client.force_login(role_users["staff"])
    body = client.get(f"/cash/transfers/{transfer.id}/").content.decode()
    assert "Approval flow" in body
    assert f"/cash/transfers/{transfer.id}/submit/" in body

    resp = client.post(f"/cash/transfers/{transfer.id}/submit/")
    assert resp.status_code == 302
    transfer.refresh_from_db()
    assert transfer.status == "submitted"

    client.force_login(role_users["head"])
    body = client.get(f"/cash/transfers/{transfer.id}/").content.decode()
    assert f"/cash/transfers/{transfer.id}/approve/" in body
    assert f"/cash/transfers/{transfer.id}/reject/" in body

    resp = client.post(f"/cash/transfers/{transfer.id}/approve/")
    assert resp.status_code == 302
    transfer.refresh_from_db()
    assert transfer.status == "approved"
    assert transfer.journal_entry.status == PostingStatus.POSTED


def test_http_staff_cannot_approve(client, transfer, role_users):
    client.force_login(role_users["staff"])
    client.post(f"/cash/transfers/{transfer.id}/submit/")
    resp = client.post(f"/cash/transfers/{transfer.id}/approve/", follow=True)
    transfer.refresh_from_db()
    assert transfer.status == "submitted"  # unchanged
    assert b"was not moved" in resp.content or b"Accounting" in resp.content


def test_http_reject_then_revise_redirects_to_edit(client, transfer, role_users):
    client.force_login(role_users["staff"])
    client.post(f"/cash/transfers/{transfer.id}/submit/")

    client.force_login(role_users["head"])
    resp = client.post(f"/cash/transfers/{transfer.id}/reject/", {"note": "fix it"})
    assert resp.status_code == 302
    transfer.refresh_from_db()
    assert transfer.status == "rejected"

    client.force_login(role_users["staff"])
    resp = client.post(f"/cash/transfers/{transfer.id}/revise/")
    assert resp.status_code == 302
    assert resp["Location"] == f"/cash/transfers/{transfer.id}/edit/"
    transfer.refresh_from_db()
    assert transfer.status == "requested"


def test_http_edit_rebuilds_je(client, transfer, banks, role_users):
    b_from, b_to = banks
    client.force_login(role_users["staff"])
    resp = client.post(
        f"/cash/transfers/{transfer.id}/edit/",
        {
            "transfer_date": "2026-09-17",
            "line_from": str(b_from.id),
            "line_to": str(b_to.id),
            "line_amount": "12345.00",
            "line_purpose": "Edited purpose",
            "line_check_no": "",
        },
    )
    assert resp.status_code == 302
    transfer.refresh_from_db()
    assert transfer.purpose == "Edited purpose"
    assert transfer.amount == Decimal("12345.00")
    assert transfer.status == "requested"


# --- Forms -----------------------------------------------------------------


def test_create_form_get(client, banks, role_users):
    client.force_login(role_users["staff"])
    resp = client.get("/cash/transfers/new/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'data-line-grid="transfer"' in body
    assert 'name="line_from"' in body
    assert 'name="reference"' in body


def test_edit_form_get_prefilled(client, transfer, role_users):
    client.force_login(role_users["staff"])
    resp = client.get(f"/cash/transfers/{transfer.id}/edit/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert transfer.purpose in body
    assert f'value="{transfer.from_account_id}"' in body


def test_create_form_batch_posts_multiple(client, banks, role_users):
    from apps.cash.models import InterAccountTransfer

    client.force_login(role_users["staff"])
    resp = client.post(
        "/cash/transfers/new/",
        {
            "transfer_date": "2026-09-15",
            "reference": "batch-ref",
            "line_from": [banks[0].id, banks[0].id],
            "line_to": [banks[1].id, banks[1].id],
            "line_amount": ["1,000.00", "2,000.00"],
            "line_purpose": ["one", "two"],
            "line_check_no": ["111", "222"],
        },
    )
    assert resp.status_code == 302
    transfers = list(InterAccountTransfer.objects.order_by("id"))
    assert [t.amount for t in transfers] == [Decimal("1000.00"), Decimal("2000.00")]
    assert [t.check_no for t in transfers] == ["111", "222"]
    assert all(t.reference == "batch-ref" for t in transfers)


# --- FTV header ------------------------------------------------------------


def test_ftv_print_header_has_form_fields(client, transfer, role_users):
    client.force_login(role_users["staff"])
    body = client.get(f"/cash/transfers/{transfer.id}/print/").content.decode()
    assert "ACCOUNTING DEPARTMENT" in body
    for label in ("VOUCHER REF #:", "DATE:", "TRANSFER TYPE:", "PREPARED BY:"):
        assert label in body