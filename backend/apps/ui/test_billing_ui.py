"""Billing UI smoke tests: form -> submit -> approve -> post, plus the
captured RFP reference surfacing on the General Journal screen.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.ap.models import RFPDocument, Supplier
from apps.billing.models import BillingDocument, BillingStatus
from apps.billing.services import BillingService

pytestmark = pytest.mark.django_db


@pytest.fixture
def billing_accounts(db):
    from apps.foundation.models import Account

    rows = [
        ("15550", "Reimbursable Expenses—Unbilled", "asset"),
        ("15560", "Due from Customers—Unbilled", "asset"),
        ("41010", "Sales-Retail", "revenue"),
    ]
    return {
        code: Account.objects.create(
            code=code, name=name, account_type=atype, segment=Account.segment_for_code(code)
        )
        for code, name, atype in rows
    }


@pytest.fixture
def supplier(db, segment):
    return Supplier.objects.create(code="S001", name="STPC Holdings", default_segment=segment)


@pytest.fixture
def posted_rfp(db, segment, supplier):
    return RFPDocument.objects.create(
        ap_number="A0001", rfp_date=date(2026, 1, 15), payee=supplier,
        segment=segment, amount=Decimal("1000.00"), status="posted",
    )


def _post_create(client, segment, billing_accounts, rfp):
    return client.post(
        "/billing/new/",
        {
            "billing_type": "stpc",
            "billing_date": "2026-02-01",
            "party_name": "STPC Holdings",
            "reference": "A0001",
            "particulars": "Intercompany service billing",
            "segment": str(segment.id),
            "rfp": str(rfp.id),
            "line_account": [str(billing_accounts["41010"].id), str(billing_accounts["15560"].id)],
            "line_segment": [str(segment.id), str(segment.id)],
            "line_debit": ["1000.00", ""],
            "line_credit": ["", "1000.00"],
            "line_description": ["Service billed", "Unbilled receivable"],
            "line_cost_center": ["OS", "OS"],
        },
    )


def test_billing_pages_render(client, segment, billing_accounts, posted_rfp, role_users):
    client.force_login(role_users["staff"])
    assert client.get("/billing/").status_code == 200
    assert client.get("/billing/new/").status_code == 200
    resp = client.get("/billing/rfp-options/?q=A0001")
    assert resp.status_code == 200
    assert b"A0001" in resp.content


def test_billing_rfp_prefill(segment, billing_accounts, posted_rfp, role_users):
    import json

    from django.test import Client
    from apps.ap.models import RFPLine

    RFPLine.objects.create(
        rfp=posted_rfp, line_no=1, side="dr", segment=segment,
        account=billing_accounts["41010"], amount=Decimal("1000.00"),
        description="Service billed", cost_center="OS",
    )
    RFPLine.objects.create(
        rfp=posted_rfp, line_no=2, side="cr", segment=segment,
        account=billing_accounts["15560"], amount=Decimal("1000.00"),
        description="Unbilled receivable", cost_center="OS",
    )
    client = Client()
    client.force_login(role_users["staff"])
    resp = client.get(f"/billing/rfp/{posted_rfp.id}/prefill/")
    assert resp.status_code == 200
    data = json.loads(resp.content)
    assert data["rfp_no"] == "A0001"
    assert data["party_name"] == "STPC Holdings"
    assert data["party_kind"] == "supplier"
    assert data["party_id"] == posted_rfp.payee_id
    assert len(data["lines"]) == 2
    assert data["lines"][0]["account_code"] == "41010"
    assert data["lines"][1]["side"] == "cr"


def test_billing_create_submit_approve_post_and_gj_note(
    client, segment, billing_accounts, posted_rfp, role_users
):
    client.force_login(role_users["staff"])
    resp = _post_create(client, segment, billing_accounts, posted_rfp)
    assert resp.status_code == 302
    billing = BillingDocument.objects.get()
    assert billing.status == BillingStatus.DRAFT
    assert billing.amount == Decimal("1000.00")

    assert client.get(f"/billing/{billing.id}/").status_code == 200

    client.post(f"/billing/{billing.id}/submit/")
    billing.refresh_from_db()
    assert billing.status == BillingStatus.SUBMITTED

    client.force_login(role_users["head"])
    client.post(f"/billing/{billing.id}/approve/")
    billing.refresh_from_db()
    assert billing.status == BillingStatus.APPROVED

    client.post(f"/billing/{billing.id}/post/")
    billing.refresh_from_db()
    assert billing.status == BillingStatus.POSTED
    assert billing.journal_entry_id
    assert billing.journal_entry.ref_number == "A0001"

    # The General Journal surfaces the RFP number + amount billed in the
    # Note/Reference column for the 15560 credit line.
    body = client.get("/journal/general/").content.decode()
    assert "RFP A0001" in body
    assert "billed 1,000.00" in body


def test_billing_export_xlsx(client, segment, billing_accounts, posted_rfp, role_users):
    client.force_login(role_users["head"])
    billing = BillingService.create_billing(
        billing_no="BI-2026-0009",
        billing_date=date(2026, 2, 1),
        billing_type="stpc",
        company=segment.company,
        segment=segment,
        party_name="STPC Holdings",
        lines=[
            {"side": "dr", "segment": segment, "account": billing_accounts["41010"],
             "amount": "500.00", "description": "x"},
            {"side": "cr", "segment": segment, "account": billing_accounts["15560"],
             "amount": "500.00", "description": "y"},
        ],
        rfp=posted_rfp,
        user=role_users["head"],
    )
    resp = client.get(f"/billing/{billing.id}/export/xlsx/")
    assert resp.status_code == 200
    assert resp["Content-Type"] in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    )


def test_print_page_renders(client, segment, billing_accounts, posted_rfp, role_users):
    client.force_login(role_users["head"])
    billing = BillingService.create_billing(
        billing_no="BI-2026-0010",
        billing_date=date(2026, 2, 1),
        billing_type="third_party",
        company=segment.company,
        segment=segment,
        party_name="Acme Corp",
        lines=[
            {"side": "dr", "segment": segment, "account": billing_accounts["41010"],
             "amount": "700.00", "description": "x"},
            {"side": "cr", "segment": segment, "account": billing_accounts["15560"],
             "amount": "700.00", "description": "y"},
        ],
        user=role_users["head"],
    )
    body = client.get(f"/billing/{billing.id}/print/").content.decode()
    assert "BILLING TRANSACTION" in body
    assert "BI-2026-0010" in body


def test_create_links_customer_party_fk(client, segment, billing_accounts, role_users):
    from apps.ar.models import Customer

    customer = Customer.objects.create(code="C001", name="Acme Corp")
    client.force_login(role_users["staff"])
    resp = client.post(
        "/billing/new/",
        {
            "billing_type": "third_party",
            "billing_date": "2026-02-01",
            "party_name": "Acme Corp",
            "party_kind": "customer",
            "party_id": str(customer.id),
            "segment": str(segment.id),
            "line_account": [str(billing_accounts["41010"].id), str(billing_accounts["15560"].id)],
            "line_segment": [str(segment.id), str(segment.id)],
            "line_debit": ["100.00", ""],
            "line_credit": ["", "100.00"],
        },
    )
    assert resp.status_code == 302
    billing = BillingDocument.objects.get()
    assert billing.customer_id == customer.id
    assert billing.supplier_id is None
    assert billing.party_name == "Acme Corp"


def test_create_links_supplier_party_fk(client, segment, billing_accounts, supplier, role_users):
    client.force_login(role_users["staff"])
    client.post(
        "/billing/new/",
        {
            "billing_type": "third_party",
            "billing_date": "2026-02-01",
            "party_name": "STPC Holdings",
            "party_kind": "supplier",
            "party_id": str(supplier.id),
            "segment": str(segment.id),
            "line_account": [str(billing_accounts["41010"].id), str(billing_accounts["15560"].id)],
            "line_segment": [str(segment.id), str(segment.id)],
            "line_debit": ["100.00", ""],
            "line_credit": ["", "100.00"],
        },
    )
    billing = BillingDocument.objects.get()
    assert billing.supplier_id == supplier.id
    assert billing.customer_id is None