"""Rejected documents stay trackable + revisable in their own module.

Verifies the reject->revise return path for RFP (and the JE-module guard that
keeps source-document entries out of the generic JE editor).
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.ap.models import RFPDocument, Supplier
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def supplier(segment):
    return Supplier.objects.create(
        code="SUP-RJ", name="Reject Vendor", default_segment=segment
    )


def test_rejected_rfp_is_tracked_in_rfp_list_and_detail(client, segment, supplier, role_users):
    rfp = RFPDocument.objects.create(
        ap_number="A-REJ-1", rfp_date=date(2026, 9, 10), payee=supplier,
        segment=segment, amount=Decimal("2000.00"), particulars="Rejected test",
        status="rejected", created_by=role_users["staff"],
        rejected_by=role_users["head"], rejection_note="wrong vendor",
    )
    client.force_login(role_users["staff"])

    # Visible in the RFP register...
    body = client.get("/ap/rfps/").content.decode()
    assert "A-REJ-1" in body
    assert f"/ap/rfps/{rfp.id}/revise/" in body

    # ...and on its detail page with the note + revise action.
    body = client.get(f"/ap/rfps/{rfp.id}/").content.decode()
    assert "wrong vendor" in body
    assert f"/ap/rfps/{rfp.id}/revise/" in body
    assert client.get(f"/ap/rfps/{rfp.id}/revise/").status_code == 200


def test_rfp_linked_je_is_not_editable_from_the_je_module(
    client, company, segment, accounts, supplier, role_users
):
    je = JournalEntry.objects.create(
        entry_no="RFP-A-REJ-1", company=company, segment=segment,
        transaction_date=date(2026, 9, 10), status=PostingStatus.DRAFT,
        description="RFP posting", source_doc_type="RFP", source_doc_no="A-REJ-1",
    )
    JournalEntryLine.objects.create(
        entry=je, line_no=1, account=accounts["10010"], debit=Decimal("100.00")
    )
    JournalEntryLine.objects.create(
        entry=je, line_no=2, account=accounts["41010"], credit=Decimal("100.00")
    )
    je.recalc_totals()
    rfp = RFPDocument.objects.create(
        ap_number="A-REJ-1", rfp_date=date(2026, 9, 10), payee=supplier,
        segment=segment, amount=Decimal("100.00"), status="posted",
        created_by=role_users["staff"], journal_entry=je,
    )

    client.force_login(role_users["staff"])
    resp = client.get(f"/journal/{je.id}/edit/")
    assert resp.status_code == 302
    assert resp["Location"] == f"/ap/rfps/{rfp.id}/"

    body = client.get(f"/journal/{je.id}/").content.decode()
    assert "Generated from RFP" in body