"""Inter-account transfer detail page, per-transfer exports, JE source
designation, and approval-inbox integration (ADR-030).

These tests pin the transfer flow to the same shape as RFP/CV/JE: a dedicated
detail page with PDF/Excel/CSV/Print actions, a proper source-document
designation on the linked JE, and visibility in the head's approval inbox.
"""

import pytest

from apps.cash.models import BankAccount
from apps.cash.services import TransferService

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
        purpose="Fund transfer to MB-CHK (Metrobank)",
        reference="REF-123",
        transfer_date="2026-09-17",
        segment=segment,
        user=role_users["staff"],
    )


def test_transfer_je_carries_ftv_source_designation(transfer):
    """The transfer JE designates its originating FTV voucher, like RFP/CV."""
    entry = transfer.journal_entry
    assert entry.source_doc_type == "FTV"
    assert entry.source_doc_no == transfer.voucher_no
    assert transfer.voucher_no in entry.description
    assert entry.ref_number == "REF-123"


def test_transfer_lines_use_purpose_as_description(transfer):
    """Both distribution lines carry the user-entered purpose (the per-line fix)."""
    lines = list(transfer.journal_entry.lines.order_by("line_no"))
    assert [line.description for line in lines] == [transfer.purpose, transfer.purpose]


def test_transfer_detail_renders_voucher(client, transfer, role_users):
    client.force_login(role_users["staff"])
    resp = client.get(f"/cash/transfers/{transfer.id}/")
    assert resp.status_code == 200
    body = resp.content.decode()

    assert transfer.voucher_no in body
    assert "1VB-CHK" in body and "MB-CHK" in body
    assert transfer.purpose in body
    assert "Particulars" in body
    assert "Balance" in body

    # Action set mirrors rfp_detail/cv_detail (PDF/Excel/CSV/Print).
    assert f"/cash/transfers/{transfer.id}/export/pdf/" in body
    assert f"/cash/transfers/{transfer.id}/export/xlsx/" in body
    assert f"/cash/transfers/{transfer.id}/export/csv/" in body
    assert f"/cash/transfers/{transfer.id}/print/" in body


def test_transfer_detail_requires_login(client, transfer):
    resp = client.get(f"/cash/transfers/{transfer.id}/")
    assert resp.status_code in (301, 302)
    assert "/login/" in resp["Location"]


def test_transfer_export_formats(client, transfer, role_users):
    client.force_login(role_users["staff"])

    pdf = client.get(f"/cash/transfers/{transfer.id}/export/pdf/")
    assert pdf.status_code == 200
    assert pdf["Content-Type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    xlsx = client.get(f"/cash/transfers/{transfer.id}/export/xlsx/")
    assert xlsx.status_code == 200
    assert xlsx.content[:2] == b"PK"  # real xlsx zip container

    csvr = client.get(f"/cash/transfers/{transfer.id}/export/csv/")
    assert csvr.status_code == 200
    body = csvr.content.decode()
    assert transfer.purpose in body
    assert "MB-CHK" in body and "1VB-CHK" in body


def test_head_sees_transfer_in_approval_queue(transfer, role_users):
    from apps.cash.services import TransferService
    from apps.core.approvals import pending_approval_queue

    TransferService.submit(transfer, user=role_users["staff"])
    items = pending_approval_queue(role_users["head"])
    transfer_items = [i for i in items if i["kind"] == "transfer"]
    assert transfer_items
    assert transfer_items[0]["doc"].id == transfer.id
    assert transfer_items[0]["action"] == ("ui:transfer_approve", transfer.id)
    assert transfer_items[0]["detail"] == ("ui:transfer_detail", transfer.id)


def test_staff_does_not_see_transfer_in_approval_queue(transfer, role_users):
    from apps.cash.services import TransferService
    from apps.core.approvals import pending_approval_queue

    TransferService.submit(transfer, user=role_users["staff"])
    items = pending_approval_queue(role_users["staff"])
    assert all(i["kind"] != "transfer" for i in items)


def test_detail_approve_posts_and_redirects_to_detail(client, transfer, role_users):
    from apps.cash.services import TransferService
    from apps.posting.models import PostingStatus

    TransferService.submit(transfer, user=role_users["staff"])
    client.force_login(role_users["head"])
    resp = client.post(f"/cash/transfers/{transfer.id}/approve/")
    assert resp.status_code == 302
    assert resp["Location"] == f"/cash/transfers/{transfer.id}/"

    transfer.refresh_from_db()
    assert transfer.status == "approved"
    assert transfer.journal_entry.status == PostingStatus.POSTED


def test_transfers_list_links_to_detail(client, transfer, role_users):
    client.force_login(role_users["staff"])
    resp = client.get("/cash/transfers/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"/cash/transfers/{transfer.id}/" in body
    assert transfer.voucher_no in body


def _make_transfer(banks, segment, role_users, *, purpose, amount, day):
    b_from, b_to = banks
    return TransferService.transfer(
        from_account=b_from, to_account=b_to, amount=amount,
        purpose=purpose, transfer_date=f"2026-09-{day}", segment=segment,
        user=role_users["staff"],
    )


def test_transfers_list_shows_filter_bar(client, transfer, role_users):
    client.force_login(role_users["staff"])
    body = client.get("/cash/transfers/").content.decode()
    assert 'name="q"' in body
    assert 'name="status"' in body
    assert 'name="from_account"' in body
    assert 'name="to_account"' in body
    assert 'hx-target="#transfers-table"' in body


def test_transfers_list_search_filters_rows(client, banks, segment, role_users):
    _make_transfer(banks, segment, role_users, purpose="Payroll sweep ABC", amount="1000.00", day="10")
    _make_transfer(banks, segment, role_users, purpose="Fuel reimbursement XYZ", amount="2000.00", day="11")
    client.force_login(role_users["staff"])
    body = client.get("/cash/transfers/?q=Payroll").content.decode()
    assert "Payroll sweep ABC" in body
    assert "Fuel reimbursement XYZ" not in body


def test_transfers_list_search_matches_bank_code(client, banks, segment, role_users):
    _make_transfer(banks, segment, role_users, purpose="Sweep", amount="1000.00", day="10")
    client.force_login(role_users["staff"])
    body = client.get("/cash/transfers/?q=MB-CHK").content.decode()
    assert "Sweep" in body
    body_miss = client.get("/cash/transfers/?q=DOES-NOT-EXIST").content.decode()
    assert "No transfers match" in body_miss


def test_transfers_list_filters_by_status(client, banks, segment, role_users):
    approved = _make_transfer(banks, segment, role_users, purpose="Approved move", amount="1000.00", day="10")
    _make_transfer(banks, segment, role_users, purpose="Pending move", amount="2000.00", day="11")
    TransferService.submit(approved, user=role_users["staff"])
    TransferService.approve(approved, user=role_users["head"])
    client.force_login(role_users["staff"])

    body = client.get("/cash/transfers/?status=approved").content.decode()
    assert "Approved move" in body
    assert "Pending move" not in body

    body = client.get("/cash/transfers/?status=requested").content.decode()
    assert "Pending move" in body
    assert "Approved move" not in body


def test_transfers_list_htmx_returns_fragment_only(client, transfer, role_users):
    client.force_login(role_users["staff"])
    resp = client.get("/cash/transfers/?q=Fund", HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    body = resp.content.decode()
    # Fragment carries the table (and pagination), not the page chrome/form.
    assert "transfers-table" not in body
    assert "New transfer(s)" not in body
    assert transfer.purpose in body


def test_transfers_export_honours_filters(client, banks, segment, role_users):
    _make_transfer(banks, segment, role_users, purpose="Payroll sweep ABC", amount="1000.00", day="10")
    _make_transfer(banks, segment, role_users, purpose="Fuel reimbursement XYZ", amount="2000.00", day="11")
    client.force_login(role_users["staff"])
    body = client.get("/cash/transfers/export/?format=csv&q=Payroll").content.decode()
    assert "Payroll sweep ABC" in body
    assert "Fuel reimbursement XYZ" not in body