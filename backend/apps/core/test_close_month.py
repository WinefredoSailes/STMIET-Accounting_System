"""close_month management command: posts the §13 closing JEs via the operator CLI.

Proves the command (a) posts §13.1/13.2, (b) respects the 4-step gate so it
never locks with accruals/recon outstanding, and (c) is idempotent on re-run.
"""

import io
from datetime import date
from decimal import Decimal

import pytest

from apps.foundation.models import Account, Company, FiscalPeriod, FiscalYear, Segment
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService
from apps.reporting.models import MonthEndClose

pytestmark = pytest.mark.django_db


@pytest.fixture
def jan_company():
    company = Company.objects.create(code="STMIET", name="Seven-Trent Test")
    seg = Segment.objects.create(code="DHPP", name="DHPP", company=company)
    fy = FiscalYear.objects.create(
        company=company, code="2026", start_date="2026-01-01", end_date="2026-12-31"
    )
    jan = FiscalPeriod.objects.create(
        fiscal_year=fy, period_no=1, start_date="2026-01-01", end_date="2026-01-31"
    )
    for code, name, atype in (
        ("10010", "Cash on Hand", "asset"),
        ("20000", "A/Payables - Current", "liability"),
        ("61100", "Cost of Sales", "expense"),
        ("30000", "E.Bagatua Capital", "equity"),
    ):
        Account.objects.create(code=code, name=name, account_type=atype, segment="DHPP")
    return company, seg, jan


def _post_expense(company, seg, jan):
    je = JournalEntry.objects.create(
        company=company, segment=seg, transaction_date=jan.start_date,
        status=PostingStatus.DRAFT, entry_no="JE-CMD-TEST", description="expense",
    )
    JournalEntryLine.objects.create(entry=je, line_no=1, account=Account.objects.get(code="61100"), debit="9000.00")
    JournalEntryLine.objects.create(entry=je, line_no=2, account=Account.objects.get(code="20000"), credit="9000.00")
    je.recalc_totals()
    PostingService.post(je)


def test_close_month_posts_but_respects_step_gate(jan_company):
    company, seg, jan = jan_company
    _post_expense(company, seg, jan)

    out = io.StringIO()
    from django.core.management import call_command

    call_command("close_month", "--company", "STMIET", "--period", "2026-01", stdout=out)

    mec = MonthEndClose.objects.get(fiscal_period=jan)
    assert mec.expense_close_entry is not None and mec.expense_close_entry.is_posted
    assert mec.revenue_close_entry is None  # no revenue posted in the period
    assert mec.step_status("close") == "done"
    assert mec.step_status("appropriations") == "done"
    jan.refresh_from_db()
    assert jan.is_closed is False  # accruals/recon outstanding -> not locked
    text = out.getvalue()
    assert "accruals, recon" in text


def test_close_month_is_idempotent(jan_company):
    company, seg, jan = jan_company
    _post_expense(company, seg, jan)

    from django.core.management import call_command

    call_command("close_month", "--company", "STMIET", "--period", "2026-01", stdout=io.StringIO())
    call_command("close_month", "--company", "STMIET", "--period", "2026-01", stdout=io.StringIO())

    cle = JournalEntry.objects.filter(source_doc_type="CLOSE", entry_no__startswith="CLE-")
    assert cle.count() == 1  # a re-run must never double-post the close
    assert cle.first().total_debit == Decimal("9000.00")