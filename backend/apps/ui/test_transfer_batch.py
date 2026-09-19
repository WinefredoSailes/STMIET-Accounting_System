"""Inter-account transfer batch grid tests (add/remove lines, ADR-030).

The transfers screen is a line grid where each added row is a full transfer
leg (From → To → Amount → optional Purpose). Every non-blank row requests its
own transfer + DRAFT JE; nothing posts until the head approves each transfer.
The batch is atomic — one invalid line rejects all legs.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.cash.models import BankAccount, InterAccountTransfer

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(db, role_users):
    from django.test import Client

    c = Client()
    c.force_login(role_users["staff"])
    return c


@pytest.fixture
def banks(db, company, segment, accounts):
    return {
        "b1": BankAccount.objects.create(
            code="BDO-1", name="BDO Checking", account_type="checking",
            bank_name="BDO", gl_account=accounts["10110"], company=company,
        ),
        "b2": BankAccount.objects.create(
            code="BDO-2", name="BDO Savings", account_type="savings",
            bank_name="BDO", gl_account=accounts["10010"], company=company,
        ),
        "b3": BankAccount.objects.create(
            code="PNB-1", name="PNB Checking", account_type="checking",
            bank_name="PNB", gl_account=accounts["12020"], company=company,
        ),
    }


def test_batch_requests_one_transfer_and_draft_je_per_line(client, banks):
    resp = client.post("/cash/transfers/new/", {
        "transfer_date": "2026-09-15",
        "line_from": [banks["b1"].id, banks["b2"].id],
        "line_to": [banks["b2"].id, banks["b3"].id],
        "line_amount": ["10,000.00", "20,000.00"],
        "line_purpose": ["sweep to BDO savings", "cover PNB payroll"],
    })
    assert resp.status_code == 302
    transfers = list(InterAccountTransfer.objects.order_by("id"))
    assert len(transfers) == 2
    assert transfers[0].amount == Decimal("10000.00")
    assert transfers[1].amount == Decimal("20000.00")
    assert transfers[0].from_account_id == banks["b1"].id
    assert transfers[0].to_account_id == banks["b2"].id
    assert all(t.journal_entry_id for t in transfers)
    # Requested, not posted: DRAFT JE awaits head approval (no threshold).
    from apps.posting.models import PostingStatus

    assert all(t.status == "requested" for t in transfers)
    assert all(t.journal_entry.status == PostingStatus.DRAFT for t in transfers)
    assert transfers[0].voucher_no.startswith("FTV-2026-")
    assert transfers[1].voucher_no.startswith("FTV-2026-")
    assert transfers[0].voucher_no != transfers[1].voucher_no


def test_head_approve_posts_batch_transfer(client, banks, role_users):
    from apps.cash.services import TransferService

    client.post("/cash/transfers/new/", {
        "transfer_date": "2026-09-15",
        "line_from": [banks["b1"].id],
        "line_to": [banks["b2"].id],
        "line_amount": ["10,000.00"],
        "line_purpose": ["sweep"],
    })
    transfer = InterAccountTransfer.objects.get()
    client.force_login(role_users["head"])
    resp = client.post(f"/cash/transfers/{transfer.id}/approve/")
    assert resp.status_code == 302
    transfer.refresh_from_db()
    assert transfer.status == "approved"
    assert transfer.approved_by_id == role_users["head"].id
    from apps.posting.models import PostingStatus

    assert transfer.journal_entry.status == PostingStatus.POSTED


def test_batch_skips_blank_template_row(client, banks):
    resp = client.post("/cash/transfers/new/", {
        "transfer_date": "2026-09-15",
        "line_from": [banks["b1"].id, "", banks["b2"].id],
        "line_to": [banks["b2"].id, "", banks["b3"].id],
        "line_amount": ["5,000.00", "", "7,500.00"],
        "line_purpose": ["one", "", "three"],
    })
    assert resp.status_code == 302
    assert InterAccountTransfer.objects.count() == 2


def test_batch_is_atomic_on_invalid_line(client, banks):
    resp = client.post("/cash/transfers/new/", {
        "transfer_date": "2026-09-15",
        "line_from": [banks["b1"].id, banks["b2"].id],  # second leg: same From & To
        "line_to": [banks["b2"].id, banks["b2"].id],
        "line_amount": ["10,000.00", "5,000.00"],
        "line_purpose": ["ok leg", "bad leg"],
    })
    assert resp.status_code == 302
    assert InterAccountTransfer.objects.count() == 0
    # Nothing from the first (valid) leg was persisted either — batch is atomic.
    from apps.posting.models import JournalEntry

    assert JournalEntry.objects.filter(source_doc_type="TRANSFER").count() == 0


def test_batch_defaults_blank_purpose(client, banks):
    resp = client.post("/cash/transfers/new/", {
        "line_from": [banks["b1"].id],
        "line_to": [banks["b2"].id],
        "line_amount": ["3,000.00"],
        "line_purpose": [""],
    })
    assert resp.status_code == 302
    t = InterAccountTransfer.objects.get()
    assert t.purpose == f"Fund transfer to {banks['b2'].code} ({banks['b2'].bank_name})"


def test_batch_requires_one_line(client, banks):
    resp = client.post("/cash/transfers/new/", {
        "transfer_date": "2026-09-15",
        "line_from": [""],
        "line_to": [""],
        "line_amount": [""],
        "line_purpose": [""],
    })
    assert resp.status_code == 302
    assert InterAccountTransfer.objects.count() == 0


def test_batch_keeps_full_purpose_text(client, banks):
    """Long purposes are stored in full (matches RFP/CV/JE 500-char behavior)."""
    purpose = ("Payroll coverage " * 28).strip()  # ~475 chars
    assert 450 < len(purpose) <= 500
    resp = client.post("/cash/transfers/new/", {
        "transfer_date": "2026-09-15",
        "line_from": [banks["b1"].id],
        "line_to": [banks["b2"].id],
        "line_amount": ["10,000.00"],
        "line_purpose": [purpose],
    })
    assert resp.status_code == 302
    t = InterAccountTransfer.objects.get()
    assert t.purpose == purpose
    assert len(t.purpose) == len(purpose)


def test_approve_catches_up_already_posted_je(client, banks, role_users):
    """If a transfer's JE was already posted out-of-band, approving the
    transfer catches it up to approved without re-posting or duplicating GL."""
    from apps.posting.models import GeneralLedger, PostingStatus
    from apps.posting.services import PostingService

    client.post("/cash/transfers/new/", {
        "transfer_date": "2026-09-15",
        "line_from": [banks["b1"].id],
        "line_to": [banks["b2"].id],
        "line_amount": ["10,000.00"],
        "line_purpose": ["sweep"],
    })
    transfer = InterAccountTransfer.objects.get()
    # Out-of-band: the JE is posted directly (e.g. through the JE module).
    PostingService.post(transfer.journal_entry)
    transfer.journal_entry.refresh_from_db()
    assert transfer.journal_entry.status == PostingStatus.POSTED
    assert GeneralLedger.objects.filter(entry=transfer.journal_entry).count() == 2
    assert transfer.status == "requested"

    client.force_login(role_users["head"])
    resp = client.post(f"/cash/transfers/{transfer.id}/approve/")
    assert resp.status_code == 302
    transfer.refresh_from_db()
    assert transfer.status == "approved"
    assert transfer.approved_by_id == role_users["head"].id
    # The JE was NOT re-posted and the GL was NOT duplicated.
    assert GeneralLedger.objects.filter(entry=transfer.journal_entry).count() == 2