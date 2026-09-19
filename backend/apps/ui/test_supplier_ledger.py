"""End-to-end coverage for the supplier subsidiary ledger page, its per-supplier
export (xlsx / csv / pdf), and the print view (ADR-005 AP subsidiary ledger)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.ap.models import RFPDocument, RFPLine, Supplier

FORMATS = {
    "pdf": ("application/pdf", b"%PDF-"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"PK\x03\x04"),
    "csv": ("text/csv", None),
}


@pytest.fixture
def ledger_supplier(db, segment, accounts):
    """A supplier with one posted RFP (credit/payable row in the ledger)."""
    supplier = Supplier.objects.create(
        code="SL-01", name="Ledger Test Supply Corp", default_segment=segment
    )
    rfp = RFPDocument.objects.create(
        ap_number="A9501",
        rfp_date=date(2026, 1, 7),
        payee=supplier,
        segment=segment,
        particulars="Ledger test fuel",
        purpose="purchase",
        amount=Decimal("50000.00"),
        status="posted",
    )
    RFPLine.objects.create(
        rfp=rfp, line_no=1, side="dr", segment=segment,
        account=accounts["61100"], amount=Decimal("50000.00"),
        description="Ledger test fuel", cost_center="OS",
    )
    RFPLine.objects.create(
        rfp=rfp, line_no=2, side="cr", segment=segment,
        account=accounts["20000"], amount=Decimal("50000.00"),
        description="AP - Ledger Test Supply Corp", cost_center="",
    )
    return supplier


@pytest.mark.django_db
def test_supplier_ledger_page_renders(client, user, ledger_supplier):
    client.force_login(user)
    resp = client.get(f"/ap/ledger/{ledger_supplier.pk}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    # supplier name must be resolved, never a literal template variable
    assert "Ledger Test Supply Corp" in body
    assert "{{ supplier.name }}" not in body
    assert "{{ supplier.code }}" not in body
    # export + print actions must be present
    for label in ("Excel", "PDF", "CSV"):
        assert f">{label}<" in body
    assert ">Print<" in body
    assert f"format=xlsx" in body


@pytest.mark.django_db
@pytest.mark.parametrize("fmt", ["xlsx", "csv", "pdf"])
def test_supplier_ledger_export_formats(client, user, ledger_supplier, fmt):
    client.force_login(user)
    resp = client.get(f"/ap/ledger/{ledger_supplier.pk}/export/?format={fmt}")
    assert resp.status_code == 200
    ctype, magic = FORMATS[fmt]
    assert resp["Content-Type"].startswith(ctype)
    if magic:
        assert resp.content.startswith(magic)


@pytest.mark.django_db
def test_supplier_ledger_export_preserves_date_filter(client, user, ledger_supplier):
    client.force_login(user)
    resp = client.get(
        f"/ap/ledger/{ledger_supplier.pk}/export/?format=csv&start=2026-01-01&end=2026-01-31"
    )
    assert resp.status_code == 200
    text = resp.content.decode("utf-8", "replace")
    assert "Date" in text
    assert "A9501" in text


@pytest.mark.django_db
def test_supplier_ledger_print(client, user, ledger_supplier):
    client.force_login(user)
    resp = client.get(f"/ap/ledger/{ledger_supplier.pk}/print/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Ledger Test Supply Corp" in body
    assert "stmiet-trans-logo.png" in body
    assert "{{ supplier.name }}" not in body
    assert "{{ supplier.code }}" not in body