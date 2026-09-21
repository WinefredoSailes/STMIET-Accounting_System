"""Pending / Unposted visibility on the Journal Entries screen (ADR-043).

Approved RFP / CONSO / PCF documents have no JournalEntry until they post, so
they are surfaced on the Journal Entries "Pending / Unposted" tab instead of
silently disappearing. These documents are NOT journal entries yet.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.ap.models import CONSOBatch, RFPDocument, Supplier
from apps.cash.models import PCFReplenishment, PettyCashFund
from apps.ui.services import pending_count, pending_documents

pytestmark = pytest.mark.django_db


@pytest.fixture
def supplier(segment):
    return Supplier.objects.create(
        code="SUP-P1", name="Pending Vendor", default_segment=segment
    )


def _rfp(segment, supplier, *, ap_number, status, conso=None):
    return RFPDocument.objects.create(
        ap_number=ap_number,
        rfp_date=date(2026, 9, 1),
        payee=supplier,
        segment=segment,
        amount=Decimal("1000.00"),
        particulars="Pending test",
        status=status,
        conso=conso,
    )


def _pcf(company, segment, accounts, user, *, status="approved", voucher="PCV-2026-0001"):
    fund = PettyCashFund.objects.create(
        fund_code="PCF-P1", name="Pending Fund", custodian_name="Custodian",
        imprest_amount=Decimal("20000.00"), gl_account=accounts["10010"],
        company=company, is_active=True,
    )
    return PCFReplenishment.objects.create(
        fund=fund, request_date=date(2026, 9, 2), amount=Decimal("500.00"),
        payee_name="PCF Clerk", reference="REF", voucher_no=voucher,
        requested_by=user, status=status,
    )


def test_rfp_pending_appears_then_drops_after_posted(segment, supplier):
    rfp = _rfp(segment, supplier, ap_number="A-P1", status="fin_approved")
    rows = pending_documents()
    assert any(r["kind"] == "RFP" and r["number"] == "A-P1" for r in rows)
    # Once posted, it is no longer pending.
    rfp.status = "posted"
    rfp.save(update_fields=["status", "updated_at"])
    assert all(r["number"] != "A-P1" for r in pending_documents())


def test_rfp_shows_in_conso_label(segment, supplier):
    batch = CONSOBatch.objects.create(
        batch_no="CONSO-2026-01", conso_date=date(2026, 9, 5), status="open",
        total_amount=Decimal("1000.00"),
    )
    _rfp(segment, supplier, ap_number="A-P2", status="fin_approved", conso=batch)
    row = next(r for r in pending_documents() if r["number"] == "A-P2")
    assert row["status_label"] == "In CONSO"
    assert row["conso"] == "CONSO-2026-01"


def test_open_conso_batch_is_pending(segment):
    batch = CONSOBatch.objects.create(
        batch_no="CONSO-2026-02", conso_date=date(2026, 9, 5), status="open",
        total_amount=Decimal("2500.00"),
    )
    assert any(r["kind"] == "CONSO" and r["number"] == "CONSO-2026-02" for r in pending_documents())
    batch.status = "posted"
    batch.save(update_fields=["status", "updated_at"])
    assert all(r["number"] != "CONSO-2026-02" for r in pending_documents())


def test_pcf_pending_appears_then_drops(company, segment, accounts, role_users):
    replen = _pcf(company, segment, accounts, role_users["staff"], status="approved")
    assert any(r["kind"] == "PCF" and r["number"] == "PCV-2026-0001" for r in pending_documents())
    replen.status = "posted"
    replen.save(update_fields=["status", "updated_at"])
    assert all(r["number"] != "PCV-2026-0001" for r in pending_documents())


def test_pending_count_matches(segment, supplier):
    _rfp(segment, supplier, ap_number="A-P3", status="cnr_approved")
    assert pending_count() == len(pending_documents())


def test_je_list_pending_tab_renders(client, segment, supplier, role_users):
    _rfp(segment, supplier, ap_number="A-P4", status="fin_approved")
    client.force_login(role_users["staff"])
    resp = client.get("/journal/?tab=pending")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Pending / Unposted" in body
    assert "A-P4" in body
    # The entries filter bar is not shown on the pending tab.
    assert 'name="q"' not in body


def test_je_list_entries_tab_default(client, role_users):
    client.force_login(role_users["staff"])
    resp = client.get("/journal/")
    assert resp.status_code == 200
    assert "Pending / Unposted" in resp.content.decode()


def test_dashboard_pending_count(client, segment, supplier, role_users):
    _rfp(segment, supplier, ap_number="A-P5", status="fin_approved")
    client.force_login(role_users["staff"])
    body = client.get("/").content.decode()
    assert "pending / not yet posted" in body