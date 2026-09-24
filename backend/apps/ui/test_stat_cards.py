"""Stat-card coverage guards (Phase UI-8b).

Every workflow-driven list screen must show summary stat cards so future role
holders (AR person, AP person, CV person, treasury, etc.) can track their
queue at a glance. The cards render through one shared partial —
``ui/partials/stat_card.html`` — fed by a per-screen ``*_summary()`` service.
"""

import pytest

pytestmark = pytest.mark.django_db

# path -> required card labels (assert at least these exist on the page)
SCREENS = {
    "/ap/rfps/": ["Total RFPs", "Pending approval", "Posted (CONSO'd)"],
    "/ap/pos/": ["Total POs", "Pending approval", "Billed via posted RFPs"],
    "/ap/cv/": ["Total CVs", "For head signature", "Cleared (in GL)"],
    "/ap/conso/": ["Total batches", "Reviewed", "Posted"],
    "/ar/receipts/": ["Total receipts", "For head approval", "Posted (collected)"],
    "/ar/invoices/": ["Total invoices", "Open / partial", "Overdue (60+ days)"],
    "/billing/": ["Total billings", "For head approval", "Posted to GL"],
    "/cash/transfers/": ["Total transfers", "For head approval", "Approved (posted)"],
    "/cash/cycles/": ["Total cycles", "Reconciled", "Locked"],
    "/cash/pcf/replenishments/": ["Total vouchers", "Requested", "Posted"],
    "/cash/recon/": ["Total recons", "Resolved", "Escalated"],
    "/cash/short/": ["Total worksheets", "Open variances", "Adjusted"],
    "/ap/advances/": ["Total advances", "Active (unsettled)", "Liquidated / closed"],
    "/assets/": ["Total assets", "Active", "Disposed"],
}


@pytest.mark.parametrize("path,labels", sorted(SCREENS.items()))
def test_list_screens_show_stat_cards(client, user, path, labels):
    client.force_login(user)
    resp = client.get(path)
    assert resp.status_code == 200
    body = resp.content.decode()
    for label in labels:
        assert label in body, f"{path} missing stat card: {label!r}"
    assert "partials/stat_card.html" not in body  # rendered, not raw


def test_shared_stat_card_partial_exists():
    from pathlib import Path

    partial = (
        Path(__file__).resolve().parent
        / "templates" / "ui" / "partials" / "stat_card.html"
    )
    assert partial.exists()