"""The head's rejection note on a Journal Entry must reach the requester.

Regression: je_detail/je_form rendered no rejection note, so a returned entry
looked identical to a normal draft and the requester never saw why.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def entry(company, segment, accounts, role_users):
    je = JournalEntry.objects.create(
        entry_no="JE-REJ-1", company=company, segment=segment,
        transaction_date=date(2026, 9, 10), status=PostingStatus.SUBMITTED,
        description="Manual test entry", created_by=role_users["staff"],
    )
    JournalEntryLine.objects.create(
        entry=je, line_no=1, account=accounts["10010"], debit=Decimal("100.00")
    )
    JournalEntryLine.objects.create(
        entry=je, line_no=2, account=accounts["41010"], credit=Decimal("100.00")
    )
    je.recalc_totals()
    return je


def test_head_reject_note_visible_to_requester(client, entry, role_users):
    client.force_login(role_users["head"])
    resp = client.post(f"/journal/{entry.id}/reject/", {"note": "Wrong account used"})
    assert resp.status_code == 302
    entry.refresh_from_db()
    assert entry.status == PostingStatus.DRAFT
    assert entry.rejection_note == "Wrong account used"

    # The requester sees the note on the detail page...
    client.force_login(role_users["staff"])
    body = client.get(f"/journal/{entry.id}/").content.decode()
    assert "Wrong account used" in body
    assert "needs revision" in body

    # ...on the edit form...
    body = client.get(f"/journal/{entry.id}/edit/").content.decode()
    assert "Wrong account used" in body

    # ...and the register flags it as Returned.
    body = client.get("/journal/").content.decode()
    assert "Returned" in body


def test_rejection_note_clears_on_resubmit(client, entry, role_users):
    client.force_login(role_users["head"])
    client.post(f"/journal/{entry.id}/reject/", {"note": "Fix me"})
    entry.refresh_from_db()

    client.force_login(role_users["staff"])
    client.post(f"/journal/{entry.id}/submit/")
    entry.refresh_from_db()
    assert entry.status == PostingStatus.SUBMITTED
    assert entry.rejection_note == ""
    # The returned banner is gone; the note still lives in the audit trail.
    body = client.get(f"/journal/{entry.id}/").content.decode()
    assert "needs revision" not in body