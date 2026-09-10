"""End-to-end flow tests: source document -> JE -> GL -> TB -> FS.

Closes the loop the operators care about: an RFP run through the real AP
services (RFPService -> CONSOService) and a CV run through the real payment
service (CVPaymentService) must each land in the GeneralLedger projection,
show up in the signed Trial Balance, and flow into the generated statements.

The reporting suite's `_post` helper posts bare JEs; these tests drive the
actual production services so the whole chain (including the CV approval/clear
gate and the CONSO batch) is exercised exactly as an operator would.

All data is created inside pytest's `db` transaction and rolled back.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.ap.models import CONSOBatch, Supplier
from apps.ap.services import CONSOService, CVPaymentService, RFPService
from apps.posting.models import GeneralLedger
from apps.reporting.models import StatementType
from apps.reporting.services import (
    FinancialStatementService,
    StatementTemplateService,
    TrialBalanceService,
)

P1 = date(2026, 1, 1)
P31 = date(2026, 1, 31)


@pytest.fixture
def supplier(db, segment):
    return Supplier.objects.create(
        code="S001", name="Shandong Fuel Depot", default_segment=segment
    )


@pytest.fixture
def staff(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="staff", password="x")


@pytest.fixture
def head(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="head", password="x")


@pytest.fixture
def templates(db):
    return StatementTemplateService.seed_defaults()


def _square_rfp(staff, segment, supplier, accounts, ap_number, amount="85000.00"):
    return RFPService.create_rfp(
        ap_number=ap_number, rfp_date=date(2026, 1, 15), payee=supplier,
        segment=segment,
        lines=[
            {"side": "dr", "segment": segment, "account_code": "61100",
             "amount": amount, "description": "Fuel delivery"},
            {"side": "cr", "segment": segment, "account_code": "20000",
             "amount": amount, "description": "AP - Supplier"},
        ],
        user=staff,
    )


def _approve_and_post(rfp, head):
    rfp.status = "submitted"
    rfp.save(update_fields=["status", "updated_at"])
    rfp = RFPService.approve_head(rfp, user=head)
    assert rfp.status == "fin_approved"
    batch = CONSOBatch.objects.create(
        batch_no=f"CONSO-2026-{rfp.ap_number}", conso_date=rfp.rfp_date
    )
    rfp.conso = batch
    rfp.save(update_fields=["conso", "updated_at"])
    CONSOService.post_batch(batch=batch, user=head)
    rfp.refresh_from_db()
    assert rfp.status == "posted"
    return rfp


class TestRFPFlowsToTrialBalance:
    def test_posted_rfp_je_hits_gl_tb_and_is(
        self, company, segment, supplier, accounts, staff, head, templates
    ):
        rfp = _approve_and_post(
            _square_rfp(staff, segment, supplier, accounts, "A9001"), head
        )

        # 1) JE is posted exactly as the RFP's distribution lines were entered.
        je = rfp.journal_entry
        assert je.is_posted
        gl = {g.account.code: g for g in GeneralLedger.objects.filter(entry=je)}
        assert set(gl) == {"61100", "20000"}
        assert gl["61100"].debit == Decimal("85000.00")
        assert gl["20000"].credit == Decimal("85000.00")

        # 2) Trial balance carries the signed balances (debit/credit-normal).
        tb = TrialBalanceService.segment_balances(company)
        assert tb["61100"]["DHPP"] == Decimal("85000.00")
        assert tb["20000"]["DHPP"] == Decimal("85000.00")

        # 3) Income statement picks the RFP expense up as an operating expense.
        fs = FinancialStatementService.generate(
            company=company, statement_type=StatementType.INCOME_STATEMENT,
            period_start=P1, period_end=P31,
        )
        rows = fs.rows_by_key()
        assert rows["operating_expenses"]["amounts"]["GRAND"] == "85000.00"
        assert rows["net_profit"]["amounts"]["GRAND"] == "-85000.00"


class TestCVFlowsToTrialBalance:
    def test_cleared_cv_je_hits_gl_and_tb(
        self, company, segment, supplier, accounts, staff, head, segment_account_map
    ):
        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0001", cv_date=date(2026, 1, 25),
            payee=supplier, bank_account=accounts["10010"],
            gross_amount="10000.00", withheld_tax="200.00", user=staff,
        )
        # Not cleared yet: JE is DRAFT, no GL rows at all.
        assert not cv.journal_entry.is_posted
        assert GeneralLedger.objects.filter(entry=cv.journal_entry).count() == 0

        CVPaymentService.approve(cv, user=head)
        CVPaymentService.clear(cv, user=head)
        cv.refresh_from_db()
        assert cv.status == "cleared"
        assert cv.journal_entry.is_posted

        # GL carries the 7.4 WHT split: Dr AP 10k | Cr Cash 9.8k | Cr WHT 0.2k.
        gl = {g.account.code: g for g in GeneralLedger.objects.filter(entry=cv.journal_entry)}
        assert set(gl) == {"20000", "10010", "64110"}
        assert gl["20000"].debit == Decimal("10000.00")
        assert gl["10010"].credit == Decimal("9800.00")
        assert gl["64110"].credit == Decimal("200.00")

        tb = TrialBalanceService.segment_balances(company)
        assert tb["20000"]["DHPP"] == Decimal("-10000.00")
        assert tb["10010"]["DHPP"] == Decimal("-9800.00")
        assert tb["64110"]["DHPP"] == Decimal("200.00")


class TestCVNotClearedStaysOutOfBooks:
    def test_approved_but_uncleared_cv_never_hits_gl_or_tb(
        self, company, segment, supplier, accounts, staff, head, segment_account_map
    ):
        """The user-facing gap: a CV trapped at 'approved' (never cleared) has
        NO GL rows, so it must not appear in the trial balance."""
        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0002", cv_date=date(2026, 1, 25),
            payee=supplier, bank_account=accounts["10010"],
            gross_amount="10000.00", withheld_tax="0.00", user=staff,
        )
        CVPaymentService.approve(cv, user=head)
        assert cv.status == "approved"

        tb_before = TrialBalanceService.segment_balances(company)
        assert GeneralLedger.objects.filter(entry=cv.journal_entry).count() == 0
        assert "10010" not in tb_before  # neither side leaked into the books

        CVPaymentService.clear(cv, user=head)
        cv.refresh_from_db()
        assert GeneralLedger.objects.filter(entry=cv.journal_entry).count() == 2
        tb_after = TrialBalanceService.segment_balances(company)
        assert tb_after["10010"]["DHPP"] == Decimal("-10000.00")


class TestFullChainBalances:
    def test_rfp_plus_cv_produces_balanced_balance_sheet(
        self, company, segment, supplier, accounts, staff, head,
        segment_account_map, templates,
    ):
        """RFP (Dr Expense | Cr AP) then CV (Dr AP | Cr Cash), no WHT, must
        net to a balance sheet identity: Assets == Liabilities + Equity."""
        rfp = _approve_and_post(
            _square_rfp(staff, segment, supplier, accounts, "A9002"), head
        )
        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0003", cv_date=date(2026, 1, 26),
            payee=supplier, bank_account=accounts["10010"],
            gross_amount="85000.00", withheld_tax="0.00", user=staff,
        )
        CVPaymentService.approve(cv, user=head)
        CVPaymentService.clear(cv, user=head)

        # Net zero AP, cash pulled down, expense still in the income statement.
        tb = TrialBalanceService.segment_balances(company)
        assert tb["20000"]["DHPP"] == Decimal("0.00")
        assert tb["10010"]["DHPP"] == Decimal("-85000.00")
        assert tb["61100"]["DHPP"] == Decimal("85000.00")

        fs = FinancialStatementService.generate(
            company=company, statement_type=StatementType.INCOME_STATEMENT,
            period_start=P1, period_end=P31,
        )
        net_profit = fs.rows_by_key()["net_profit"]["amounts"]["GRAND"]
        assert net_profit == "-85000.00"

        sfp = FinancialStatementService.generate(
            company=company, statement_type=StatementType.BALANCE_SHEET,
            period_start=P1, period_end=P31,
            inputs={"eq_net_profit": net_profit},
        )
        assert sfp.identity_ok, "Balance sheet identity must hold after RFP+CV"
        rows = sfp.rows_by_key()
        assert rows["total_assets"]["amounts"]["GRAND"] == rows["total_liab_equity"]["amounts"]["GRAND"]