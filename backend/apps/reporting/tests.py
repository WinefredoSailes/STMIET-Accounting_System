"""Financial Statement contract tests (BUILD-PLAN Phase 8).

- TrialBalanceService: signed balances from posted GL (ADR-005).
- Statement templates seed idempotently; IS/SFP/CoS/TE/SOCE reproduce the
  workbook layouts.
- FinancialStatementService.generate: per-segment columns + GRAND; identities
  hold (SFP: Assets == Liabilities + Equity; SOCE: ending == total - drawings).
- MonthEndCloseService: accruals -> recon -> close -> appropriations; the
  fiscal period locks on completion (posting §17 no back-posting).
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.foundation.models import Account, Company, FiscalPeriod, FiscalYear, Segment
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService
from apps.reporting.models import StatementTemplate, StatementType
from apps.reporting.services import (
    FinancialStatementService,
    MonthEndCloseService,
    StatementTemplateService,
    TrialBalanceService,
)


@pytest.fixture
def coa(db):
    """Accounts covering all five statement sections (IS/SFP/CoS/TE/SOCE)."""
    rows = [
        # assets
        ("10010", "Cash on Hand", "asset", "DHPP", "debit"),
        ("10013", "Cash on Hand-DMIE", "asset", "DMIE", "debit"),
        ("10016", "Cash on Hand-OPS", "asset", "OPS", "debit"),
        ("12030", "A/Receivables - Fuel Clients", "asset", "DHPP", "debit"),
        ("13000", "Fuel Inventory", "asset", "DHPP", "debit"),
        ("17010", "Fuel Tankers", "asset", "DHPP", "debit"),
        ("18513", "Accumulated Dep'n - Boom Trucks", "asset", "DMIE", "credit"),
        ("19000", "Container Van", "asset", "DHPP", "debit"),
        ("19760", "Accumulated Dep'n - Building and Improvements", "asset", "DHPP", "credit"),
        ("19800", "Furniture and Fixtures", "asset", "DHPP", "debit"),
        # liabilities
        ("20000", "A/Payables - Current - DHPP", "liability", "DHPP", "credit"),
        ("21000", "Unearned Revenue - DHPP", "liability", "DHPP", "credit"),
        ("27010", "Loans Payable_NC - DHPP", "liability", "DHPP", "credit"),
        # equity
        ("30000", "E.Bagatua Capital - DHPP", "equity", "DHPP", "credit"),
        ("30500", "E.Bagatua, Drawings - DHPP", "contra_equity", "DHPP", "debit"),
        # revenue
        ("40000", "Sales -Fuel Hauling", "revenue", "DHPP", "credit"),
        ("41003", "Sales - DMIE", "revenue", "DMIE", "credit"),
        ("42006", "Sales - OPS", "revenue", "OPS", "credit"),
        ("40500", "Sales Discount - Hauling", "contra_revenue", "DHPP", "debit"),
        ("43070", "Income from Disposal - DHPP", "revenue", "DHPP", "credit"),
        # cost of sales
        ("50000", "COGS - Fuel Purchase", "expense", "DHPP", "debit"),
        ("50110", "COGS - Depreciation of Fuel Tankers_DHPP", "expense", "DHPP", "debit"),
        ("51003", "COGS - Calibration Bucket", "expense", "DMIE", "debit"),
        ("52006", "COGS - Lubricants for Sale", "expense", "OPS", "debit"),
        # operating expenses
        ("61000", "Hotel Accomodation_DHPP", "expense", "DHPP", "debit"),
        ("61600", "Depreciation Expense_DHPP", "expense", "DHPP", "debit"),
        ("62200", "Insurance Expense_DHPP", "expense", "DHPP", "debit"),
        ("63400", "13th Month Pay_DHPP", "expense", "DHPP", "debit"),
        # non-operating
        ("65000", "Miscellaneous Expenses_DHPP", "expense", "DHPP", "debit"),
        ("66000", "Other Gen. and Admin. Expenses_DHPP", "expense", "DHPP", "debit"),
    ]
    out = {}
    for code, name, atype, seg, nb in rows:
        out[code] = Account.objects.create(
            code=code, name=name, account_type=atype, segment=seg, normal_balance=nb,
        )
    return out


def _post(company, segment, date_, lines, entry_no, desc, *, src="TEST", user=None):
    """Post a balanced JE from (account_code, amount) with sign: Dr(+)/Cr(-)."""
    je = JournalEntry.objects.create(
        entry_no=entry_no,
        company=company,
        segment=segment,
        transaction_date=date_,
        status=PostingStatus.DRAFT,
        description=desc,
        source_doc_type=src,
        created_by=user,
    )
    line_no = 1
    for code, raw in lines:
        amount = Decimal(raw)
        kwargs = {"debit": amount} if amount >= 0 else {"credit": -amount}
        JournalEntryLine.objects.create(
            entry=je, line_no=line_no, account=Account.objects.get(code=code), **kwargs
        )
        line_no += 1
    je.recalc_totals()
    if je.total_debit > Decimal("100000.00"):
        je.status = PostingStatus.APPROVED
        je.save(update_fields=["status", "updated_at"])
    return PostingService.post(je, user=user)


@pytest.fixture
def company(db):
    return Company.objects.create(code="STMIET", name="STMIET Testing")


@pytest.fixture
def segments(db, company):
    return {
        "DHPP": Segment.objects.create(code="DHPP", name="DHPP", company=company),
        "DMIE": Segment.objects.create(code="DMIE", name="DMIE", company=company),
        "OPS": Segment.objects.create(code="OPS", name="OPS", company=company),
    }


@pytest.fixture
def fy(db, company):
    return FiscalYear.objects.create(
        company=company, code="2026", start_date="2026-01-01", end_date="2026-12-31"
    )


@pytest.fixture
def jan(db, fy):
    return FiscalPeriod.objects.create(
        fiscal_year=fy, period_no=1, start_date="2026-01-01", end_date="2026-01-31"
    )


@pytest.fixture
def period_data(db, company, segments, coa):
    """Post a realistic January activity set across DHPP/DMIE/OPS.

    JEs (all under 100k -> no approval gate):
      - Opening capital DHPP: Dr Cash 400k | Cr Capital 400k
      - Sales DHPP: Dr AR 250k | Cr Sales 250k
      - Sales DMIE: Dr AR 100k | Cr Sales 100k
      - Sales OPS: Dr AR 50k | Cr Sales 50k
      - Sales discount: Dr 40500 5k | Cr AR 5k
      - COGS DHPP: Dr 50000 150k, Dr 50110 10k | Cr AP 160k
      - COGS DMIE: Dr 51003 60k | Cr AP 60k
      - COGS OPS: Dr 52006 25k | Cr AP 25k
      - Other income: Dr AR 5k | Cr 43070 5k
      - Op expenses: Dr 61000 8k, Dr 61600 2k, Dr 62200 3k, Dr 63400 12k | Cr AP 25k
      - Non-op: Dr 65000 1k, Dr 66000 2k | Cr AP 3k
      - Drawings: Dr 30500 5k | Cr Cash 5k
    """
    dhpp, dmie, ops = segments["DHPP"], segments["DMIE"], segments["OPS"]
    _post(company, dhpp, date(2026, 1, 2), [("10010", "400000.00"), ("30000", "-400000.00")],
          "JE-0001", "Opening capital")
    _post(company, dhpp, date(2026, 1, 5), [("12030", "250000.00"), ("40000", "-250000.00")],
          "JE-0002", "Fuel sales")
    _post(company, dmie, date(2026, 1, 6), [("12030", "100000.00"), ("41003", "-100000.00")],
          "JE-0003", "DMIE sales")
    _post(company, ops, date(2026, 1, 7), [("12030", "50000.00"), ("42006", "-50000.00")],
          "JE-0004", "OPS sales")
    _post(company, dhpp, date(2026, 1, 8), [("40500", "5000.00"), ("12030", "-5000.00")],
          "JE-0005", "Sales discount")
    _post(company, dhpp, date(2026, 1, 9), [("50000", "150000.00"), ("50110", "10000.00"),
                                            ("20000", "-160000.00")], "JE-0006", "DHPP COGS")
    _post(company, dmie, date(2026, 1, 10), [("51003", "60000.00"), ("20000", "-60000.00")],
          "JE-0007", "DMIE COGS")
    _post(company, ops, date(2026, 1, 11), [("52006", "25000.00"), ("20000", "-25000.00")],
          "JE-0008", "OPS COGS")
    _post(company, dhpp, date(2026, 1, 12), [("12030", "5000.00"), ("43070", "-5000.00")],
          "JE-0009", "Gain on disposal")
    _post(company, dhpp, date(2026, 1, 13), [("61000", "8000.00"), ("61600", "2000.00"),
                                             ("62200", "3000.00"), ("63400", "12000.00"),
                                             ("20000", "-25000.00")], "JE-0010", "Operating expenses")
    _post(company, dhpp, date(2026, 1, 14), [("65000", "1000.00"), ("66000", "2000.00"),
                                             ("20000", "-3000.00")], "JE-0011", "Non-operating expenses")
    _post(company, dhpp, date(2026, 1, 15), [("30500", "5000.00"), ("10010", "-5000.00")],
          "JE-0012", "Drawings")


@pytest.fixture
def templates(db):
    return StatementTemplateService.seed_defaults()


class TestTrialBalance:
    def test_balances_signed_by_normal_balance(self, company, segments, coa, period_data):
        bal = TrialBalanceService.segment_balances(company)
        # Cash: +400k - 5k (drawings) = +395k debit-normal.
        assert bal["10010"]["DHPP"] == Decimal("395000.00")
        # Sales credit-normal: +250k
        assert bal["40000"]["DHPP"] == Decimal("250000.00")
        # Sales discount debit-normal contra: +5k (line applies sign -1).
        assert bal["40500"]["DHPP"] == Decimal("5000.00")
        # COGS expense debit-normal: 160k
        assert bal["50000"]["DHPP"] == Decimal("150000.00")
        # Capital credit-normal: 400k
        assert bal["30000"]["DHPP"] == Decimal("400000.00")

    def test_rows_ytd(self, company, segments, coa, period_data):
        rows = {r["code"]: r for r in TrialBalanceService.rows(company, as_of=date(2026, 1, 31))}
        assert rows["10010"]["balance"] == Decimal("395000.00")
        assert rows["40000"]["balance"] == Decimal("250000.00")


class TestTemplates:
    def test_seed_idempotent(self, db, templates):
        StatementTemplateService.seed_defaults()
        assert StatementTemplate.objects.count() == 5
        for ttype in ("is", "sfp", "cos", "te", "soce"):
            assert StatementTemplate.objects.filter(statement_type=ttype).exists()

    def test_is_layout(self, templates):
        tpl = templates[StatementType.INCOME_STATEMENT]
        keys = [l.key for l in tpl.lines.all()]
        for k in ("sales", "cogs", "gross_profit", "net_profit", "gpm",
                  "app_rm", "app_tithing", "app_remaining"):
            assert k in keys

    def test_sfp_layout(self, templates):
        tpl = templates[StatementType.BALANCE_SHEET]
        keys = [l.key for l in tpl.lines.all()]
        for k in ("total_assets", "total_liab_equity", "total_equity", "eq_net_profit"):
            assert k in keys


class TestIncomeStatement:
    def test_generate_matches_expected(self, company, segments, coa, period_data, templates):
        fs = FinancialStatementService.generate(
            company=company, statement_type=StatementType.INCOME_STATEMENT,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            inputs={"app_basis": "100000.00"},
        )
        rows = fs.rows_by_key()
        # Sales 400k (DHPP 250 + DMIE 100 + OPS 50), discount 5k -> net 395k
        assert rows["net_sales"]["amounts"]["GRAND"] == "395000.00"
        # COGS 160 + 60 + 25 = 245k
        assert rows["cogs"]["amounts"]["GRAND"] == "245000.00"
        # Gross profit 150k
        assert rows["gross_profit"]["amounts"]["GRAND"] == "150000.00"
        # Other income 5k -> operating income 155k
        assert rows["total_operating_income"]["amounts"]["GRAND"] == "155000.00"
        # Op expenses 25k -> operating profit 130k
        assert rows["operating_profit"]["amounts"]["GRAND"] == "130000.00"
        # Non-op 3k -> net profit 127k
        assert rows["net_profit"]["amounts"]["GRAND"] == "127000.00"
        # Per-segment net profit: DHPP 250-5 -160 -25(exp) -3(nonop) = 57k; plus gain 5k
        #   DHPP: net sales 245k - cogs 160k = 85k; + other income 5k = 90k; - op exp 25k = 65k; - nonop 3k = 62k
        assert rows["net_profit"]["amounts"]["DHPP"] == "62000.00"
        assert rows["net_profit"]["amounts"]["DMIE"] == "40000.00"
        assert rows["net_profit"]["amounts"]["OPS"] == "25000.00"
        # Metrics: GPM = 150/395 = 37.97%
        assert rows["gpm"]["amounts"]["GRAND"] == "37.97"
        # Appropriations from inputs-provided basis 100k -> 10k / 10k / 80k
        assert rows["app_rm"]["amounts"]["GRAND"] == "10000.00"
        assert rows["app_tithing"]["amounts"]["GRAND"] == "10000.00"
        assert rows["app_remaining"]["amounts"]["GRAND"] == "80000.00"


class TestBalanceSheet:
    def test_assets_equal_liabilities_equity(self, company, segments, coa, period_data, templates):
        fs = FinancialStatementService.generate(
            company=company, statement_type=StatementType.BALANCE_SHEET,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            inputs={"eq_net_profit": "127000.00"},
        )
        assert fs.identity_ok
        rows = fs.rows_by_key()
        assert rows["total_assets"]["amounts"]["GRAND"] == rows["total_liab_equity"]["amounts"]["GRAND"]

    def test_asset_breakdown(self, company, segments, coa, period_data, templates):
        fs = FinancialStatementService.generate(
            company=company, statement_type=StatementType.BALANCE_SHEET,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            inputs={"eq_net_profit": "127000.00"},
        )
        rows = fs.rows_by_key()
        # Cash 395k (no fixed assets booked this period)
        assert rows["ca_cash"]["amounts"]["GRAND"] == "395000.00"
        # Receivables: AR 250+100+50 -5(discount) +5(gain) = 400k
        assert rows["ca_receivables"]["amounts"]["GRAND"] == "400000.00"
        # Equity: capital 400k - drawings 5k + net profit 127k = 522k
        assert rows["total_equity"]["amounts"]["GRAND"] == "522000.00"


class TestCostOfSales:
    def test_cos_by_segment(self, company, segments, coa, period_data, templates):
        fs = FinancialStatementService.generate(
            company=company, statement_type=StatementType.COST_OF_SALES,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        )
        rows = fs.rows_by_key()
        assert rows["cos_dhpp_total"]["amounts"]["GRAND"] == "160000.00"
        assert rows["cos_dmie_total"]["amounts"]["GRAND"] == "60000.00"
        assert rows["cos_ops_total"]["amounts"]["GRAND"] == "25000.00"
        assert rows["total_cost_of_sales"]["amounts"]["GRAND"] == "245000.00"
        # DHPP detail rows
        assert rows["cos_dhpp_fuel"]["amounts"]["GRAND"] == "150000.00"
        assert rows["cos_dhpp_dep_tanker"]["amounts"]["GRAND"] == "10000.00"


class TestTotalExpenses:
    def test_te_breakdown(self, company, segments, coa, period_data, templates):
        fs = FinancialStatementService.generate(
            company=company, statement_type=StatementType.TOTAL_EXPENSES,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        )
        rows = fs.rows_by_key()
        assert rows["te_total_cogs"]["amounts"]["GRAND"] == "245000.00"
        assert rows["te_accommodation"]["amounts"]["GRAND"] == "8000.00"
        assert rows["te_dep_exp"]["amounts"]["GRAND"] == "2000.00"
        assert rows["te_insurance"]["amounts"]["GRAND"] == "3000.00"
        assert rows["te_salaries"]["amounts"]["GRAND"] == "12000.00"
        assert rows["te_total_operating_expenses"]["amounts"]["GRAND"] == "25000.00"
        assert rows["te_misc"]["amounts"]["GRAND"] == "1000.00"
        assert rows["te_gen_admin"]["amounts"]["GRAND"] == "2000.00"
        assert rows["te_total_non_operating"]["amounts"]["GRAND"] == "3000.00"
        assert rows["te_total_operating_costs"]["amounts"]["GRAND"] == "273000.00"


class TestSOCE:
    def test_ending_capital_identity(self, company, segments, coa, period_data, templates):
        fs = FinancialStatementService.generate(
            company=company, statement_type=StatementType.SOCE,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            inputs={"soce_net_profit": "127000.00"},
        )
        assert fs.identity_ok
        rows = fs.rows_by_key()
        # Beginning capital = opening balance of 30000 = 0 (no prior period)
        assert rows["soce_begin_capital"]["amounts"]["GRAND"] == "0.00"
        # Additional capital = activity in 30000 = 400k
        assert rows["soce_additional_capital"]["amounts"]["GRAND"] == "400000.00"
        # Total = 0 + 400k + 127k = 527k
        assert rows["soce_total"]["amounts"]["GRAND"] == "527000.00"
        # Drawings 5k -> ending = 522k
        assert rows["soce_drawings"]["amounts"]["GRAND"] == "5000.00"
        assert rows["soce_ending_capital"]["amounts"]["GRAND"] == "522000.00"


class TestMonthEndClose:
    def test_workflow_locks_period(self, company, segments, coa, jan, period_data, templates):
        mec = MonthEndCloseService.get_or_create(jan)
        assert mec.status == "open"
        assert mec.is_ready is False
        # advance each step
        for step in MonthEndCloseService.STEPS:
            mec = MonthEndCloseService.advance(mec, step)
        assert mec.is_ready is True
        mec = MonthEndCloseService.complete(mec)
        assert mec.status == "closed"
        jan.refresh_from_db()
        assert jan.is_closed is True

    def test_cannot_complete_with_pending_steps(self, company, segments, coa, jan, period_data, templates):
        mec = MonthEndCloseService.get_or_create(jan)
        mec = MonthEndCloseService.advance(mec, "accruals")
        with pytest.raises(ValueError, match="pending"):
            MonthEndCloseService.complete(mec)
