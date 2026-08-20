"""Shared fixtures: minimal COA, company, segment, and a posting rule."""

import pytest
from django.contrib.auth import get_user_model

from apps.foundation.models import Account, Company, FiscalPeriod, FiscalYear, Segment
from apps.posting.models import PostingRule, PostingRuleLine


@pytest.fixture
def company(db):
    return Company.objects.create(
        code="STMIET",
        name="Seven-Trent Machineries Industrial Equipment Trading",
    )


@pytest.fixture
def segment(db, company):
    return Segment.objects.create(code="DHPP", name="Diesel & Heavy Parts Procurement", company=company)


@pytest.fixture
def fiscal_year(db, company):
    return FiscalYear.objects.create(
        company=company, code="2026", start_date="2026-01-01", end_date="2026-12-31"
    )


@pytest.fixture
def fiscal_period(db, fiscal_year):
    return FiscalPeriod.objects.create(
        fiscal_year=fiscal_year, period_no=1, start_date="2026-01-01", end_date="2026-01-31"
    )


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="x")


@pytest.fixture
def role_users(db):
    """One user per approval position with a UserProfile (ADR-036 map):
    staff prepares, head (Alywin) checks + approves acctg/fin, coo signs CNR."""
    from apps.foundation.models import UserProfile

    U = get_user_model()
    out = {}
    for role in ("staff", "head", "coo"):
        u = U.objects.create_user(username=role, password="x")
        UserProfile.objects.create(user=u, approval_role=role)
        out[role] = u
    return out


@pytest.fixture
def accounts(db):
    """Canonical 5-digit COA slice needed by posting tests (ADR-003)."""
    rows = [
        ("10010", "Cash on Hand", "asset"),
        ("10110", "BDO Checking", "asset"),
        ("12020", "A/Receivables - Other Current-DHPP", "asset"),
        ("12030", "A/Receivables - Fuel Clients", "asset"),
        ("12070", "Advances to Employees", "asset"),
        ("20000", "A/Payables - Current - DHPP", "liability"),
        ("21000", "Unearned Revenue - DHPP", "liability"),
        ("21010", "Accounts Payable-Trade", "liability"),
        ("41010", "Sales-Retail", "revenue"),
        ("61100", "Cost of Sales", "expense"),
        ("64110", "Withholding Tax-Expanded_DHPP", "liability"),
    ]
    out = {}
    for code, name, atype in rows:
        out[code] = Account.objects.create(
            code=code,
            name=name,
            account_type=atype,
            segment=Account.segment_for_code(code),
        )
    return out


@pytest.fixture
def rfp_rule(db, accounts):
    """ADR-018 canonical rule: Dr TOTAL | Cr advances 20k | Cr AP balance."""
    rule = PostingRule.objects.create(
        code="RFP_DISBURSEMENT",
        name="RFP disbursement",
        event="ap.disbursement.rfp",
    )
    PostingRuleLine.objects.create(
        rule=rule, line_no=1, side="debit", account_code="61100", share="1.0000",
        description="Expense total",
    )
    PostingRuleLine.objects.create(
        rule=rule, line_no=2, side="credit", account_code="12070", fixed_amount="20000.00",
        description="Employee advances portion",
    )
    PostingRuleLine.objects.create(
        rule=rule, line_no=3, side="credit", account_code="21010", use_balance=True,
        description="AP balance",
    )
    return rule