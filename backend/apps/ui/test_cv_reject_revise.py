"""CV reject -> revise cycle must stay on the CV screens (not the JE list).

Regression check requested by the user: after the head rejects a CV, the
issuer must be able to track and revise it from the CV list/detail.
"""

from datetime import date

import pytest

from apps.ap.models import Supplier
from apps.ap.services import CVPaymentService
from apps.posting.models import PostingStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def supplier(segment):
    return Supplier.objects.create(
        code="SUP-CVR", name="CV Vendor", default_segment=segment
    )


@pytest.fixture
def cv(supplier, accounts, segment_account_map, role_users):
    return CVPaymentService.create_cv(
        cv_number="CV-2026-9001", cv_date=date(2026, 9, 10), payee=supplier,
        bank_account=accounts["10110"], gross_amount="1000.00",
        withheld_tax="0.00", user=role_users["staff"],
    )


def test_cv_reject_then_revise_stays_on_cv_screens(client, cv, accounts, role_users):
    assert cv.status == "created"
    assert cv.journal_entry_id is not None

    # Head rejects with a note.
    client.force_login(role_users["head"])
    resp = client.post(f"/ap/cv/{cv.id}/reject/", {"note": "wrong check no"})
    assert resp.status_code == 302
    cv.refresh_from_db()
    assert cv.status == "rejected"
    assert cv.journal_entry_id is None
    assert cv.rejection_note == "wrong check no"

    # Issuer can still see and revise the CV from the CV list...
    client.force_login(role_users["staff"])
    list_body = client.get("/ap/cv/").content.decode()
    assert "CV-2026-9001" in list_body
    assert f"/ap/cv/{cv.id}/revise/" in list_body

    # ...and from the CV detail page.
    detail = client.get(f"/ap/cv/{cv.id}/").content.decode()
    assert "wrong check no" in detail
    assert f"/ap/cv/{cv.id}/revise/" in detail

    # The revise form renders, and resubmitting rebuilds the DRAFT JE.
    assert client.get(f"/ap/cv/{cv.id}/revise/").status_code == 200
    resp = client.post(
        f"/ap/cv/{cv.id}/revise/",
        {
            "bank_account": accounts["10110"].id,
            "gross_amount": "1000.00",
            "withheld_tax": "0.00",
            "cv_date": "2026-09-10",
            "check_no": "999",
        },
    )
    assert resp.status_code == 302
    cv.refresh_from_db()
    assert cv.status == "created"
    assert cv.journal_entry_id is not None
    assert cv.check_no == "999"


def test_cv_je_is_not_editable_from_the_je_module(client, cv, role_users):
    """A CV's JE is corrected on the CV screen — never via the JE module."""
    entry_id = cv.journal_entry_id
    client.force_login(role_users["staff"])

    # The JE detail points back to the CV and offers no manual lifecycle action.
    body = client.get(f"/journal/{entry_id}/").content.decode()
    assert "Generated from Check Voucher" in body
    assert f"/ap/cv/{cv.id}/" in body
    assert "/journal/" + str(entry_id) + "/submit/" not in body
    assert "/journal/" + str(entry_id) + "/edit/" not in body

    # Editing/submitting through the JE module is refused and rerouted.
    resp = client.get(f"/journal/{entry_id}/edit/")
    assert resp.status_code == 302
    assert resp["Location"] == f"/ap/cv/{cv.id}/"

    resp = client.post(f"/journal/{entry_id}/submit/")
    assert resp.status_code == 302
    assert resp["Location"] == f"/ap/cv/{cv.id}/"
    cv.refresh_from_db()
    assert cv.journal_entry_id == entry_id
    assert cv.journal_entry.status == PostingStatus.DRAFT