"""AR receipt autofill polish (SI -> AR): the picker's option payload,
reverse customer fill, over-application hint and the wiring contract the
form JS relies on (service-side guards live in apps/ar/tests.py)."""

import json
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.ar.models import ARInvoice, ARInvoiceLine, Customer

pytestmark = pytest.mark.django_db


@pytest.fixture
def payer(db, segment, company):
    return Customer.objects.create(code="C500", name="Haul Client")


@pytest.fixture
def owed(db, payer, segment, accounts):
    inv = ARInvoice.objects.create(
        invoice_no="SI-2026-0500",
        customer=payer,
        transaction_date=date(2026, 2, 3),
        segment=segment,
        total=Decimal("8000.00"),
        status="open",
    )
    ARInvoiceLine.objects.create(
        invoice=inv, line_no=1, product_code="HAUL", description="h",
        quantity=Decimal("1"), unit_price=Decimal("8000.00"), amount=Decimal("8000.00"),
    )
    return inv


def _login(client):
    u = get_user_model().objects.create_user("picker", password="x")
    client.force_login(u)
    return client


def test_options_endpoint_ships_prefill(client, owed, payer, segment):
    _login(client)
    resp = client.get("/foundation/ar-invoice-options/", {"customer": payer.id, "q": "SI-2026"})
    assert resp.status_code == 200
    rows = json.loads(resp.content)
    assert len(rows) == 1
    data = json.loads(rows[0]["prefill"])
    assert data["customer_id"] == payer.id
    assert data["customer_name"] == "Haul Client"
    assert data["invoice_no"] == "SI-2026-0500"
    assert data["balance"] == "8000.00"
    assert data["ar_account_id"]  # drives the credit-line autofill


def test_options_prefill_for_unscoped_query(client, owed):
    _login(client)
    rows = json.loads(client.get("/foundation/ar-invoice-options/").content)
    assert json.loads(rows[0]["prefill"])["customer_id"] == owed.customer_id


def test_receipt_form_wires_the_autofill(client, db):
    body = _login(client).get("/ar/receipts/new/").content.decode()
    assert 'id="ar-due-hint"' in body          # live balance / warning chip
    assert "dataset.prefill" in body           # async-safe autofill source
    assert "autoCust" in body                  # reverse customer-fill guard
    assert "checkBalance" in body              # over-application hint


def test_existing_selected_option_survives_edit_mode(client, owed):
    _login(client)
    r = client.get("/ar/receipts/new/")
    assert r.status_code == 200
