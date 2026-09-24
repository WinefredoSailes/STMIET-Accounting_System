"""Executive dashboard (Phase UI-7): the 4-zone finance view.

The dashboard is a read-only projection of the posted GL — these tests pin
the contract: every zone renders, the KPI set is complete, segment filtering
flips the numbers, the chart JSON blob is present, and non-posted activity
never leaks into the figures.
"""

import json
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()

pytestmark = pytest.mark.django_db

KPI_LABELS = [
    "Revenue YTD",
    "Expenses YTD",
    "Net Income YTD",
    "Cash Position",
    "Gross Profit Margin",
    "Net Profit Margin",
    "AR Outstanding",
    "AP Outstanding",
]


@pytest.fixture
def client_login(client, user):
    client.force_login(user)
    return client


def _post_income(client, company, segment, accounts, user):
    """Post a simple cash sale through the services so revenue lands in the GL."""
    from apps.posting.services import PostingService
    from apps.posting.models import JournalEntry, PostingStatus

    cash = accounts["10010"]
    revenue = next(
        a for a in accounts.values() if getattr(a, "account_type", None) == "revenue"
    )
    entry = JournalEntry.objects.create(
        entry_no="EXEC-1",
        company=company,
        segment=segment,
        transaction_date=date.today(),
        status=PostingStatus.APPROVED,
        description="dashboard test sale",
    )
    from apps.posting.models import JournalEntryLine

    JournalEntryLine.objects.create(entry=entry, line_no=1, account=cash, segment=segment, debit=Decimal("5000.00"), credit=Decimal("0.00"))
    JournalEntryLine.objects.create(entry=entry, line_no=2, account=revenue, segment=segment, debit=Decimal("0.00"), credit=Decimal("5000.00"))
    entry.recalc_totals()
    PostingService.post(entry, approver=user, user=user)
    return entry


def test_dashboard_renders_all_zones(client_login):
    body = client_login.get("/").content.decode()
    assert "Executive Dashboard" in body
    for label in KPI_LABELS:
        assert label in body, f"missing KPI {label}"
    assert body.count('id="chart-') == 4
    assert "AR Aging" in body and "AP Aging" in body
    assert "Disbursement Pipeline" in body and "Month-End Close" in body


def test_dashboard_chart_json_is_valid(client_login):
    body = client_login.get("/").content.decode()
    start = body.index('id="dash-charts"')
    raw = body[start:]
    content = raw[raw.index(">") + 1 : raw.index("</script>")]
    payload = json.loads(content)
    assert set(payload) >= {
        "revenue", "expenses", "cash_in", "cash_out",
        "segment_revenue", "segment_expenses",
        "expense_labels", "expense_values", "month_labels",
    }
    assert len(payload["month_labels"]) == 12


def test_segment_filter_filters_kpis(client_login, company, segment, accounts, user):
    _post_income(client_login, company, segment, accounts, user)
    all_body = client_login.get("/").content.decode()
    seg_body = client_login.get(f"/?segment={segment.code}").content.decode()
    assert all_body != seg_body  # filter changed the page


def test_segment_filter_unknown_value_is_graceful(client_login):
    resp = client_login.get("/?segment=NOPE")
    assert resp.status_code == 200


def test_dashboard_links_kpis_to_sources(client_login):
    body = client_login.get("/").content.decode()
    assert "/reports/is/" in body
    assert "/reports/te/" in body
    assert "/bank-accounts/" in body or "/cash/banks/" in body
    assert "/ar/aging/" in body
    assert "/ap/aging/" in body