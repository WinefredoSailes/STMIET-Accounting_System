"""End-to-end coverage for the customer subsidiary ledger page, its exports
(xlsx / csv / pdf), the print view, and the AR ledger flow audit.

Mirror of ``test_supplier_ledger.py`` for the AR receivable track (ADR-005):
invoices post as debit rows, approved collections post as credit rows, and a
draft (unapproved) collection never touches the ledger."""

from datetime import date
from decimal import Decimal

import pytest

from apps.ar.models import ARInvoice, ARInvoiceLine, Customer
from apps.ar.services import CollectionService

FORMATS = {
    "pdf": ("application/pdf", b"%PDF-"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"PK\x03\x04"),
    "csv": ("text/csv", None),
}


@pytest.fixture
def ledger_customer(db, company, segment, accounts, user):
    """A customer with one invoice (debit row) and one posted collection
    (credit row) in the ledger."""
    customer = Customer.objects.create(code="LC-01", name="Ledger Test Trading")
    inv = ARInvoice.objects.create(
        invoice_no="SI-L-2026-0001",
        customer=customer,
        transaction_date=date(2026, 1, 7),
        segment=segment,
        total=Decimal("5000.00"),
    )
    ARInvoiceLine.objects.create(
        invoice=inv, line_no=1, product_code="DIESEL",
        description="Ledger test fuel", quantity=Decimal("100"),
        unit_price=Decimal("50.00"), amount=Decimal("5000.00"),
    )
    CollectionService.record_collection(
        receipt_no="AR-L-2026-00001",
        customer=customer,
        transaction_date=date(2026, 1, 10),
        amount="2000.00",
        cash_account=accounts["10010"],
        segment=segment,
    )
    return customer


@pytest.mark.django_db
def test_ar_ledger_summary_page(client, user, ledger_customer):
    client.force_login(user)
    resp = client.get("/ar/ledger/")
    assert resp.status_code == 200
    body = resp.content.decode()
    # customer name must be resolved, never a literal template variable
    assert "Ledger Test Trading" in body
    assert "{{ customer.name }}" not in body
    assert "{{ r.code }}" not in body
    # per-customer SOA link must be present
    assert f"/ar/ledger/{ledger_customer.pk}/" in body


@pytest.mark.django_db
def test_ar_customer_ledger_page_renders(client, user, ledger_customer):
    client.force_login(user)
    resp = client.get(f"/ar/ledger/{ledger_customer.pk}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Ledger Test Trading" in body
    # invoice debit row + posted collection credit row
    assert "SI-L-2026-0001" in body
    assert "AR-L-2026-00001" in body
    assert "{{ customer.name }}" not in body
    assert "{{ supplier.code }}" not in body
    # export + print actions must be present
    for label in ("Excel", "PDF", "CSV"):
        assert f">{label}<" in body
    assert ">Print<" in body
    assert f"format=xlsx" in body


@pytest.mark.django_db
@pytest.mark.parametrize("fmt", ["xlsx", "csv", "pdf"])
def test_ar_customer_ledger_export_formats(client, user, ledger_customer, fmt):
    client.force_login(user)
    resp = client.get(f"/ar/ledger/{ledger_customer.pk}/export/?format={fmt}")
    assert resp.status_code == 200
    ctype, magic = FORMATS[fmt]
    assert resp["Content-Type"].startswith(ctype)
    if magic:
        assert resp.content.startswith(magic)


@pytest.mark.django_db
def test_ar_customer_ledger_export_preserves_date_filter(client, user, ledger_customer):
    client.force_login(user)
    resp = client.get(
        f"/ar/ledger/{ledger_customer.pk}/export/?format=csv&start=2026-01-01&end=2026-01-31"
    )
    assert resp.status_code == 200
    text = resp.content.decode("utf-8", "replace")
    assert "Date" in text
    assert "SI-L-2026-0001" in text
    assert "AR-L-2026-00001" in text


@pytest.mark.django_db
def test_ar_customer_ledger_print(client, user, ledger_customer):
    client.force_login(user)
    resp = client.get(f"/ar/ledger/{ledger_customer.pk}/print/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Ledger Test Trading" in body
    assert "stmiet-trans-logo.png" in body
    assert "{{ customer.name }}" not in body
    assert "{{ supplier.code }}" not in body


@pytest.mark.django_db
def test_ar_ledger_summary_export(client, user, ledger_customer):
    client.force_login(user)
    resp = client.get("/ar/ledger/export/?format=csv")
    assert resp.status_code == 200
    text = resp.content.decode("utf-8", "replace")
    assert "Code" in text
    assert "Customer Name" in text
    assert "Ledger Test Trading" in text


@pytest.mark.django_db
def test_ar_ledger_flow_audit(client, company, segment, accounts, user):
    """Flow audit: invoice -> posted collection -> ledger doc + summary agree,
    and a draft (unapproved) collection is invisible to the ledger."""
    from apps.ar.models import AcknowledgmentReceipt
    from apps.ar.services import CollectionService as CS
    from apps.ui.services import ar_customer_ledger, ar_customer_summary

    customer = Customer.objects.create(code="LC-A1", name="Audit Trading")
    inv = ARInvoice.objects.create(
        invoice_no="SI-L-A-1", customer=customer,
        transaction_date=date(2026, 1, 7), segment=segment, total=Decimal("5000.00"),
    )

    # Draft collection: created but NOT approved -> must not appear as paid.
    draft = CS.create_receipt(
        customer=customer,
        transaction_date=date(2026, 1, 12),
        receipt_no="AR-L-A-DRAFT",
        amount="1000.00",
        cash_account=accounts["10010"],
        segment=segment,
        created_by=user,
    )
    assert draft.status == "draft"
    assert draft.journal_entry_id is None

    pay = CS.record_collection(
        receipt_no="AR-L-A-1",
        customer=customer,
        transaction_date=date(2026, 1, 10),
        amount="2000.00",
        cash_account=accounts["10010"],
        segment=segment,
        applied_to=inv,
    )
    assert pay.journal_entry_id is not None
    assert pay.journal_entry.status == "posted"

    # Summary: billed 5000, paid 2000 (draft excluded), outstanding 3000.
    sum_ctx = ar_customer_summary()
    row = next(r for r in sum_ctx["rows"] if r["pk"] == customer.pk)
    assert row["billed"] == Decimal("5000.00")
    assert row["paid"] == Decimal("2000.00")
    assert row["outstanding"] == Decimal("3000.00")

    # SOA: two rows, invoice first then collection; running balance = 3000 Dr.
    ctx = ar_customer_ledger(customer=customer)
    assert len(ctx["rows"]) == 2
    assert ctx["rows"][0]["ref"] == "SI-L-A-1"
    assert ctx["rows"][0]["type"] == "Invoice"
    assert ctx["rows"][0]["debit"] == Decimal("5000.00")
    assert ctx["rows"][1]["ref"] == "AR-L-A-1"
    assert ctx["rows"][1]["type"] == "Receipt (Collection)"
    assert ctx["rows"][1]["credit"] == Decimal("2000.00")
    assert ctx["closing_dr"] == Decimal("3000.00")
    assert ctx["closing_cr"] is None
    # draft receipt number never surfaces in the ledger doc
    assert all("AR-L-A-DRAFT" not in r["ref"] for r in ctx["rows"])


@pytest.mark.django_db
def test_ar_ledger_reversed_collection_excluded(company, segment, accounts, user):
    """A collection whose JE was reversed is dropped from paid/ledger rows."""
    from apps.ui.services import ar_customer_ledger, ar_customer_summary

    customer = Customer.objects.create(code="LC-A2", name="Reversal Audit")
    rec = CollectionService.record_collection(
        receipt_no="AR-L-A-2", customer=customer,
        transaction_date=date(2026, 1, 10), amount="1500.00",
        cash_account=accounts["10010"], segment=segment,
    )
    ctx = ar_customer_ledger(customer=customer)
    assert len(ctx["rows"]) == 1
    assert ctx["rows"][0]["credit"] == Decimal("1500.00")
    # flip the posted JE to reversed (ADR-004 reversal recompute)
    rec.journal_entry.status = "reversed"
    rec.journal_entry.save(update_fields=["status", "updated_at"])
    ctx2 = ar_customer_ledger(customer=customer)
    assert len(ctx2["rows"]) == 0
    sum_ctx = ar_customer_summary()
    row = next(r for r in sum_ctx["rows"] if r["pk"] == customer.pk)
    assert row["paid"] == Decimal("0.00")


@pytest.mark.django_db
def test_ar_ledger_advance_rendered(client, user, company, segment, accounts):
    """A customer with receipt-only collections (no invoice) shows a Credit
    Balance (Advance); the outstanding cell renders '—' and never a negative."""
    customer = Customer.objects.create(code="LC-ADV", name="Advance Test Trading")
    CollectionService.record_collection(
        receipt_no="AR-L-ADV-0001",
        customer=customer,
        transaction_date=date(2026, 1, 12),
        amount="2500.00",
        cash_account=accounts["10010"],
        segment=segment,
    )
    from apps.ui.services import ar_customer_summary

    ctx = ar_customer_summary()
    row = next(r for r in ctx["rows"] if r["pk"] == customer.pk)
    assert row["billed"] == Decimal("0.00")
    assert row["outstanding"] == Decimal("0.00")
    assert row["advance"] == Decimal("2500.00")
    assert ctx["total_advance"] == Decimal("2500.00")
    assert ctx["total_outstanding"] == Decimal("0.00")

    client.force_login(user)
    resp = client.get("/ar/ledger/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Credit Balance (Advance)" in body
    assert "Advance Test Trading" in body
    assert "2,500.00" in body
    assert "-2,500.00" not in body


@pytest.mark.django_db
def test_ar_ledger_summary_export_advance(client, user, company, segment, accounts):
    """CSV export surfaces the Credit Balance (Advance) header and the positive
    advance magnitude, never a negative outstanding."""
    customer = Customer.objects.create(code="LC-ADVX", name="Advance Export Trading")
    CollectionService.record_collection(
        receipt_no="AR-L-ADVX-0001",
        customer=customer,
        transaction_date=date(2026, 1, 12),
        amount="975.50",
        cash_account=accounts["10010"],
        segment=segment,
    )
    client.force_login(user)
    resp = client.get("/ar/ledger/export/?format=csv")
    assert resp.status_code == 200
    text = resp.content.decode("utf-8", "replace")
    assert "Credit Balance (Advance)" in text
    assert "Advance Export Trading" in text
    assert "975.50" in text
    assert "-975.50" not in text