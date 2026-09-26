"""Universal action confirmation (base.js/confirm-core.js) + link hygiene.

The decision rules themselves are node-tested (frontend/tests/confirm-core
.test.mjs). These tests pin the template/DOM contract the JS relies on:
script order, the data-confirm attributes on shared buttons, the stale
single-approver banner being gone, the Head being able to approve their own
reversal end-to-end, and dashboard/inbox links never advertising a 403.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings

from apps.posting.models import ReversalRequest

from .test_reversal_ui import _posted

pytestmark = pytest.mark.django_db

TPL = Path(__file__).parent / "templates"


@pytest.fixture
def supplier(db, segment):
    from apps.ap.models import Supplier

    return Supplier.objects.create(
        code="S910", name="Confirm Depot", supplier_type="depot",
        default_segment=segment,
    )


@pytest.fixture
def checked_rfp(db, segment, supplier):
    from apps.ap.models import RFPDocument

    return RFPDocument.objects.create(
        ap_number="A9101", rfp_date=date(2026, 1, 5), payee=supplier,
        segment=segment, amount=Decimal("50000.00"),
        particulars="confirm smoke", status="checked",
    )


@pytest.fixture
def cnr_rfp(db, segment, supplier):
    """fin_approved + above the CNR gate: the queue item the COO signs."""
    from apps.ap.models import RFPDocument

    return RFPDocument.objects.create(
        ap_number="A9102", rfp_date=date(2026, 1, 6), payee=supplier,
        segment=segment, amount=Decimal("150000.00"),
        particulars="cnr review", status="fin_approved",
    )


# ---------------------------------------------------------------------------
# script contract
# ---------------------------------------------------------------------------

def test_confirm_core_loads_before_base_js():
    src = (TPL / "ui" / "base.html").read_text(encoding="utf-8")
    assert "confirm-core.js" in src
    assert src.index("confirm-core.js") < src.index("js/base.js")


# ---------------------------------------------------------------------------
# data-confirm attributes on the shared action buttons
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "relpath",
    [
        "ui/partials/workflow/rfp_actions.html",
        "ui/partials/workflow/po_actions.html",
        "ui/partials/workflow/cv_actions.html",
        "ui/partials/workflow/transfer_actions.html",
        "ui/partials/reversal_ui.html",
        "ui/posting/je_detail.html",
        "ui/ar/receipt_detail.html",
        "ui/home/approvals.html",
        "ui/ap/rfp_form.html",
        "ui/ap/po_form.html",
        "ui/ap/cv_revise_form.html",
        "ui/ap/_rfp_row.html",
        "ui/ap/_po_row.html",
        "ui/ap/_cv_row.html",
        "ui/cash/_cash_short_row.html",
    ],
)
def test_action_templates_wire_data_confirm(relpath):
    assert "data-confirm=" in (TPL / relpath).read_text(encoding="utf-8"), relpath


def test_stale_single_approver_banner_is_gone():
    for f in TPL.rglob("*.html"):
        assert "different approver" not in f.read_text(encoding="utf-8"), f


# ---------------------------------------------------------------------------
# the Head's own reversal request is approvable by the Head (UI round trip)
# ---------------------------------------------------------------------------

def test_head_approves_own_reversal_from_ui(client, company, segment, accounts, role_users):
    head = role_users["head"]
    je = _posted(company, segment, accounts, ref="JE-SELF-APPR")

    client.force_login(head)
    resp = client.post(f"/journal/{je.id}/reverse/", {"reason": "my own fix"})
    assert resp.status_code == 302
    req = ReversalRequest.objects.get(entry=je)
    assert req.requested_by_id == head.id

    body = client.get(f"/journal/{je.id}/").content.decode()
    assert "Approve reversal" in body          # button visible, not a dead end
    assert "different approver" not in body

    resp = client.post(f"/journal/reversal/{req.id}/approve/")
    assert resp.status_code == 302
    req.refresh_from_db()
    je.refresh_from_db()
    assert req.status == ReversalRequest.Status.APPROVED
    assert je.status == "reversed"


# ---------------------------------------------------------------------------
# inbox: confirm-tagged actions + no links to registers off the viewer's desk
# ---------------------------------------------------------------------------

def test_inbox_approve_button_carries_confirm(client, role_users, checked_rfp):
    client.force_login(role_users["head"])
    body = client.get("/approvals/").content.decode()
    assert "data-confirm=\"Approve A9101" in body


def test_inbox_hides_register_links_the_viewer_cannot_open(client, role_users, cnr_rfp):
    domain = dict(settings.DOMAIN, COO_REVIEW_ENABLED=True)
    with override_settings(DOMAIN=domain):
        client.force_login(role_users["coo"])
        assert client.get("/ap/rfps/").status_code == 403   # no register access
        body = client.get("/approvals/").content.decode()
    assert "A9102" in body                                   # still listed...
    assert f"href=\"/ap/rfps/{cnr_rfp.id}/\"" not in body    # ...as plain text
    assert f'form method="post" action="/ap/rfps/{cnr_rfp.id}/approve-cnr/"' in body
    # ...and the row points at the CNR endpoint, not Head's
    assert "data-confirm=\"Approve A9102" in body            # ...and signable here


# ---------------------------------------------------------------------------
# dashboard: drill-downs only for granted screens
# ---------------------------------------------------------------------------

def test_dashboard_links_respect_screen_grants(client, company, segment, accounts, role_users):
    client.force_login(role_users["coo"])
    body = client.get("/").content.decode()
    assert "Revenue YTD" in body                  # cards remain readable
    assert "/reports/is/" not in body             # ...but no 403 traps
    assert "/ap/rfps/" not in body
    assert "/ar/aging/" not in body

    client.force_login(role_users["head"])
    body = client.get("/").content.decode()
    assert "/reports/is/" in body                 # head keeps the drill-downs
    assert "/ar/aging/" in body


def test_favicon_and_robots_are_answered(client):
    """Prod-log hygiene: /favicon.ico redirects to the app logo and robots.txt
    disallows crawlers - no more 404 noise from probes, and no anonymous
    auth-wall redirects."""
    assert client.get("/favicon.ico").status_code == 302
    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert b"Disallow: /" in robots.content
