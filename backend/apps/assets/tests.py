"""Fixed Assets contract tests (BUILD-PLAN Phase 7, POSTING_RULES §9).

- Acquisition JE: Dr Asset | Cr funding (AP/Cash/Loans) — 9.1
- Straight-line monthly depreciation; Dr 50110/616xx | Cr Accum Dep — 9.2
- Schedule generation through useful life (idempotent)
- Fully-depreciated-still-in-use flag
- Disposal: Dr Cash + Dr Accum Dep | Cr Asset + Cr Gain/Loss — 9.3
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.assets.models import Asset, AssetDisposal, AssetStatus, DepreciationSchedule
from apps.assets.services import AssetService, DepreciationService, DisposalService
from apps.core.exceptions import ValidationError
from apps.foundation.models import Account
from apps.posting.models import JournalEntry, GeneralLedger


@pytest.fixture
def asset_accounts(db, segment):
    """Segment-specific accounts for the asset tests."""
    rows = [
        ("10010", "Cash on Hand", "asset", "DHPP"),
        ("20000", "A/Payables - Current - DHPP", "liability", "DHPP"),
        ("27000", "Loans Payable", "liability", "DHPP"),
        ("17010", "Fuel Tankers", "asset", "DHPP"),
        ("50110", "COGS - Depreciation of Fuel Tankers_DHPP", "expense", "DHPP"),
        ("61600", "Depreciation Expense_DHPP", "expense", "DHPP"),
        ("18513", "Accumulated Dep'n - Boom Trucks", "asset", "DMIE"),
        ("43070", "Income from Disposal - DHPP", "revenue", "DHPP"),
        ("62000", "Impairment Loss_DHPP", "expense", "DHPP"),
    ]
    out = {}
    for code, name, atype, seg in rows:
        out[code] = Account.objects.create(
            code=code, name=name, account_type=atype, segment=seg,
        )
    return out


@pytest.fixture
def tanker_category(db, asset_accounts):
    """Fuel tanker category: 10-year life, DHPP accounts (POSTING_RULES 9.2)."""
    from apps.assets.models import AssetCategory

    return AssetCategory.objects.create(
        code="TANKER",
        name="Fuel Tankers",
        useful_life_years=10,
        asset_account=asset_accounts["17010"],
        depreciation_expense_account=asset_accounts["50110"],
        accumulated_dep_account=asset_accounts["18513"],
        segment=None,
    )


@pytest.fixture
def asset(company, segment, tanker_category, asset_accounts):
    """Acquire a P60,000 tanker on 2026-01-15 (kept under the 100k JE
    approval threshold so posting proceeds without a second approver)."""
    return AssetService.acquire(
        asset_no="FA-2026-0001",
        name="Diesel Tanker 001",
        category=tanker_category,
        segment=segment,
        acquisition_date=date(2026, 1, 15),
        cost="60000.00",
        residual_value="0.00",
        funding_source="cash",
        user=None,
    )


class TestAcquisition:
    def test_acquire_posts_je(self, asset):
        """POSTING_RULES 9.1: Dr Asset | Cr Cash."""
        je = asset.acquisition_journal
        assert je.is_balanced
        assert je.status == "posted"
        lines = {l.line_no: l for l in je.lines.all()}
        assert lines[1].debit == Decimal("60000.00")  # Dr Asset
        assert lines[2].credit == Decimal("60000.00")  # Cr Cash
        assert GeneralLedger.objects.filter(entry=je).count() == 2
        assert asset.status == AssetStatus.ACTIVE

    def test_zero_cost_rejected(self, company, segment, tanker_category):
        with pytest.raises(ValidationError, match="positive"):
            AssetService.acquire(
                asset_no="FA-2026-0002", name="Bad", category=tanker_category,
                segment=segment, acquisition_date=date(2026, 1, 16), cost="0.00",
            )

    def test_loan_financed_credits_loans(self, company, segment, tanker_category, asset_accounts):
        asset = AssetService.acquire(
            asset_no="FA-2026-0003", name="Financed Tanker", category=tanker_category,
            segment=segment, acquisition_date=date(2026, 1, 16), cost="60000.00",
            funding_source="loan", financed_loan_reference="LOAN-001",
        )
        lines = {l.line_no: l for l in asset.acquisition_journal.lines.all()}
        assert lines[2].credit == Decimal("60000.00")


class TestDepreciation:
    def test_monthly_amount_straight_line(self, asset):
        # 60,000 / 10 years / 12 = 500/month.
        assert asset.monthly_depreciation == Decimal("500.00")

    def test_build_schedule_idempotent(self, asset):
        rows1 = DepreciationService.build_schedule(asset)
        rows2 = DepreciationService.build_schedule(asset)
        assert len(rows1) == 120  # 10 years
        assert len(rows2) == 120  # no duplicates
        assert DepreciationSchedule.objects.filter(asset=asset).count() == 120

    def test_post_month_creates_je(self, asset):
        row = DepreciationService.post_month(asset, period_start=date(2026, 2, 1))
        assert row.status == "posted"
        je = row.journal_entry
        assert je.is_balanced
        lines = {l.line_no: l for l in je.lines.all()}
        assert lines[1].debit == Decimal("500.00")  # Dr Depreciation Exp
        assert lines[2].credit == Decimal("500.00")  # Cr Accum Dep
        asset.refresh_from_db()
        assert asset.accumulated_depreciation == Decimal("500.00")
        assert asset.net_book_value == Decimal("59500.00")

    def test_post_month_idempotent(self, asset):
        DepreciationService.post_month(asset, period_start=date(2026, 2, 1))
        DepreciationService.post_month(asset, period_start=date(2026, 2, 1))
        assert DepreciationSchedule.objects.filter(asset=asset, status="posted").count() == 1
        assert asset.accumulated_depreciation == Decimal("500.00")

    def test_fully_depreciated_flags_asset(self, asset):
        """After 120 months the asset is fully depreciated but still in use."""
        # Post all 120 months.
        DepreciationService.build_schedule(asset)
        for row in DepreciationSchedule.objects.filter(asset=asset, status="pending"):
            DepreciationService.post_month(asset, period_start=row.period_start)
        asset.refresh_from_db()
        assert asset.accumulated_depreciation == Decimal("60000.00")
        assert asset.status == AssetStatus.FULLY_DEPRECIATED
        last = DepreciationSchedule.objects.filter(asset=asset).order_by("-period_start").first()
        assert last.is_still_in_use is True


class TestDisposal:
    def test_gain_disposal(self, asset, asset_accounts):
        """Sell for more than NBV after some depreciation -> gain (9.3)."""
        DepreciationService.post_month(asset, period_start=date(2026, 2, 1))
        asset.refresh_from_db()
        dis = DisposalService.dispose(
            asset=asset, disposal_date=date(2026, 3, 15),
            proceeds="60000.00", reason="Sold",
        )
        assert dis.status == "posted"
        je = dis.journal_entry
        assert je.is_balanced
        lines = {l.line_no: l for l in je.lines.all()}
        # Dr Cash 60,000 + Dr Accum 500 | Cr Asset 60,000 + Cr Gain 500
        assert lines[1].debit == Decimal("60000.00")
        assert lines[2].debit == Decimal("500.00")
        assert lines[3].credit == Decimal("60000.00")
        assert lines[4].credit == Decimal("500.00")  # gain
        asset.refresh_from_db()
        assert asset.status == AssetStatus.DISPOSED

    def test_loss_disposal(self, asset, asset_accounts):
        """Sell below NBV -> loss leg (9.3 alt)."""
        DepreciationService.post_month(asset, period_start=date(2026, 2, 1))
        asset.refresh_from_db()
        dis = DisposalService.dispose(
            asset=asset, disposal_date=date(2026, 3, 15),
            proceeds="50000.00", reason="Scrapped",
        )
        je = dis.journal_entry
        assert je.is_balanced
        lines = {l.line_no: l for l in je.lines.all()}
        # Dr Cash 50,000 + Dr Accum 500 | Cr Asset 60,000 + Dr Loss 9,500
        assert lines[1].debit == Decimal("50000.00")
        assert lines[2].debit == Decimal("500.00")
        assert lines[3].credit == Decimal("60000.00")
        assert lines[4].debit == Decimal("9500.00")  # loss is a debit (9.3)
        assert dis.gain == Decimal("-9500.00")
        asset.refresh_from_db()
        assert asset.status == AssetStatus.DISPOSED
