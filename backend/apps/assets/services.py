"""Fixed Assets services (BUILD-PLAN Phase 7, POSTING_RULES §9).

  - AssetService.acquire      : Dr Asset 17xxx-19xxx | Cr AP/Cash/Loans (9.1)
  - DepreciationService       : straight-line monthly rows; Dr 50110/51173/616xx
                                | Cr Accum Dep (9.2)
  - DisposalService.dispose   : Dr Cash + Dr Accum Dep | Cr Asset + Cr Gain
                                (or Dr Loss), POSTING_RULES 9.3.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from apps.core.exceptions import ValidationError
from apps.core.money import money
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService

from .models import Asset, AssetDisposal, AssetStatus, DepreciationSchedule

# Segment -> funding/credit account defaults for acquisition (9.1):
# AP (200xx), Cash (100xx), Loans (270xx).
SEGMENT_AP = {"DHPP": "20000", "DMIE": "20003", "OPS": "20006"}
SEGMENT_CASH = {"DHPP": "10010", "DMIE": "10013", "OPS": "10016"}
SEGMENT_LOANS = {"DHPP": "27000", "DMIE": "27003", "OPS": "27006"}
# Gain on disposal (9.3) per segment.
SEGMENT_GAIN = {"DHPP": "43070", "DMIE": "43083", "OPS": "43096"}
# Loss on disposal — 9.3 "Or: 6xxx Other Expense". Default per segment.
SEGMENT_LOSS = {"DHPP": "62000", "DMIE": "62003", "OPS": "62003"}


def _account(code: str):
    from apps.foundation.models import Account

    try:
        return Account.objects.get(code=code)
    except Account.DoesNotExist as exc:
        raise ValidationError(f"COA account {code} not found.") from exc


def _segment_account(map_: dict, segment) -> object:
    code = map_.get(segment.code)
    if not code:
        raise ValidationError(f"Segment {segment.code} has no account mapping.")
    return _account(code)


class AssetService:
    """Acquires fixed assets and posts the acquisition JE (POSTING_RULES 9.1)."""

    @classmethod
    @transaction.atomic
    def acquire(
        cls,
        *,
        asset_no: str,
        name: str,
        category,
        segment,
        acquisition_date: date,
        cost,
        residual_value: Decimal = Decimal("0.00"),
        asset_account=None,
        depreciation_expense_account=None,
        accumulated_dep_account=None,
        funding_source: str = "cash",  # ap / cash / loan
        financed_loan_reference: str = "",
        acquisition_fees: Decimal = Decimal("0.00"),
        vehicle=None,
        user=None,
    ) -> Asset:
        cost = money(cost)
        fees = money(acquisition_fees)
        residual = money(residual_value)
        if cost <= 0:
            raise ValidationError("Asset cost must be positive.")
        if residual >= cost:
            raise ValidationError("Residual value must be less than cost.")

        asset = Asset.objects.create(
            asset_no=asset_no,
            name=name,
            category=category,
            segment=segment,
            acquisition_date=acquisition_date,
            cost=cost,
            residual_value=residual,
            asset_account=asset_account or category.asset_account,
            depreciation_expense_account=depreciation_expense_account
            or category.depreciation_expense_account,
            accumulated_dep_account=accumulated_dep_account
            or category.accumulated_dep_account,
            funding_source=funding_source,
            financed_loan_reference=financed_loan_reference,
            acquisition_fees=fees,
            status=AssetStatus.ACTIVE,
            vehicle=vehicle,
            created_by=user,
        )

        # 9.1 JE: Dr Asset {cost + fees} | Cr funding source.
        total = cost + fees
        credit_account = {
            "ap": _segment_account(SEGMENT_AP, segment),
            "cash": _segment_account(SEGMENT_CASH, segment),
            "loan": _segment_account(SEGMENT_LOANS, segment),
        }.get(funding_source)
        if credit_account is None:
            raise ValidationError(f"Unknown funding source '{funding_source}'.")

        entry = JournalEntry.objects.create(
            entry_no=asset_no,
            company=segment.company,
            segment=segment,
            transaction_date=acquisition_date,
            status=PostingStatus.DRAFT,
            description=f"Asset acquisition {asset_no} {name}",
            source_doc_type="ASSET",
            source_doc_no=asset_no,
            created_by=user,
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=1, account=asset.asset_account, debit=total,
            description=f"Acquisition of {name}",
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=2, account=credit_account, credit=total,
            description=f"Funded by {funding_source}",
        )
        entry.recalc_totals()
        PostingService.post(entry, user=user)
        asset.acquisition_journal = entry
        asset.save(update_fields=["acquisition_journal", "updated_at"])
        return asset


class DepreciationService:
    """Straight-line monthly depreciation (POSTING_RULES §9.2).

    Generates the lifetime schedule (month rows) and posts a single month's
    JE on demand: Dr depreciation_expense_account | Cr accumulated_dep_account.
    """

    @classmethod
    def build_schedule(cls, asset: Asset, *, as_of: date | None = None) -> list[DepreciationSchedule]:
        """Create (idempotently) the monthly rows from acquisition through
        either the as-of month or end of useful life."""
        months = asset.category.useful_life_years * 12
        amount = asset.monthly_depreciation
        if amount <= 0:
            raise ValidationError("Asset has no depreciable base.")

        end = as_of or asset.acquisition_date.replace(
            day=1, year=asset.acquisition_date.year + asset.category.useful_life_years
        )
        rows = []
        created = set(
            DepreciationSchedule.objects.filter(asset=asset).values_list("period_start", flat=True)
        )
        start = asset.acquisition_date.replace(day=1)
        count = 0
        while start <= end and count < months:
            if start not in created:
                rows.append(
                    DepreciationSchedule(
                        asset=asset,
                        period_start=start,
                        period_end=_month_end(start),
                        amount=amount,
                        status="pending",
                    )
                )
            start = _next_month(start)
            count += 1
        if rows:
            DepreciationSchedule.objects.bulk_create(rows)
        return list(asset.depreciation_schedule.order_by("period_start"))

    @classmethod
    @transaction.atomic
    def post_month(cls, asset: Asset, *, period_start: date, user=None) -> DepreciationSchedule:
        """Post one month's depreciation JE (idempotent per schedule row)."""
        row, _ = DepreciationSchedule.objects.get_or_create(
            asset=asset,
            period_start=period_start.replace(day=1),
            defaults={
                "period_end": _month_end(period_start.replace(day=1)),
                "amount": asset.monthly_depreciation,
                "status": "pending",
            },
        )
        if row.status == "posted":
            return row
        if asset.is_fully_depreciated:
            row.status = "posted"
            row.is_still_in_use = True
            row.save(update_fields=["status", "is_still_in_use", "updated_at"])
            asset.status = AssetStatus.FULLY_DEPRECIATED
            asset.save(update_fields=["status", "updated_at"])
            return row

        entry = JournalEntry.objects.create(
            entry_no=f"DEP-{asset.asset_no}-{period_start.strftime('%Y%m')}",
            company=asset.segment.company,
            segment=asset.segment,
            transaction_date=_month_end(period_start.replace(day=1)),
            status=PostingStatus.DRAFT,
            description=f"Depreciation {asset.name} {period_start.strftime('%Y-%m')}",
            source_doc_type="DEP",
            source_doc_no=asset.asset_no,
            created_by=user,
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=1, account=asset.depreciation_expense_account,
            debit=row.amount, description=f"Depreciation {asset.name}",
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=2, account=asset.accumulated_dep_account,
            credit=row.amount, description=f"Accumulated depreciation {asset.name}",
        )
        entry.recalc_totals()
        PostingService.post(entry, user=user)
        row.journal_entry = entry
        row.status = "posted"
        row.save(update_fields=["journal_entry", "status", "updated_at"])

        if asset.is_fully_depreciated:
            asset.status = AssetStatus.FULLY_DEPRECIATED
            asset.save(update_fields=["status", "updated_at"])
        return row


class DisposalService:
    """Asset disposal (POSTING_RULES §9.3).

        Dr Cash (proceeds) + Dr Accum Dep {accum} |
            Cr Asset {cost} + Cr Gain 43070-96 {gain}
    If proceeds < net book value the gain line becomes a Dr loss instead.
    """

    @classmethod
    @transaction.atomic
    def dispose(
        cls,
        *,
        asset: Asset,
        disposal_date: date,
        proceeds: Decimal,
        reason: str = "",
        cash_account=None,
        loss_account=None,
        user=None,
    ) -> AssetDisposal:
        proceeds = money(proceeds)
        accum = asset.accumulated_depreciation
        nbv = asset.cost - accum
        gain = proceeds - nbv
        loss = -gain if gain < 0 else Decimal("0.00")
        gain = gain if gain > 0 else Decimal("0.00")

        disposal = AssetDisposal.objects.create(
            asset=asset,
            disposal_date=disposal_date,
            proceeds=proceeds,
            reason=reason,
            gain=gain if gain else -loss,
            status="draft",
            created_by=user,
        )

        entry = JournalEntry.objects.create(
            entry_no=f"DIS-{asset.asset_no}-{disposal.id}",
            company=asset.segment.company,
            segment=asset.segment,
            transaction_date=disposal_date,
            status=PostingStatus.DRAFT,
            description=f"Disposal {asset.asset_no} {asset.name}",
            source_doc_type="DISPOSAL",
            source_doc_no=asset.asset_no,
            created_by=user,
        )
        line_no = 1
        if proceeds > 0:
            JournalEntryLine.objects.create(
                entry=entry, line_no=line_no,
                account=cash_account or _segment_account(SEGMENT_CASH, asset.segment),
                debit=proceeds, description=f"Disposal proceeds {asset.name}",
            )
            line_no += 1
        if accum > 0:
            JournalEntryLine.objects.create(
                entry=entry, line_no=line_no,
                account=asset.accumulated_dep_account, debit=accum,
                description=f"Accumulated depreciation cleared",
            )
            line_no += 1
        JournalEntryLine.objects.create(
            entry=entry, line_no=line_no,
            account=asset.asset_account, credit=asset.cost,
            description=f"Asset {asset.asset_no} removed",
        )
        line_no += 1
        if loss > 0:
            JournalEntryLine.objects.create(
                entry=entry, line_no=line_no,
                account=loss_account or _account(SEGMENT_LOSS.get(asset.segment.code, "62000")),
                debit=loss, description=f"Loss on disposal {asset.name}",
            )
        elif gain > 0:
            JournalEntryLine.objects.create(
                entry=entry, line_no=line_no,
                account=_segment_account(SEGMENT_GAIN, asset.segment), credit=gain,
                description=f"Gain on disposal {asset.name}",
            )
        entry.recalc_totals()
        PostingService.post(entry, user=user)
        disposal.journal_entry = entry
        disposal.status = "posted"
        disposal.save(update_fields=["journal_entry", "status", "updated_at"])
        asset.status = AssetStatus.DISPOSED
        asset.save(update_fields=["status", "updated_at"])
        return disposal


def _month_end(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)
