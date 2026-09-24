"""My Approvals inbox actions (ADR-047 phase 4).

Approvers can sign straight from the queue: every row carries its action
endpoint plus `next=/approvals/`, so an approver whose screen set is
dashboard+inbox (the COO default) can approve *without* being able to open
the register. Wrong-role attempts still bounce off the service guards.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.foundation.models import UserProfile

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def role_users(db):
    out = {}
    for username in ("staff", "head", "coo"):
        u = User.objects.create_user(username=username, password="x")
        UserProfile.objects.create(user=u, approval_role=username)
        out[username] = u
    return out


@pytest.fixture
def supplier(db, segment):
    from apps.ap.models import Supplier

    return Supplier.objects.create(
        code="S900", name="Inbox Fuel Depot", supplier_type="depot",
        default_segment=segment,
    )


@pytest.fixture
def checked_rfp(db, segment, supplier):
    from apps.ap.models import RFPDocument

    return RFPDocument.objects.create(
        ap_number="A9001", rfp_date=date(2026, 1, 5), payee=supplier,
        segment=segment, amount=Decimal("50000.00"),
        particulars="inbox smoke", status="checked",
    )


def _approve(client, user, url):
    client.force_login(user)
    return client.post(url, {"next": "/approvals/"})


def test_inbox_shows_action_buttons(client, role_users, segment, supplier, checked_rfp):
    client.force_login(role_users["head"])
    body = client.get("/approvals/").content.decode()
    assert f'/ap/rfps/{checked_rfp.id}/approve/' in body
    assert "data-inbox-reject" in body  # reject is available from the queue too


def test_head_approves_from_inbox_redirects_back(client, role_users, checked_rfp):
    resp = _approve(client, role_users["head"], f"/ap/rfps/{checked_rfp.id}/approve/")
    assert resp.status_code == 302
    assert resp.url == "/approvals/"
    checked_rfp.refresh_from_db()
    assert checked_rfp.status != "checked"  # it moved


def test_wrong_role_still_refused_from_inbox(client, role_users, checked_rfp):
    resp = _approve(client, role_users["coo"], f"/ap/rfps/{checked_rfp.id}/approve/")
    assert resp.status_code == 302
    assert resp.url == "/approvals/"  # bounced, not 403: action bucket allows it
    checked_rfp.refresh_from_db()
    assert checked_rfp.status == "checked"  # nothing moved (service guard)


def test_coo_signs_cnr_step_from_inbox_alone(client, role_users, segment, supplier):
    """The COO default screen set is dashboard+inbox; he can still clear CNR."""
    from django.conf import settings
    from django.test import override_settings

    from apps.ap.models import RFPDocument

    rfp = RFPDocument.objects.create(
        ap_number="A9002", rfp_date=date(2026, 1, 6), payee=supplier,
        segment=segment, amount=Decimal("150000.00"),  # above the CNR gate
        particulars="cnr from inbox", status="fin_approved",
    )
    domain = dict(settings.DOMAIN, COO_REVIEW_ENABLED=True)
    with override_settings(DOMAIN=domain):
        client.force_login(role_users["coo"])
        # no register access
        assert client.get("/ap/rfps/").status_code == 403
        resp = client.post(f"/ap/rfps/{rfp.id}/approve-cnr/", {"next": "/approvals/"})
        assert resp.status_code == 302 and resp.url == "/approvals/"
    rfp.refresh_from_db()
    assert rfp.status == "cnr_approved"


def test_je_reject_with_note_from_inbox(client, role_users, company, segment, accounts):
    from apps.posting.models import JournalEntry, PostingStatus

    je = JournalEntry.objects.create(
        entry_no="JE-REJ-1", company=company, segment=segment,
        transaction_date=date(2026, 1, 7), status=PostingStatus.SUBMITTED,
        description="awaiting rejection", created_by=role_users["staff"],
    )
    client.force_login(role_users["head"])
    resp = client.post(
        f"/journal/{je.id}/reject/",
        {"note": "missing OR", "next": "/approvals/"},
        follow=False,
    )
    assert resp.status_code == 302
    assert resp.url == "/approvals/"
    je.refresh_from_db()
    assert je.status == PostingStatus.DRAFT
    assert je.rejection_note == "missing OR"


def test_missing_next_falls_back_to_detail(client, role_users, checked_rfp):
    """Without the inbox `next`, the old redirect target is preserved."""
    client.force_login(role_users["head"])
    resp = client.post(f"/ap/rfps/{checked_rfp.id}/approve/", {})
    assert resp.status_code == 302
    assert resp.url == f"/ap/rfps/{checked_rfp.id}/"
