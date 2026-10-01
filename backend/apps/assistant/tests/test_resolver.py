"""Entity/period resolution tests for computed-answer routing."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.ap.models import CheckVoucher, PurchaseOrder, RFPDocument, Supplier
from apps.assistant.answers.context import (
    _explicit_period,
    parse_as_of,
    resolve_entities,
)
from apps.assistant.parser.query_parser import QueryParser
from apps.foundation.models import UserProfile

User = get_user_model()
PARSER = QueryParser()


def _resolve(user, raw, companies):
    parsed = PARSER.parse(raw)
    return resolve_entities(user, parsed, raw, raw.lower(), companies)


@pytest.fixture
def staff(db):
    u = User.objects.create_user(username="resolver", password="x")
    UserProfile.objects.create(user=u, approval_role="staff")
    return u


class TestParseAsOf:
    def test_iso_and_spoken_dates(self):
        assert parse_as_of("balance as of 2026-05-31") == date(2026, 5, 31)
        assert parse_as_of("balance as of May 31, 2026") == date(2026, 5, 31)
        assert parse_as_of("balance as of May 2026") == date(2026, 5, 1)
        assert parse_as_of("balance as of January 1, 2026?") == date(2026, 1, 1)

    def test_no_as_of(self):
        assert parse_as_of("what is the balance") is None


class TestExplicitPeriod:
    def test_named_month(self):
        p = _explicit_period("what is our net income for january 2026")
        assert p is not None and not p.is_default
        assert (p.start, p.end) == (date(2026, 1, 1), date(2026, 1, 31))

    def test_this_and_last_month(self):
        this = _explicit_period("net income this month")
        assert this is not None and this.start.day == 1
        last = _explicit_period("compare with last month")
        assert last is not None and last.end < this.start

    def test_year_window(self):
        p = _explicit_period("totals this year")
        assert p is not None
        assert p.start == date(date.today().year, 1, 1)


class TestEntityResolution:
    def test_supplier_by_name_and_advance_by_name(self, staff, segment, db):
        s = Supplier.objects.create(code="S001", name="Limdon Sales Corp", default_segment=segment)
        e = _resolve(staff, "how much do we owe Limdon", [segment.company])
        assert e.supplier is not None and e.supplier.pk == s.pk

    def test_customer_code_and_docs(self, staff, segment, accounts, company, db):
        from apps.ar.models import Customer

        customer = Customer.objects.create(code="C009", name="Petron Depot", approval_status="approved")
        po = PurchaseOrder.objects.create(
            po_number="PO-2026-0007", po_date=date(2026, 9, 1), supplier=Supplier.objects.create(code="S002", name="Another Co", default_segment=segment),
            segment=segment, amount=Decimal("1.00"), status="prepared",
        )
        e = _resolve(staff, "show me PO-2026-0007", [segment.company])
        assert e.po is not None and e.po.pk == po.pk
        e = _resolve(staff, "balance of customer C009", [segment.company])
        assert e.customer is not None and e.customer.pk == customer.pk

    def test_rfp_code_without_dash(self, staff, segment, accounts, company, db):
        rfp = RFPDocument.objects.create(
            ap_number="A1027", rfp_date=date(2026, 9, 1), payee=Supplier.objects.create(code="S003", name="Third Co", default_segment=segment),
            segment=segment, amount=Decimal("1.00"), status="posted",
        )
        e = _resolve(staff, "what rfp is A1027", [segment.company])
        assert e.rfp is not None and e.rfp.pk == rfp.pk

    def test_account_by_code_and_name(self, staff, segment, accounts, company, db):
        e = _resolve(staff, "balance of 10010", [segment.company])
        assert e.account is not None and e.account.code == "10010"
        e = _resolve(staff, "what is the balance of the cash on hand account", [segment.company])
        assert e.account is not None and e.account.code == "10010"

    def test_period_defaults_to_latest_activity(self, staff, segment, accounts, company, db):
        from apps.assistant.answers.context import latest_activity_period
        from .test_answer_handlers import _post

        _post(company, segment, date(2026, 9, 20), [("10010", "5.00"), ("41010", "-5.00")], "JE-P1", "x")
        p = latest_activity_period([company])
        assert p is not None
        assert p.start == date(2026, 9, 1) and p.end == date(2026, 9, 30)
        assert p.is_default

    def test_bank_lookup(self, staff, segment, accounts, company, db):
        from apps.cash.models import BankAccount

        bank = BankAccount.objects.create(
            code="PNB-SAV", name="PNB Savings", bank_name="PNB", account_type="savings",
            gl_account=accounts["10010"], company=company, is_active=True,
        )
        e = _resolve(staff, "bank balance of pnb savings", [company])
        assert e.bank is not None and e.bank.pk == bank.pk