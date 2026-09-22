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


@pytest.mark.django_db
def test_supplier_ledger_advance_rendered(client, user, company, segment, accounts):
    """A supplier with a posted CV but no posted RFP shows an advance; the
    outstanding cell renders '—' and never a negative."""
    from apps.ap.models import CheckVoucher
    from apps.posting.models import JournalEntry, PostingStatus
    from apps.ui.services import ap_supplier_summary

    supplier = Supplier.objects.create(code="SL-ADV", name="Advance Test Supply", default_segment=segment)
    je = JournalEntry.objects.create(
        entry_no="JE-SL-ADV",
        company=company,
        segment=segment,
        transaction_date=date(2026, 1, 9),
        status=PostingStatus.POSTED,
        description="Advance CV posting",
    )
    CheckVoucher.objects.create(
        cv_number="CV-SL-ADV-0001",
        cv_date=date(2026, 1, 10),
        payee=supplier,
        bank_account=accounts["10110"],
        gross_amount=Decimal("1200.00"),
        withheld_tax=Decimal("0.00"),
        net_amount=Decimal("1200.00"),
        check_no="CHK-ADV",
        status="cleared",
        journal_entry=je,
    )

    ctx = ap_supplier_summary()
    row = next(r for r in ctx["rows"] if r["pk"] == supplier.pk)
    assert row["billed"] == Decimal("0.00")
    assert row["outstanding"] == Decimal("0.00")
    assert row["advance"] == Decimal("1200.00")
    assert ctx["total_advance"] == Decimal("1200.00")
    assert ctx["total_outstanding"] == Decimal("0.00")

    client.force_login(user)
    resp = client.get("/ap/ledger/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Credit Balance (Advance)" in body
    assert "Advance Test Supply" in body
    assert "1,200.00" in body
    assert "-1,200.00" not in body


@pytest.mark.django_db
def test_supplier_ledger_summary_export_advance(client, user, company, segment, accounts):
    """CSV export surfaces the Credit Balance (Advance) header and the positive
    advance magnitude, never a negative outstanding."""
    from apps.ap.models import CheckVoucher
    from apps.posting.models import JournalEntry, PostingStatus

    supplier = Supplier.objects.create(code="SL-ADVX", name="Advance Export Supply", default_segment=segment)
    je = JournalEntry.objects.create(
        entry_no="JE-SL-ADVX",
        company=company,
        segment=segment,
        transaction_date=date(2026, 1, 9),
        status=PostingStatus.POSTED,
        description="Advance CV posting",
    )
    CheckVoucher.objects.create(
        cv_number="CV-SL-ADVX-0001",
        cv_date=date(2026, 1, 10),
        payee=supplier,
        bank_account=accounts["10110"],
        gross_amount=Decimal("640.25"),
        withheld_tax=Decimal("0.00"),
        net_amount=Decimal("640.25"),
        check_no="CHK-ADVX",
        status="cleared",
        journal_entry=je,
    )
    client.force_login(user)
    resp = client.get("/ap/ledger/export/?format=csv")
    assert resp.status_code == 200
    text = resp.content.decode("utf-8", "replace")
    assert "Credit Balance (Advance)" in text
    assert "Advance Export Supply" in text
    assert "640.25" in text
    assert "-640.25" not in text