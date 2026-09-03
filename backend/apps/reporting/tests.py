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
from apps.reporting.excel_export import (
    build_cash_flow_statement,
    build_statement_of_changes_in_equity,
    build_statement_of_cost_of_sales,
    build_statement_of_financial_position,
    build_statement_of_total_expenses,
    build_trial_balance,
)
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


class TestClosingJournals:
    """§13 closing entries (Batch D): revenue/expense close into Capital
    (13.1/13.2) and appropriation reserves (13.3), all data-driven."""

    def test_close_segment_posts_balanced_jes(self, company, segments, coa, jan, period_data):
        end = jan.end_date
        rev, exp = MonthEndCloseService.close_segment(
            company, segments["DHPP"], jan.start_date, end
        )
        # Revenue close: DHPP sales 40000 250k + gain 43070 5k debited, the
        # 40500 contra_revenue (5k, debit-normal) credited => net Cr Capital 250k.
        assert rev is not None and rev.is_posted
        assert rev.total_debit == rev.total_credit == Decimal("255000.00")
        cap = coa["30000"]
        cap_credit = sum(
            l.credit for l in rev.lines.all() if l.account_id == cap.pk
        )
        assert cap_credit == Decimal("250000.00")
        # Expense close: DHPP COGS 150k+10k + opp 8+2+3+12k + nonop 1+2k = 188k Dr.
        assert exp is not None and exp.is_posted
        assert exp.total_debit == exp.total_credit == Decimal("188000.00")

    def test_close_zeroes_nominal_dhpp(self, company, segments, coa, jan, period_data):
        rev, exp = MonthEndCloseService.close_segment(
            company, segments["DHPP"], jan.start_date, jan.end_date
        )
        # After closing, DHPP nominal accounts have zero period balance.
        bal = TrialBalanceService.segment_balances(company, start=jan.start_date, end=jan.end_date)
        for acct in coa.values():
            if acct.account_type in ("revenue", "contra_revenue", "expense", "contra_expense"):
                assert Decimal(bal.get(acct.code, {}).get("DHPP", "0")) == 0, acct.code

    def test_close_period_links_jes(self, company, segments, coa, jan, period_data):
        mec = MonthEndCloseService.get_or_create(jan)
        mec = MonthEndCloseService.close_period(mec, user=None)
        assert mec.revenue_close_entry is not None
        assert mec.expense_close_entry is not None

    def test_appropriation_noop_without_reserve_accounts(
        self, company, segments, coa, jan, period_data
    ):
        # Current COA has no 3xxxx reserve accounts -> §13.3 defers (no JE).
        mec = MonthEndCloseService.get_or_create(jan)
        mec = MonthEndCloseService.close_period(mec, user=None)
        mec = MonthEndCloseService.apply_appropriations(mec, user=None)
        assert mec.appropriation_entry is None

    def test_appropriation_posts_balanced_je_when_reserves_resolved(
        self, company, segments, coa, jan, period_data
    ):
        from apps.foundation.models import SegmentAccountMap

        rm = Account.objects.create(
            code="33010", name="Appropriation Reserve - R&M", account_type="equity",
            segment="DHPP", normal_balance="credit",
        )
        tith = Account.objects.create(
            code="33020", name="Appropriation Reserve - Tithing", account_type="equity",
            segment="DHPP", normal_balance="credit",
        )
        SegmentAccountMap.objects.create(
            segment=segments["DHPP"], role="appropriation_rm", account=rm,
            is_active=True,
        )
        SegmentAccountMap.objects.create(
            segment=segments["DHPP"], role="appropriation_tithing", account=tith,
            is_active=True,
        )
        mec = MonthEndCloseService.get_or_create(jan)
        mec = MonthEndCloseService.close_period(mec, user=None)
        mec = MonthEndCloseService.apply_appropriations(mec, user=None)
        app = mec.appropriation_entry
        assert app is not None and app.is_posted
        assert app.total_debit == app.total_credit
        assert app.total_debit > 0


class TestExcelExport:
    """Excel builders mirror the source workbooks cell-for-cell (the builders
    only; the HTTP export endpoints are covered by the e2e suite). Values are
    always recomputed from the posted GL, never hardcoded."""

    @staticmethod
    def _code_rows(ws):
        return {ws.cell(row=r, column=1).value: r for r in range(6, ws.max_row + 1)}

    def test_trial_balance_mirrors_workbook(self, company, segments, coa, period_data):
        wb = build_trial_balance(company, 2026)
        ws = wb["TRIAL BALANCE"]
        assert "I2:AJ2" in {str(r) for r in ws.merged_cells.ranges}
        assert ws["I2"].value == "SEVEN-TRENT MACHINERIES INDUSTRIAL EQUIPMENT TRADING (TRIAL BALANCE)"
        # alternating Dr./Cr. from I4
        assert ws["H4"].value is None and ws["I4"].value == "Dr." and ws["J4"].value == "Cr."
        # header band row 5
        assert [ws.cell(row=5, column=i).value for i in range(1, 9)] == [
            "COA", "Normal Balance of Account Titles", "ACCOUNT TITLES", "SEGMENT",
            "CLASSIFICATION", "CATEGORY", "Sub-Accounts", "Major Accounts"]
        assert ws["I5"].value == "OPENING BALANCES"
        assert ws["K5"].value == "JANUARY"
        assert ws["AI5"].value == "YTD Balances"
        # first account row is 10010 (ordered by code), COA columns echoed
        rows = self._code_rows(ws)
        assert rows["10010"] == 6
        assert ws["A6"].value == "10010"
        assert ws["B6"].value == "Dr."
        assert ws["C6"].value == "Cash on Hand"
        assert ws["D6"].value == "DHPP"
        # Cash: opening 0, Jan Dr 395000 (400k capital - 5k drawings), YTD same;
        # only one side of a Dr/Cr pair is ever populated
        assert ws["I6"].value == 0
        assert ws["K6"].value == 395000
        assert ws["L6"].value is None
        assert ws["AI6"].value == 395000
        assert ws["AJ6"].value is None
        # credit-normal AP account: Jan Cr 273000
        ap_row = rows["20000"]
        assert ws.cell(row=ap_row, column=11).value is None
        assert ws.cell(row=ap_row, column=12).value == 273000
        # contra-equity drawings (debit-normal): Jan Dr 5000
        dr_row = rows["30500"]
        assert ws.cell(row=dr_row, column=11).value == 5000
        assert ws.cell(row=dr_row, column=12).value is None

    def test_sfp_mirrors_workbook_and_identity(self, company, segments, coa, period_data, templates):
        wb = build_statement_of_financial_position(
            company, date(2026, 1, 1), date(2026, 1, 31), "127000.00")
        ws = wb["YEAR END"]
        assert ws["B4"].value == "STATEMENT OF FINANCIAL POSITION"
        assert ws["B5"].value == "As of  January 31, 2026"
        assert ws["B6"].value == "ASSETS" and ws["E6"].value == "LIABILITIES AND OWNER'S EQUITY"
        assert ws["B8"].value == "Cash" and ws["C8"].value == 395000
        assert ws["E8"].value == "Accounts Payable" and ws["F8"].value == 273000
        assert ws["B10"].value == "Accounts Receivable" and ws["C10"].value == 400000
        assert ws["C16"].value == 795000
        assert ws["F16"].value == 273000
        assert ws["F25"].value == 400000
        assert ws["F26"].value == 5000
        assert ws["F27"].value == 522000
        # identity: assets == liabilities + equity (127k net profit input)
        assert ws["C29"].value == ws["F29"].value == 795000
        assert float(ws["C32"].value) == pytest.approx(273000 * 100 / 795000, abs=0.001)
        assert float(ws["C33"].value) == pytest.approx(795000 / 273000, abs=0.001)

    def test_soce_mirrors_workbook(self, company, segments, coa, period_data, templates):
        wb = build_statement_of_changes_in_equity(
            company, date(2026, 1, 1), date(2026, 1, 31), "127000.00")
        ws = wb["EQUITY"]
        assert "C2:D2" in {str(r) for r in ws.merged_cells.ranges}
        assert ws["C2"].value == "STATEMENT OF CHANGES IN EQUITY"
        assert ws["B6"].value == "EQUITY ACCOUNTS" and ws["D6"].value == "TOTAL"
        assert ws["B7"].value == "E.Bagatua, Beginning Capital" and ws["D7"].value == 0
        assert ws["B8"].value == "Additional Capital" and ws["D8"].value == 400000
        assert ws["B9"].value == "Net Profit / Loss for the year (+ / - )" and ws["D9"].value == 127000
        assert ws["B10"].value == "Total" and ws["D10"].value == 527000
        assert ws["B11"].value == "Less: E. Bagatua, Drawings" and ws["D11"].value == 5000
        assert ws["B12"].value == "E. Bagatua, Ending Capital" and ws["D12"].value == 522000

    def test_cos_mirrors_workbook(self, company, segments, coa, period_data, templates):
        wb = build_statement_of_cost_of_sales(company, date(2026, 1, 1), date(2026, 1, 31))
        ws = wb["COST OF SALES"]
        assert ws["B1"].value.startswith("\nSEVEN-TRENT MACHINERIES")
        assert ws["A8"].value == "Distribution and Hauling of Petroleum Products (DHPP)"
        assert ws["A9"].value == "ACCOUNT TITLES" and ws["E9"].value == "GRAND TOTAL"
        # DHPP detail rows 10-21, total row 22
        assert ws["A10"].value == "COGS - Subscription Fees" and ws["E10"].value == 0
        assert ws["A11"].value == "COGS - Depreciation of Fuel Tankers_DHPP" and ws["E11"].value == 10000
        assert ws["A12"].value == "COGS - Fuel Purchase" and ws["E12"].value == 150000
        assert ws["E22"].value == 160000
        assert ws["A23"].value == "VOLUME IN LITERS"
        assert ws["A24"].value == "DIRECT COST PER LITER "
        # DMIE section
        assert ws["A25"].value == "Distribution of Machineries and Industrial Equipment (DMIE)"
        assert ws["A27"].value == "COGS - Calibration Bucket" and ws["E27"].value == 60000
        assert ws["E45"].value == 60000
        # OPS section
        assert ws["A46"].value == "Other Products and Services (OPS)"
        assert ws["A48"].value == "COGS - Lubricants for Sale" and ws["E48"].value == 25000
        assert ws["E53"].value == 25000
        assert ws["E54"].value == 245000

    def test_te_mirrors_workbook(self, company, segments, coa, period_data, templates):
        wb = build_statement_of_total_expenses(company, date(2026, 1, 1), date(2026, 1, 31))
        ws = wb["January 2026 CGSE"]
        assert "H6:H8" in {str(r) for r in ws.merged_cells.ranges}
        assert ws["H6"].value == "GRAND TOTAL"
        assert ws["A9"].value == "COGS - DHPP" and ws["H9"].value == 160000
        assert ws["A12"].value == "Total Cost of Sales" and ws["H12"].value == 245000
        assert ws["A14"].value == "Accommodation Fees" and ws["H14"].value == 8000
        assert ws["A18"].value == "Depreciation Expense (Others)" and ws["H18"].value == 2000
        assert ws["A21"].value == "Insurance Fees" and ws["H21"].value == 3000
        assert ws["A26"].value == "Salary and Company Benefits" and ws["H26"].value == 12000
        assert ws["A33"].value == "Total Operating Expenses" and ws["H33"].value == 25000
        assert ws["A34"].value == "Other Gen. & Admin. Expense" and ws["H34"].value == 2000
        assert ws["A35"].value == "Other Expense/Miscellaneous Exp." and ws["H35"].value == 1000
        assert ws["A37"].value == "TOTAL OPERATING COSTS" and ws["H37"].value == 273000
        assert ws["A43"].value == "Legend:"
        assert ws["A44"].value == "DHPP - Distribution and Hauling of Petroleum Products"
        assert ws["A46"].value == "OPS - Other Products and Services"

    def test_cash_flow_mirrors_workbook(self, segments, coa):
        from apps.cash.models import ActivityType, BankAccount, CashCycleActivity, WeeklyCashCycle

        dhpp = segments["DHPP"]
        BankAccount.objects.create(
            code="PNB-DHPP", name="PNB DHPP", account_type="checking",
            bank_name="PNB", bank_code="PNB", gl_account=coa["10010"],
            company=dhpp.company, adb_required=Decimal("5000.00"),
        )
        WeeklyCashCycle.objects.create(
            cycle_start=date(2026, 1, 6), cycle_end=date(2026, 1, 12),
            segment=dhpp, closing_balance=Decimal("100000.00"),
        )
        c2 = WeeklyCashCycle.objects.create(
            cycle_start=date(2026, 1, 13), cycle_end=date(2026, 1, 19),
            segment=dhpp, closing_balance=Decimal("150000.00"),
        )
        for atype, amount in [
            (ActivityType.COLLECTION_DIST, "120000.00"),
            (ActivityType.OTHER_COLLECTION, "30000.00"),
            (ActivityType.SUPPLIER_PAYMENT, "50000.00"),
            (ActivityType.RFP_AP, "20000.00"),
            (ActivityType.PCF_REPLEN, "5000.00"),
            (ActivityType.OTHER_PAYMENT, "10000.00"),
            (ActivityType.CAPEX, "25000.00"),
            (ActivityType.BORROWED, "40000.00"),
            (ActivityType.LOAN_CLEARED, "15000.00"),
        ]:
            CashCycleActivity.objects.create(cycle=c2, activity_type=atype, amount=Decimal(amount))

        wb = build_cash_flow_statement(dhpp.company, date(2026, 1, 6), date(2026, 1, 19))
        ws = wb["CF"]
        assert ws["B2"].value == "SEVEN-TRENT MACHINERIES INDUSTRIAL EQUIPMENT TRADING"
        assert ws["H5"].value == "Amounts in pesos"
        # operating: +120k +30k -50k -20k -5k -10k = 65k
        assert ws["H7"].value == 120000
        assert ws["H8"].value == 30000
        assert ws["H9"].value == 50000
        assert ws["H10"].value == 20000
        assert ws["H11"].value == 5000
        assert ws["H12"].value == 10000
        assert ws["H13"].value == 65000
        # investing / financing
        assert ws["H17"].value == -25000
        assert ws["H19"].value == 40000
        assert ws["H20"].value == 15000
        assert ws["H21"].value == 25000
        # net change, beginning, ADB 5k, ending = 150k - 5k
        assert ws["H22"].value == 65000
        assert ws["H23"].value == 0
        assert ws["H24"].value == 5000
        assert ws["H25"].value == 145000
