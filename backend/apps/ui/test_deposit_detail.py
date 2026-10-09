"""Bank Deposit JE link regression (prod 500, Oct-2026).

JournalEntry 672's "Bank Deposit" source-doc link crashed ``je_detail``
with ``NoReverseMatch: Reverse for 'receipt_list' with arguments '(136,)'``:
``entry_source_doc`` pointed ``ar_deposits`` at ``ui:receipt_list`` (a
pk-less list route) while ``je_detail.html`` reverses
``{% url source_doc.detail source_doc.pk %}``. The deposit now owns a real
detail page (``ui:deposit_detail``) like every other source document, so the
JE link, the manual-JE guard redirect, and the receipt's deposit box all
resolve to the deposit slip itself — not to some other receipt's id.
"""

from datetime import date

import pytest
from django.urls import reverse

from apps.ar.models import Customer
from apps.ar.services import CollectionService, DepositService
from apps.posting.services import entry_source_doc

pytestmark = pytest.mark.django_db


@pytest.fixture
def customer(db, segment, company):
    return Customer.objects.create(code="CDEP", name="Deposit Client")


def _posted_receipt(customer, segment, bank, user, head, amount="5000.00"):
    receipt = CollectionService.create_receipt(
        customer=customer,
        transaction_date=date(2026, 1, 15),
        amount=amount,
        cash_account=bank,
        segment=segment,
        created_by=user,
    )
    CollectionService.submit(receipt, user=user)
    CollectionService.approve(receipt, user=head)
    receipt.refresh_from_db()
    assert receipt.journal_entry_id is not None
    return receipt


@pytest.fixture
def deposit(customer, segment, accounts, role_users):
    receipt = _posted_receipt(
        customer, segment, accounts["10110"], role_users["staff"], role_users["head"]
    )
    dep = DepositService.record_deposit(
        receipts=[receipt],
        bank_account=accounts["10110"],
        transaction_date=date(2026, 1, 20),
        user=role_users["head"],
    )
    assert dep.journal_entry_id is not None
    return dep


def test_entry_source_doc_points_deposit_at_deposit_detail(deposit):
    src = entry_source_doc(deposit.journal_entry)
    assert src == {
        "label": "Bank Deposit",
        "detail": "ui:deposit_detail",
        "pk": deposit.id,
    }


def test_deposit_detail_reverses_with_deposit_pk(deposit):
    assert reverse("ui:deposit_detail", args=[deposit.id]) == f"/ar/deposits/{deposit.id}/"


def test_je_detail_renders_for_deposit_entry(client, deposit, role_users):
    """The prod crash: GET /journal/<deposit JE> 500'd on the source-doc link."""
    client.force_login(role_users["head"])
    resp = client.get(f"/journal/{deposit.journal_entry_id}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"/ar/deposits/{deposit.id}/" in body
    assert "Bank Deposit" in body


def test_deposit_detail_renders_slip_receipts_and_je(client, deposit, role_users):
    client.force_login(role_users["head"])
    resp = client.get(f"/ar/deposits/{deposit.id}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert (deposit.deposit_no or f"Deposit #{deposit.id}") in body
    receipt = deposit.receipts.first()
    assert receipt is not None
    assert receipt.receipt_no in body
    assert f"/ar/receipts/{receipt.id}/" in body
    assert deposit.journal_entry.entry_no in body
    assert f"/journal/{deposit.journal_entry_id}/" in body


def test_receipt_detail_links_to_its_deposit(client, deposit, role_users):
    client.force_login(role_users["head"])
    receipt = deposit.receipts.first()
    resp = client.get(f"/ar/receipts/{receipt.id}/")
    assert resp.status_code == 200
    assert f"/ar/deposits/{deposit.id}/" in resp.content.decode()


def test_deposit_detail_is_gated_to_receipts_screen():
    from apps.ui.screens import screen_for_url_name

    assert screen_for_url_name("deposit_detail") == "receipt_list"
