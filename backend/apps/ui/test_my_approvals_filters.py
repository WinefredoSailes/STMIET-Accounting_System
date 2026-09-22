"""Phase C — My Approvals filter bar (kind / search / date window).

The filters are applied server-side in the view, in memory, before
``group_by_role``, so the grouped table and the badge always agree.
"""

from datetime import date

import pytest

from apps.ar.models import ARInvoice, Customer
from apps.ar.services import InvoiceService
from apps.foundation.models import UserProfile
from apps.posting.models import JournalEntry

pytestmark = pytest.mark.django_db


def _make_si(customer, segment, user, txn_date, label="DIESEL"):
    invoice = InvoiceService.create_invoice(
        customer=customer,
        transaction_date=txn_date,
        segment=segment,
        is_paid_on_delivery=False,
        lines=[{"product_code": label, "description": "", "quantity": "1", "unit_price": "100.00"}],
        created_by=user,
    )
    InvoiceService.submit(invoice, user=user)
    return invoice


def _submit_je_through_ui(client, user, company, segment, accounts, transaction_date="2026-01-15"):
    client.force_login(user)
    resp = client.post(
        "/journal/new/",
        {
            "transaction_date": transaction_date,
            "source_doc_type": "JE",
            "account": [accounts["10010"].id, accounts["20000"].id],
            "line_segment": [segment.id, segment.id],
            "debit": ["1000.00", ""],
            "credit": ["", "1000.00"],
            "line_description": ["Cash in", "AP"],
        },
    )
    je = JournalEntry.objects.first()
    client.post(f"/journal/{je.id}/submit/")
    return je


def test_kind_filter_narrows_to_invoices(
    client, role_users, company, segment, accounts, fiscal_period
):
    head_client = type(client)()
    head_client.force_login(role_users["head"])

    # One invoice + one journal entry both wait on the head.
    customer = Customer.objects.create(code="C001", name="Filter Test Client")
    _make_si(customer, segment, role_users["staff"], date(2026, 1, 15))
    je = _submit_je_through_ui(
        client, role_users["staff"], company, segment, accounts
    )

    unfiltered = head_client.get("/approvals/")
    body = unfiltered.content.decode()
    assert "SI-2026-00001" in body
    assert f"/journal/{je.id}/" in body

    filtered = head_client.get("/approvals/?kind=invoice")
    body = filtered.content.decode()
    assert "SI-2026-00001" in body
    assert f"/journal/{je.id}/" not in body
    # Document-type filter dropdown lists the invoice kind
    assert 'value="invoice"' in body
    assert "Sales Invoices" in body
    # Dropdown shows every kind even when it has nothing pending (static list)
    assert "Check Vouchers" in body


def test_search_filter_matches_number_or_title(
    client, role_users, company, segment, accounts, fiscal_period
):
    head_client = type(client)()
    head_client.force_login(role_users["head"])

    customer = Customer.objects.create(code="C002", name="Hopedale Trading")
    _make_si(customer, segment, role_users["staff"], date(2026, 1, 15))
    je = _submit_je_through_ui(client, role_users["staff"], company, segment, accounts)

    # match by invoice number
    body = head_client.get("/approvals/?q=SI-2026").content.decode()
    assert "SI-2026-00001" in body
    assert "SI-2026-00001" in head_client.get("/approvals/?kind=invoice").content.decode()

    # match by customer name in the SI title (JE title won't contain it)
    body = head_client.get("/approvals/?q=hopedale").content.decode()
    assert "SI-2026-00001" in body
    assert f"/journal/{je.id}/" not in body


def test_date_window_filter(client, role_users, company, segment, accounts, fiscal_period):
    head_client = type(client)()
    head_client.force_login(role_users["head"])

    customer = Customer.objects.create(code="C003", name="Window Test Client")
    early = _make_si(customer, segment, role_users["staff"], date(2026, 1, 5))
    late = _make_si(customer, segment, role_users["staff"], date(2026, 1, 25))

    body = head_client.get("/approvals/?from=2026-01-20").content.decode()
    assert late.invoice_no in body
    assert early.invoice_no not in body

    body = head_client.get("/approvals/?to=2026-01-10").content.decode()
    assert early.invoice_no in body
    assert late.invoice_no not in body


def test_clear_filters_link_and_filtered_empty_state(
    client, role_users, company, segment, accounts, fiscal_period
):
    head_client = type(client)()
    head_client.force_login(role_users["head"])

    # a filter that matches nothing shows the filtered-empty state + clear link
    body = head_client.get("/approvals/?kind=invoice").content.decode()
    assert "No documents match the current filters" in body
    assert "/approvals/" in body  # clear link target