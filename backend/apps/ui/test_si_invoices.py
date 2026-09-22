"""Phase B — Sales Invoice (SI) service + UI coverage.

Covers the SI lifecycle (draft -> submitted -> posted), the two revenue
posting paths (paid-on-delivery vs credit sale), the advance-coverage gate,
Head-only approval/rejection, VAT extraction, and the My Approvals queue."""

from datetime import date
from decimal import Decimal

import pytest

from apps.ar.models import ARInvoice, ARInvoiceLine, Customer, ReceiptStatus
from apps.ar.services import (
    CollectionService,
    InvoiceService,
    segment_sales_account,
    segment_unearned_account,
)
from apps.core.approvals import pending_approval_queue
from apps.foundation.models import Account
from apps.posting.models import PostingStatus

pytestmark = pytest.mark.django_db

LINES_15000 = [
    {
        "product_code": "DIESEL",
        "description": "Diesel delivery 1,000L @ 15.00",
        "quantity": "1000",
        "unit_price": "15.00",
    }
]


@pytest.fixture
def sales_account(db, accounts):
    """The DHPP Sales (revenue) COA account the SI Cr side resolves to."""
    return Account.objects.create(
        code="40000",
        name="Sales - Fuel Hauling",
        account_type="revenue",
        segment=Account.segment_for_code("40000"),
    )


@pytest.fixture
def customer(db, sales_account):
    return Customer.objects.create(
        code="C001",
        name="Test Fuel Client",
        tin="000-000-000-000",
        owner_name="Tester",
    )


@pytest.fixture
def draft_invoice(customer, segment):
    return InvoiceService.create_invoice(
        customer=customer,
        transaction_date=date(2026, 1, 15),
        segment=segment,
        is_paid_on_delivery=False,
        lines=LINES_15000,
        created_by=None,
    )


def _post_unearned_collection(customer, segment, accounts, user, amount="20000.00"):
    """Post an un-applied collection so the customer holds an advance."""
    receipt = CollectionService.create_receipt(
        customer=customer,
        transaction_date=date(2026, 1, 10),
        cash_account=accounts["10010"],
        payment_method="cash",
        amount=amount,
        segment=segment,
        created_by=user,
    )
    CollectionService.submit(receipt, user=user)
    CollectionService.approve(receipt, user=user)
    assert receipt.status == ReceiptStatus.POSTED
    return receipt


# ---------------------------------------------------------------------- number & create


def test_si_numbering_and_line_amounts(customer, segment, sales_account):
    invoice = InvoiceService.create_invoice(
        customer=customer,
        transaction_date=date(2026, 1, 15),
        segment=segment,
        is_paid_on_delivery=False,
        lines=LINES_15000,
        created_by=None,
    )
    assert invoice.status == "draft"
    assert invoice.invoice_no.startswith("SI-2026-")
    assert invoice.journal_entry_id is None
    assert invoice.total == Decimal("15000.00")
    line = invoice.lines.get()
    assert line.product_code == "DIESEL"
    assert line.quantity == Decimal("1000.00")
    assert line.unit_price == Decimal("15.00")
    assert line.amount == Decimal("15000.00")
    # Account resolvers from the segment maps
    assert segment_sales_account(segment).code == "40000"
    assert segment_unearned_account(segment).code == "21000"


def test_line_validation_requires_product_code(customer, segment):
    with pytest.raises(Exception, match="product code"):
        InvoiceService.create_invoice(
            customer=customer,
            transaction_date=date(2026, 1, 15),
            segment=segment,
            is_paid_on_delivery=False,
            lines=[{"product_code": "", "quantity": "1", "unit_price": "10.00"}],
        )


def test_edit_draft_recomputes_total(customer, segment, draft_invoice):
    updated = InvoiceService.update_draft(
        invoice=draft_invoice,
        lines=[
            {"product_code": "DIESEL", "description": "", "quantity": "2000", "unit_price": "15.00"},
        ],
        user=None,
    )
    assert updated.total == Decimal("30000.00")
    assert updated.lines.count() == 1


def test_cannot_edit_submitted(customer, segment, draft_invoice, role_users):
    InvoiceService.submit(draft_invoice, user=role_users["staff"])
    with pytest.raises(Exception, match="Only draft invoices can be edited"):
        InvoiceService.update_draft(invoice=draft_invoice, lines=LINES_15000, user=None)


# ---------------------------------------------------------------------- submit / approve path


def test_submit_then_approve_credit_sale_posts_revenue_je(
    customer, segment, draft_invoice, role_users
):
    submitted = InvoiceService.submit(draft_invoice, user=role_users["staff"])
    assert submitted.status == "submitted"

    approved = InvoiceService.approve(submitted, user=role_users["head"])
    assert approved.status == "open"  # credit sale opens a live receivable
    assert approved.approved_by == role_users["head"]

    entry = approved.journal_entry
    assert entry is not None
    assert entry.status == PostingStatus.POSTED
    assert entry.source_doc_type == "SI"
    lines = {l.account.code: l for l in entry.lines.all()}
    assert lines["12020"].debit == Decimal("15000.00")  # Dr AR (fuel => 12030? 12020 first)
    assert lines["40000"].credit == Decimal("15000.00")  # Cr Sales
    assert entry.total_debit == entry.total_credit == Decimal("15000.00")
    assert entry.is_balanced  # Dr AR | Cr Sales
    # VAT computation extracted
    from apps.tax.models import VATComputation

    assert VATComputation.objects.filter(invoice=approved).exists()


def test_staff_cannot_approve(customer, segment, draft_invoice, role_users):
    InvoiceService.submit(draft_invoice, user=role_users["staff"])
    with pytest.raises(Exception, match="head"):
        InvoiceService.approve(draft_invoice, user=role_users["staff"])


def test_reject_returns_to_draft_with_note(customer, segment, draft_invoice, role_users):
    InvoiceService.submit(draft_invoice, user=role_users["staff"])
    rejected = InvoiceService.reject(
        draft_invoice, user=role_users["head"], note="Wrong customer segment."
    )
    assert rejected.status == "draft"
    assert rejected.rejection_note == "Wrong customer segment."
    assert rejected.journal_entry_id is None

    # revise → resubmit → approve works again
    revised = InvoiceService.update_draft(
        invoice=rejected,
        segment=segment,
        transaction_date=date(2026, 1, 16),
        is_paid_on_delivery=False,
        lines=LINES_15000,
        user=role_users["staff"],
    )
    InvoiceService.submit(revised, user=role_users["staff"])  # clears the rejection trail
    revised.refresh_from_db()
    assert revised.rejection_note == ""
    approved = InvoiceService.approve(revised, user=role_users["head"])
    assert approved.status == "open"


def test_reject_requires_note(customer, segment, draft_invoice, role_users):
    InvoiceService.submit(draft_invoice, user=role_users["staff"])
    with pytest.raises(Exception, match="rejection note"):
        InvoiceService.reject(draft_invoice, user=role_users["head"], note="")


# ---------------------------------------------------------------------- paid-on-delivery path


def test_pod_blocks_without_advance(customer, segment, draft_invoice, role_users, accounts):
    InvoiceService.update_draft(
        invoice=draft_invoice,
        is_paid_on_delivery=True,
        user=role_users["staff"],
    )
    InvoiceService.submit(draft_invoice, user=role_users["staff"])
    with pytest.raises(Exception, match="record the collection first"):
        InvoiceService.approve(draft_invoice, user=role_users["head"])


def test_pod_posts_unearned_to_sales(
    customer, segment, draft_invoice, role_users, accounts
):
    _post_unearned_collection(customer, segment, accounts, role_users["head"])
    InvoiceService.update_draft(invoice=draft_invoice, is_paid_on_delivery=True, user=None)
    InvoiceService.submit(draft_invoice, user=role_users["staff"])
    approved = InvoiceService.approve(draft_invoice, user=role_users["head"])

    assert approved.status == "posted"  # POD is closed by its advance
    entry = approved.journal_entry
    lines = {l.account.code: l for l in entry.lines.all()}
    assert lines["21000"].debit == Decimal("15000.00")  # Dr Unearned
    assert lines["40000"].credit == Decimal("15000.00")  # Cr Sales
    assert entry.total_debit == entry.total_credit == Decimal("15000.00")
    # advance consumed: only 5,000 unearned now
    assert InvoiceService.available_unearned(customer) == Decimal("5000.00")


def test_pod_uses_latest_available_advance(customer, segment, role_users, accounts):
    _post_unearned_collection(customer, segment, accounts, role_users["head"], amount="10000.00")
    invoice = InvoiceService.create_invoice(
        customer=customer,
        transaction_date=date(2026, 1, 15),
        segment=segment,
        is_paid_on_delivery=True,
        lines=LINES_15000,
        created_by=role_users["staff"],
    )
    InvoiceService.submit(invoice, user=role_users["staff"])
    with pytest.raises(Exception, match="record the collection first"):
        InvoiceService.approve(invoice, user=role_users["head"])


# ---------------------------------------------------------------------- my approvals queue


def test_submitted_si_appears_in_head_queue(customer, segment, draft_invoice, role_users):
    InvoiceService.submit(draft_invoice, user=role_users["staff"])
    items = pending_approval_queue(role_users["head"])
    kinds = [i["kind"] for i in items]
    assert "invoice" in kinds
    si_items = [i for i in items if i["kind"] == "invoice"]
    assert len(si_items) == 1
    assert si_items[0]["number"] == draft_invoice.invoice_no
    assert si_items[0]["detail"] == ("ui:si_detail", draft_invoice.id)
    assert si_items[0]["action"] == ("ui:si_approve", draft_invoice.id)
    # draft SIs never queue; approved SIs drop out
    assert not any(i["kind"] == "invoice" for i in pending_approval_queue(role_users["staff"]))
    InvoiceService.approve(draft_invoice, user=role_users["head"])
    assert not any(i["kind"] == "invoice" for i in pending_approval_queue(role_users["head"]))


# ---------------------------------------------------------------------- views / print


def test_si_pages_flow(client, customer, segment, role_users):
    staff_client = client
    staff_client.force_login(role_users["staff"])
    head_client = type(client)()
    head_client.force_login(role_users["head"])

    # create form GET
    resp = staff_client.get("/ar/invoices/new/")
    assert resp.status_code == 200
    assert "Line Items" in resp.content.decode()

    # POST the form → draft
    resp = staff_client.post(
        "/ar/invoices/new/",
        {
            "customer": str(customer.id),
            "transaction_date": "2026-01-15",
            "segment": str(segment.id),
            "product_code": ["DIESEL"],
            "quantity": ["1000"],
            "unit_price": ["15.00"],
            "line_description": [""],
        },
    )
    assert resp.status_code == 302
    invoice = ARInvoice.objects.latest("id")
    assert invoice.status == "draft"
    assert invoice.total == Decimal("15000.00")

    # list + detail + print render
    assert staff_client.get("/ar/invoices/").status_code == 200
    detail = staff_client.get(f"/ar/invoices/{invoice.id}/")
    assert detail.status_code == 200
    assert invoice.invoice_no in detail.content.decode()
    assert staff_client.get(f"/ar/invoices/{invoice.id}/print/").status_code == 200

    # submit → head approves → revenue JE posted
    staff_client.post(f"/ar/invoices/{invoice.id}/submit/")
    invoice.refresh_from_db()
    assert invoice.status == "submitted"
    head_client.post(f"/ar/invoices/{invoice.id}/approve/")
    invoice.refresh_from_db()
    assert invoice.status == "open"
    assert invoice.journal_entry_id is not None


def test_si_reject_from_ui(client, customer, segment, role_users):
    staff_client = client
    staff_client.force_login(role_users["staff"])
    head_client = type(client)()
    head_client.force_login(role_users["head"])

    resp = staff_client.post(
        "/ar/invoices/new/",
        {
            "customer": str(customer.id),
            "transaction_date": "2026-01-15",
            "segment": str(segment.id),
            "product_code": ["DIESEL"],
            "quantity": ["1000"],
            "unit_price": ["15.00"],
            "line_description": [""],
        },
    )
    invoice = ARInvoice.objects.latest("id")
    staff_client.post(f"/ar/invoices/{invoice.id}/submit/")
    head_client.post(f"/ar/invoices/{invoice.id}/reject/", {"note": "Re-check the rate"})
    invoice.refresh_from_db()
    assert invoice.status == "draft"
    assert invoice.rejection_note == "Re-check the rate"