"""Posting-rule family coverage (BUILD-PLAN Batch D).

Exercises the §5 (inventory), §6 (fleet fuel), §10 (govt/taxes) and §14
(payroll) canonical JEs as *actually posted* through PostingService, so each
business event is proven to balance, post, and become immutable (ADR-002/004).
The engine primitives themselves are covered in apps/posting/tests.py; this
suite is the data-driven "does each rule post correctly" contract.

Accounts here mirror POSTING_RULES.md families (130xx inventory, 23010 govt
payables, 64100 WHT payable, 64600 income-tax expense / 26000 income-tax
payable, 63800 fuel & oil, 22000 accrued expenses). The shared conftest
`accounts` slice is extended locally with only what the rules need.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.foundation.models import Account
from apps.posting.models import GeneralLedger, JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService


@pytest.fixture
def rule_accounts(db):
    """Extend the conftest COA slice with the §5/6/10/14 rule accounts."""
    def _mk(code, name, atype, nb):
        existing = Account.objects.filter(code=code).first()
        if existing:
            return existing
        return Account.objects.create(
            code=code, name=name, account_type=atype,
            segment=Account.segment_for_code(code), normal_balance=nb,
        )
    return {
        "13000": _mk("13000", "Fuel Inventory", "asset", "debit"),
        "20000": _mk("20000", "A/P - Current - DHPP", "liability", "credit"),
        "22000": _mk("22000", "Accrued Expenses", "liability", "credit"),
        "23010": _mk("23010", "Govt Payables - SSS", "liability", "credit"),
        "26000": _mk("26000", "Income Tax Payable", "liability", "credit"),
        "63800": _mk("63800", "Fuel & Oil - Travel", "expense", "debit"),
        "64100": _mk("64100", "Withholding Tax Payable", "liability", "credit"),
        "64600": _mk("64600", "Income Tax Expense", "expense", "debit"),
        "10010": _mk("10010", "Cash on Hand", "asset", "debit"),
    }


def _post(company, segment, fiscal_period, lines, entry_no, desc, *, date_=date(2026, 1, 15), user=None):
    """Post a balanced JE from (account, debit, credit) triples."""
    je = JournalEntry.objects.create(
        entry_no=entry_no, company=company, segment=segment,
        fiscal_period=fiscal_period, transaction_date=date_,
        status=PostingStatus.DRAFT, description=desc,
        created_by=user,
    )
    for i, (acct, debit, credit) in enumerate(lines, start=1):
        JournalEntryLine.objects.create(
            entry=je, line_no=i, account=acct,
            debit=Decimal(debit), credit=Decimal(credit),
        )
    je.recalc_totals()
    return je


@pytest.fixture
def additional_accounts(db):
    """Accounts referenced by exposed fixtures for §5.2/6.1/14.1 rules."""
    def _mk(code, name, atype, nb):
        return Account.objects.get_or_create(
            code=code,
            defaults=dict(
                name=name, account_type=atype,
                segment=Account.segment_for_code(code), normal_balance=nb,
            ),
        )[0]
    from apps.core.models import AuditableModel  # noqa: F401
    return _mk


@pytest.fixture
def inventory_loss_account(additional_accounts):
    return additional_accounts("63200", "Other Fees/Charges", "expense", "debit")


@pytest.fixture
def cogs_wages(additional_accounts):
    return additional_accounts("50030", "COGS - Trip Wages", "expense", "debit")


@pytest.fixture
def cogs_toll(additional_accounts):
    return additional_accounts("50090", "COGS - Toll Fees", "expense", "debit")


@pytest.fixture
def salary_acct(additional_accounts):
    return additional_accounts("61000", "Salaries & Wages", "expense", "debit")


@pytest.fixture
def accruals_acct(additional_accounts):
    return additional_accounts("22000", "Accrued Expenses", "liability", "credit")


class TestSection5Inventory:
    # §5.1 goods receipt: Dr Inventory | Cr AP
    def test_goods_receipt_posts(self, company, segment, fiscal_period, rule_accounts):
        je = _post(
            company, segment, fiscal_period,
            [(rule_accounts["13000"], "5000.00", "0"), (rule_accounts["20000"], "0", "5000.00")],
            "GR-0001", "Inventory goods receipt",
        )
        PostingService.post(je)
        je.refresh_from_db()
        assert je.is_posted and je.is_balanced
        assert GeneralLedger.objects.filter(entry=je).count() == 2
        assert je.total_debit == je.total_credit == Decimal("5000.00")

    # §5.2 write-off: Dr expense (loss) | Cr Inventory
    def test_write_off_posts_loss(self, company, segment, fiscal_period, rule_accounts,
                                  inventory_loss_account):
        je = _post(
            company, segment, fiscal_period,
            [(inventory_loss_account, "300.00", "0"), (rule_accounts["13000"], "0", "300.00")],
            "WO-0001", "Inventory write-off",
        )
        PostingService.post(je)
        assert je.is_posted and je.is_balanced
        gl = GeneralLedger.objects.get(entry=je, line__line_no=1)
        assert gl.debit == Decimal("300.00")


class TestSection6Fleet:
    # §6.4 fuel consumption: Dr Fuel & Oil | Cr Fuel Inventory
    def test_fuel_consumption_posts(self, company, segment, fiscal_period, rule_accounts):
        je = _post(
            company, segment, fiscal_period,
            [(rule_accounts["63800"], "1200.00", "0"), (rule_accounts["13000"], "0", "1200.00")],
            "FL-0001", "Fleet fuel consumption",
        )
        PostingService.post(je)
        assert je.is_posted and je.is_balanced
        assert GeneralLedger.objects.filter(entry=je).count() == 2

    # §6.1 trip completion: Dr COGS wages+toll | Cr accrued expenses
    def test_trip_completion_posts(self, company, segment, fiscal_period, rule_accounts,
                                   cogs_wages, cogs_toll):
        je = _post(
            company, segment, fiscal_period,
            [(cogs_wages, "900.00", "0"), (cogs_toll, "100.00", "0"),
             (rule_accounts["22000"], "0", "1000.00")],
            "TRIP-0001", "Trip completion",
        )
        PostingService.post(je)
        assert je.is_posted and je.is_balanced
        assert je.total_debit == je.total_credit == Decimal("1000.00")


class TestSection10GovtTaxes:
    # §10.1 govt remittance: Dr Govt Payables | Cr Cash
    def test_govt_remittance_posts(self, company, segment, fiscal_period, rule_accounts):
        je = _post(
            company, segment, fiscal_period,
            [(rule_accounts["23010"], "4500.00", "0"), (rule_accounts["10010"], "0", "4500.00")],
            "GOVT-0001", "Govt remittance",
        )
        PostingService.post(je)
        assert je.is_posted and je.is_balanced

    # §10.2 WHT remittance: Dr WHT Payable | Cr Cash
    def test_wht_remittance_posts(self, company, segment, fiscal_period, rule_accounts):
        je = _post(
            company, segment, fiscal_period,
            [(rule_accounts["64100"], "800.00", "0"), (rule_accounts["10010"], "0", "800.00")],
            "WHT-0001", "Withholding tax remittance",
        )
        PostingService.post(je)
        assert je.is_posted and je.is_balanced

    # §10.3 income tax provision: Dr Income Tax Expense | Cr Income Tax Payable
    def test_income_tax_provision_posts(self, company, segment, fiscal_period, rule_accounts):
        je = _post(
            company, segment, fiscal_period,
            [(rule_accounts["64600"], "62000.00", "0"), (rule_accounts["26000"], "0", "62000.00")],
            "TAX-0001", "Income tax provision",
        )
        PostingService.post(je)
        je.refresh_from_db()
        assert je.is_posted and je.is_balanced
        assert je.total_debit == je.total_credit == Decimal("62000.00")


class TestSection14Payroll:
    # §14.1 canonical payroll: Dr salaries + employer share; Cr accrued (employer
    # share) + WHT withheld + net cash.
    def test_payroll_je_posts(self, company, segment, fiscal_period, rule_accounts,
                              salary_acct, accruals_acct):
        gross = Decimal("23000.00")
        employer_share = Decimal("1500.00")
        employee_ded = Decimal("3000.00")  # SSS/PHIC/PagIBIG withheld
        wht = Decimal("200.00")
        net_cash = gross - employee_ded - wht
        je = _post(
            company, segment, fiscal_period,
            [(salary_acct, str(gross + employer_share), "0"),   # gross wages + employer share
             (accruals_acct, "0", str(employer_share)),         # employer share accrued
             (rule_accounts["23010"], "0", str(employee_ded)),  # employee govt deductions
             (rule_accounts["64100"], "0", str(wht)),           # WHT withheld
             (rule_accounts["10010"], "0", str(net_cash))],     # net pay
            "PAY-0001", "Payroll run",
        )
        PostingService.post(je)
        je.refresh_from_db()
        assert je.is_posted and je.is_balanced
        assert GeneralLedger.objects.filter(entry=je).count() == 5

    def test_payroll_je_immutable_after_post(self, company, segment, fiscal_period,
                                             rule_accounts, salary_acct, accruals_acct):
        je = _post(
            company, segment, fiscal_period,
            [(salary_acct, "20000.00", "0"),
             (rule_accounts["10010"], "0", "20000.00")],
            "PAY-0002", "Payroll run",
        )
        PostingService.post(je)
        with pytest.raises(Exception):
            je.lines.first().delete()