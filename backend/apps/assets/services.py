"""Fixed Assets services (BUILD-PLAN Phase 7, POSTING_RULES §9).

  - AssetService        : acquisition lifecycle — the asset is created as a
                          draft carrying an Account Distribution grid
                          (AssetLine); it is submitted, approved by the
                          Accounting & Finance Head, and *posted* only then
                          (the 9.1 JE is built from the grid at post time).
  - DepreciationService : straight-line monthly rows; Dr 50110/51173/616xx
                          | Cr Accum Dep (9.2) — authorized single-step.
  - DisposalService     : Dr Cash + Dr Accum Dep | Cr Asset + Cr Gain (or Dr
                          Loss), POSTING_RULES 9.3 — authorized single-step.
  - ReversalService     : overstated-asset correction (ADR-038 §2.c).
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.ap.services import log_action, retry_on_lock
from apps.core.approvals import require_approval_role
from apps.core.exceptions import PostingError, ValidationError
from apps.core.money import money
from apps.foundation.models import SegmentAccountMap, resolve_segment_account
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService

from .models import (
    Asset,
    AssetApprovalStatus,
    AssetDisposal,
    AssetLine,
    AssetReversal,
    AssetStatus,
    DepreciationSchedule,
)

# Asset (fixed-asset) accounts live in the 16xxx-19xxx class (POSTING_RULES §9).
ASSET_ACCOUNT_PREFIXES = ("16", "17", "18", "19")


class AssetService:
    """Acquisition lifecycle: draft -> submitted -> approved -> posted.

    A new asset is created as a draft whose Account Distribution grid
    (``AssetLine``) defines the eventual acquisition JE. The preparer submits
    it; the Accounting & Finance Head approves it (reserving the linked PO's
    balance); posting builds the JE from the grid with status ``APPROVED`` and
    pushes it to the General Journal. Rejected drafts return to draft with a
    rejection note (mirrors the Billing lifecycle).
    """

    # ------------------------------------------------------------------ create

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def create_asset(
        cls,
        *,
        asset_no: str,
        name: str,
        category,
        segment,
        acquisition_date: date,
        lines: list[dict],
        residual_value: Decimal = Decimal("0.00"),
        supplier=None,
        po=None,
        reference: str = "",
        useful_life_months: int | None = None,
        vehicle=None,
        depreciation_expense_account=None,
        accumulated_dep_account=None,
        user=None,
    ) -> Asset:
        """Create a draft asset from a JE-style Account Distribution grid.

        Each line is ``{side, segment, account|account_code, amount,
        description, cost_center}``. The register ``cost`` and the cleared
        ``asset_account`` are derived from the asset-account debit lines
        (codes 16xxx-19xxx) — at least one is required. The funding source
        (AP / Cash / Loans) is derived from the credit lines for the reversal
        engine. No Journal Entry is created until the asset posts.
        """
        from apps.foundation.models import Account

        resolved = []
        for raw in lines:
            line = dict(raw)
            if "account" not in line or line["account"] is None:
                code = line.get("account_code") or ""
                line["account"] = Account.objects.filter(code=code).first()
                if line["account"] is None:
                    raise ValidationError(f"Unknown account code '{code}'.")
            resolved.append(line)
        lines = resolved

        residual = money(residual_value)
        if residual < 0:
            raise ValidationError("Residual value cannot be negative.")

        dr_total, cr_total = cls._validate_lines(lines)
        if not name.strip():
            raise ValidationError("Asset name is required.")

        asset_lines = [
            l for l in lines
            if l["side"] == "dr" and l["account"].code.startswith(ASSET_ACCOUNT_PREFIXES)
        ]
        if not asset_lines:
            raise ValidationError(
                "The account distribution needs at least one Dr line on a "
                "fixed-asset account (16xxx-19xxx) to capitalize the asset."
            )
        cost = sum((money(l["amount"]) for l in asset_lines), Decimal("0.00"))
        if residual >= cost:
            raise ValidationError("Residual value must be less than cost.")
        asset_account = asset_lines[0]["account"]

        funding_source = cls._derive_funding_source(lines)

        asset = Asset.objects.create(
            asset_no=asset_no,
            name=name.strip(),
            category=category,
            segment=segment,
            acquisition_date=acquisition_date,
            cost=cost,
            residual_value=residual,
            asset_account=asset_account,
            depreciation_expense_account=depreciation_expense_account
            or category.depreciation_expense_account,
            accumulated_dep_account=accumulated_dep_account
            or category.accumulated_dep_account,
            funding_source=funding_source,
            supplier=supplier,
            po=po,
            reference=(reference or "").strip(),
            useful_life_months=useful_life_months,
            status=AssetStatus.ACTIVE,
            approval_status=AssetApprovalStatus.DRAFT,
            vehicle=vehicle,
            created_by=user,
        )
        cls._write_lines(asset, lines)
        cls._log(asset, "created (draft)", actor=user)
        return asset

    # How many times to retry number allocation when the FA sequence lags
    # behind rows minted outside it (e.g. the opening-balance import, which
    # writes FA-YYYY-#### numbers directly). Each retry heals the counter
    # forward, so a lag of any size converges instead of 500ing per submit.
    MAX_NUMBER_RETRIES = 5

    @staticmethod
    def is_asset_no_collision(exc: BaseException) -> bool:
        """True when a DB error is a duplicate asset_no on either backend.

        PostgreSQL names the constraint
        (``assets_asset_asset_no_key``); SQLite names the column
        (``UNIQUE constraint failed: assets_asset.asset_no``).
        """
        msg = str(exc).lower()
        return "asset_no" in msg and ("unique" in msg or "duplicate" in msg)

    @classmethod
    def heal_fa_sequence(cls, *, company, year) -> int:
        """Fast-forward the FA/<year> counter past the highest existing number.

        Rows created outside the sequence (imports, seeds) leave
        ``DocumentSequence.next_seq`` behind ``max(asset_no)``; the next UI
        allocation then collides with an existing row. Healing sets the
        counter to ``max + 1`` (never backwards) and returns the new value.
        """
        from apps.sequences.models import DocumentSequence

        prefix = f"FA-{year}-"
        peak = 0
        for (asset_no,) in Asset.objects.filter(
            asset_no__startswith=prefix
        ).values_list("asset_no"):
            tail = asset_no[len(prefix):]
            if tail.isdigit():
                peak = max(peak, int(tail))
        with transaction.atomic():
            seq, _ = DocumentSequence.objects.select_for_update().get_or_create(
                company=company,
                form_code="FA",
                year=year,
                cost_center="",
                defaults={"pattern": "FA-{YYYY}-{SEQ:04d}"},
            )
            if seq.next_seq <= peak:
                seq.next_seq = peak + 1
                seq.save(update_fields=["next_seq", "updated_at"])
            return seq.next_seq

    @classmethod
    def create_asset_with_sequence(
        cls, *, company, acquisition_date: date, max_attempts: int = MAX_NUMBER_RETRIES,
        **kwargs,
    ) -> Asset:
        """Create a draft asset, allocating its FA number with self-healing.

        Each attempt allocates a fresh number (its own committed transaction,
        so concurrent submits still get distinct numbers) and inserts the
        asset. On a duplicate ``asset_no`` the counter is healed forward past
        existing rows before retrying, per the ``DocumentSequence``
        caller-retries-on-duplicate contract. ``max_attempts`` bounds the
        loop; exhaustion raises ``ValidationError`` (rendered friendly by
        callers) instead of leaking ``IntegrityError`` as a 500.
        """
        from django.db import IntegrityError

        from apps.sequences.models import DocumentSequence

        year = acquisition_date.year
        last_exc = None
        for _ in range(max(1, max_attempts)):
            asset_no = DocumentSequence.next_number(
                company=company,
                form_code="FA",
                year=year,
                pattern="FA-{YYYY}-{SEQ:04d}",
            )
            try:
                return cls.create_asset(
                    asset_no=asset_no, acquisition_date=acquisition_date, **kwargs
                )
            except IntegrityError as exc:
                if not cls.is_asset_no_collision(exc):
                    raise
                last_exc = exc
                cls.heal_fa_sequence(company=company, year=year)
        raise ValidationError(
            "Could not allocate an asset number — please try submitting again."
        ) from last_exc

    @staticmethod
    def _validate_lines(lines: list[dict]) -> tuple[Decimal, Decimal]:
        if not lines:
            raise ValidationError("Add at least one account distribution line.")
        dr_total = Decimal("0.00")
        cr_total = Decimal("0.00")
        for i, line in enumerate(lines, start=1):
            amt = money(line["amount"])
            if amt <= 0:
                raise ValidationError(f"Line {i}: amount must be greater than zero.")
            side = str(line.get("side") or "dr").lower()
            if side not in ("dr", "cr"):
                raise ValidationError(f"Line {i}: side must be Dr or Cr, got '{side}'.")
            if side == "dr":
                dr_total += amt
            else:
                cr_total += amt
        if dr_total <= 0:
            raise ValidationError("The account distribution needs at least one Dr line.")
        if dr_total != cr_total:
            raise ValidationError(
                f"Account distribution does not balance: Dr {dr_total} vs Cr {cr_total} "
                "— the posted entry must balance."
            )
        return dr_total, cr_total

    @staticmethod
    def _derive_funding_source(lines: list[dict]) -> str:
        """AP when any credit leg lands on a liability (2xxxx) account, Loans
        for the loans payable class (27xxx), else Cash. Mirrors the reversal
        engine's expectation of an AP / Cash / Loans funding source."""
        for line in lines:
            if line["side"] != "cr":
                continue
            code = line["account"].code
            if code.startswith("27"):
                return "loan"
            if code.startswith("2"):
                return "ap"
        return "cash"

    @staticmethod
    def _write_lines(asset: Asset, lines: list[dict]) -> None:
        rows = []
        for i, line in enumerate(lines, start=1):
            amt = money(line["amount"])
            side = str(line.get("side") or "dr").lower()
            account = line["account"]
            rows.append(
                AssetLine(
                    asset=asset,
                    line_no=i,
                    side=side,
                    segment=line["segment"],
                    account=account,
                    cost_center=(str(line.get("cost_center") or ""))[:64],
                    description=(str(line.get("description") or ""))[:500],
                    debit=amt if side == "dr" else Decimal("0.00"),
                    credit=amt if side == "cr" else Decimal("0.00"),
                )
            )
        AssetLine.objects.bulk_create(rows)

    # ------------------------------------------------------------- lifecycle

    @classmethod
    @transaction.atomic
    def submit(cls, asset: Asset, *, user) -> Asset:
        """draft -> submitted (the preparer sends it for head approval)."""
        if asset.approval_status != AssetApprovalStatus.DRAFT:
            raise ValidationError(
                f"Asset {asset.asset_no} can only be submitted from draft "
                f"(status '{asset.approval_status}')."
            )
        if not asset.lines.exists():
            raise ValidationError("The asset has no account distribution lines.")
        asset.approval_status = AssetApprovalStatus.SUBMITTED
        asset.rejected_by = None
        asset.rejected_at = None
        asset.rejection_note = ""
        asset.save(
            update_fields=[
                "approval_status", "rejected_by", "rejected_at",
                "rejection_note", "updated_at",
            ]
        )
        cls._log(asset, "submitted", actor=user)
        return asset

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def approve(cls, asset: Asset, *, user) -> Asset:
        """submitted -> approved (Accounting & Finance Head sign-off).

        Reserves the linked PO's balance under a lock so concurrent approvals
        cannot over-commit the same PO."""
        require_approval_role(user, "head")
        if asset.approval_status != AssetApprovalStatus.SUBMITTED:
            raise ValidationError(
                f"Asset {asset.asset_no} can only be approved from submitted "
                f"(status '{asset.approval_status}')."
            )
        cls._guard_po_balance(asset)
        asset.approval_status = AssetApprovalStatus.APPROVED
        asset.approved_by = user
        asset.approved_at = timezone.now()
        asset.rejected_by = None
        asset.rejected_at = None
        asset.rejection_note = ""
        asset.save(
            update_fields=[
                "approval_status", "approved_by", "approved_at",
                "rejected_by", "rejected_at", "rejection_note", "updated_at",
            ]
        )
        cls._log(asset, "approved", actor=user)
        return asset

    @classmethod
    @transaction.atomic
    def reject(cls, asset: Asset, *, user, note: str = "") -> Asset:
        """submitted -> draft with a rejection note (head only)."""
        require_approval_role(user, "head")
        if asset.approval_status != AssetApprovalStatus.SUBMITTED:
            raise ValidationError("Only submitted assets can be rejected.")
        note = (note or "").strip()
        if not note:
            raise ValidationError("A rejection note is required.")
        asset.approval_status = AssetApprovalStatus.DRAFT
        asset.rejected_by = user
        asset.rejected_at = timezone.now()
        asset.rejection_note = note
        asset.approved_by = None
        asset.approved_at = None
        asset.save(
            update_fields=[
                "approval_status", "rejected_by", "rejected_at", "rejection_note",
                "approved_by", "approved_at", "updated_at",
            ]
        )
        cls._log(asset, "rejected", actor=user, note=note)
        return asset

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def post(cls, asset: Asset, *, user) -> JournalEntry:
        """approved -> posted: build and post the acquisition Journal Entry.

        The JE is built exactly from the Account Distribution grid as entered;
        it carries the supplier / PO / reference metadata on the header so the
        General Journal shows the counterparty. The entry is created with
        status APPROVED (the Head already approved this acquisition) and then
        pushed to the GL."""
        require_approval_role(user, "head")
        if asset.approval_status != AssetApprovalStatus.APPROVED:
            raise ValidationError(
                f"Asset {asset.asset_no} must be approved before posting "
                f"(status '{asset.approval_status}')."
            )
        if asset.acquisition_journal_id:
            raise PostingError(f"Asset {asset.asset_no} is already posted.")
        cls._guard_po_balance(asset)

        from apps.foundation.models import FiscalPeriod

        period = FiscalPeriod.objects.filter(
            start_date__lte=asset.acquisition_date, end_date__gte=asset.acquisition_date
        ).first()
        description = (
            f"Asset acquisition {asset.asset_no} {asset.name}"
            + (f" — PO {asset.po.po_number}" if asset.po_id else "")
        ).strip()
        entry = JournalEntry.objects.create(
            entry_no=asset.asset_no,
            company=asset.segment.company,
            segment=asset.segment,
            fiscal_period=period,
            transaction_date=asset.acquisition_date,
            status=PostingStatus.APPROVED,
            description=description[:500],
            source_doc_type="ASSET",
            source_doc_no=asset.asset_no,
            supplier_name=asset.supplier.name if asset.supplier_id else "",
            po=asset.po.po_number if asset.po_id else "",
            ref_number=(asset.reference or "")[:128],
            created_by=user,
        )
        for i, line in enumerate(asset.lines.order_by("line_no"), start=1):
            JournalEntryLine.objects.create(
                entry=entry,
                line_no=i,
                account=line.account,
                segment=line.segment,
                description=line.description,
                cost_center=line.cost_center,
                debit=line.debit,
                credit=line.credit,
            )
        entry.recalc_totals()
        PostingService.post(entry, user=user)

        asset.acquisition_journal = entry
        asset.approval_status = AssetApprovalStatus.POSTED
        asset.save(update_fields=["acquisition_journal", "approval_status", "updated_at"])
        cls._log(asset, "posted", actor=user)
        return entry

    @staticmethod
    def _guard_po_balance(asset: Asset) -> None:
        """Confirm, under a PO row lock, that the linked PO still has room for
        this acquisition's full JE debit total (excludes the asset itself).
        Called at approval (where the balance is reserved) and at posting."""
        if not asset.po_id:
            return
        from apps.ap.models import PurchaseOrder

        try:
            po = PurchaseOrder.objects.select_for_update().get(pk=asset.po_id)
        except PurchaseOrder.DoesNotExist:
            return
        drawn = Decimal("0.00")
        for a in po.assets.select_for_update().all():
            if a.id == asset.id:
                continue
            if a.approval_status in (
                AssetApprovalStatus.APPROVED, AssetApprovalStatus.POSTED
            ):
                drawn += a.acquisition_amount
        amount = asset.acquisition_amount
        if amount > po.amount - drawn:
            raise ValidationError(
                f"PO {po.po_number} no longer holds enough balance for asset "
                f"{asset.asset_no}: {po.amount - drawn} remaining."
            )

    @staticmethod
    def _log(asset: Asset, action: str, *, actor=None, note: str = "") -> None:
        """Audit-trail entry tagged as a Fixed Asset document."""
        from apps.ap.models import ActionLog

        log_action(asset, action, actor=actor, note=note, doc_type=ActionLog.DocType.ASSET)

    @classmethod
    @transaction.atomic
    def seed_opening(
        cls, *, asset_no, name, category, segment, acquisition_date,
        cost, accumulated_dep, asset_account, depreciation_expense_account,
        accumulated_dep_account, funding_source="cash", user=None,
    ) -> Asset:
        """Seed one asset at company opening (Sept 1, 2026 snapshot).

        Unlike `acquire` (which credits a real funding source in the present),
        an opening-balance asset is brought onto the register with a single
        balanced opening JE that reflects the net book position:

            Dr  {asset_account}                 = cost
            Cr  {accumulated_dep_account}       = accumulated_dep   (to-date)
            Cr  {opening_equity}                = net book value

        The plug equity is resolved data-driven via SegmentAccountMap
        ROLE_OPENING_EQUITY (never hardcoded). A posted DepreciationSchedule
        row carries the to-date accumulated depreciation so the register's
        NBV ties to the workbook; future accruals restart the month after the
        snapshot via the normal DepreciationService.
        """
        from apps.foundation.models import SegmentAccountMap, resolve_segment_account
        from apps.posting.models import JournalEntryLine

        cost = money(cost)
        accum = money(accumulated_dep)
        if cost <= 0:
            raise ValidationError("Asset cost must be positive.")
        if accum < 0 or accum > cost:
            raise ValidationError("Accumulated depreciation must be 0..cost.")
        nbv = cost - accum

        asset = Asset.objects.create(
            asset_no=asset_no,
            name=name,
            category=category,
            segment=segment,
            acquisition_date=acquisition_date,
            cost=cost,
            residual_value=Decimal("0.00"),
            asset_account=asset_account,
            depreciation_expense_account=depreciation_expense_account,
            accumulated_dep_account=accumulated_dep_account,
            funding_source=funding_source,
            status=AssetStatus.ACTIVE,
            created_by=user,
        )

        equity = resolve_segment_account(segment, SegmentAccountMap.ROLE_OPENING_EQUITY)
        entry = JournalEntry.objects.create(
            entry_no=asset_no,
            company=segment.company,
            segment=segment,
            transaction_date=acquisition_date,
            status=PostingStatus.DRAFT,
            description=f"Opening balance {asset_no} {name}",
            source_doc_type="OPENING_ASSET",
            source_doc_no=asset_no,
            created_by=user,
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=1, account=asset.asset_account, debit=cost,
            description=f"Opening asset cost {name}",
        )
        if accum > 0:
            JournalEntryLine.objects.create(
                entry=entry, line_no=2, account=asset.accumulated_dep_account,
                credit=accum, description=f"Accumulated depreciation to date {name}",
            )
        JournalEntryLine.objects.create(
            entry=entry, line_no=3, account=equity, credit=nbv,
            description=f"Opening equity plug (net book value) {name}",
        )
        entry.recalc_totals()
        # Opening-balance seeding is an authorised migration operation (like
        # month-end close): the plug JE legitimately exceeds the discretionary
        # posting threshold, so it is approved before posting.
        entry.status = PostingStatus.APPROVED
        entry.save(update_fields=["status", "updated_at"])
        PostingService.post(entry, user=user)
        asset.acquisition_journal = entry
        asset.save(update_fields=["acquisition_journal", "updated_at"])

        # To-date accumulated depreciation as a posted schedule row (ND: this
        # carries the full catch-up; the .accumulated_depreciation aggregate
        # therefore equals the workbook figure and NBV ties out).
        DepreciationSchedule.objects.get_or_create(
            asset=asset,
            period_start=acquisition_date.replace(day=1),
            defaults={
                "period_end": _month_end(acquisition_date.replace(day=1)),
                "amount": accum,
                "journal_entry": entry,
                "status": "posted",
                "is_still_in_use": True,
            },
        )
        return asset

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
        """Authorized programmatic acquisition (import / seed tooling).

        Builds the simple funding grid (Dr Asset cost+fees | Cr funding
        source) behind the same validation as the UI draft, but books the
        asset directly as ``POSTED`` (there is no head approval step in a
        one-shot import). The 9.1 JE is created with status APPROVED — an
        authorized operation like the opening-balance seeding — so bulk
        imports are not blocked by the discretionary posting threshold.
        Interactive users and the API must use the draft lifecycle
        (``create_asset`` -> ``submit`` -> ``approve`` -> ``post``).
        """
        from apps.foundation.models import resolve_segment_account

        cost = money(cost)
        fees = money(acquisition_fees)
        residual = money(residual_value)
        if cost <= 0:
            raise ValidationError("Asset cost must be positive.")
        if residual >= cost:
            raise ValidationError("Residual value must be less than cost.")

        total = cost + fees
        fund_role = {
            "ap": SegmentAccountMap.ROLE_AP,
            "cash": SegmentAccountMap.ROLE_CASH,
            "loan": SegmentAccountMap.ROLE_LOANS,
        }
        role = fund_role.get(funding_source)
        if role is None:
            raise ValidationError(f"Unknown funding source '{funding_source}'.")
        credit_account = resolve_segment_account(segment, role)
        asset_account_obj = asset_account or category.asset_account

        lines = [
            {"side": "dr", "segment": segment, "account_code": asset_account_obj.code,
             "amount": total, "description": f"Acquisition of {name}"},
            {"side": "cr", "segment": segment, "account_code": credit_account.code,
             "amount": total, "description": f"Funded by {funding_source}"},
        ]
        asset = cls.create_asset(
            asset_no=asset_no, name=name, category=category, segment=segment,
            acquisition_date=acquisition_date, lines=lines,
            residual_value=residual, reference=financed_loan_reference,
            vehicle=vehicle,
            depreciation_expense_account=depreciation_expense_account,
            accumulated_dep_account=accumulated_dep_account,
            user=user,
        )
        asset.approval_status = AssetApprovalStatus.POSTED
        asset.acquisition_fees = fees
        asset.financed_loan_reference = financed_loan_reference
        asset.save()

        entry = JournalEntry.objects.create(
            entry_no=asset_no,
            company=segment.company,
            segment=segment,
            transaction_date=acquisition_date,
            status=PostingStatus.APPROVED,
            description=f"Asset acquisition {asset_no} {name}",
            source_doc_type="ASSET",
            source_doc_no=asset_no,
            supplier_name="",
            po="",
            ref_number=(financed_loan_reference or "")[:128],
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
        months = asset.useful_life_in_months
        amount = asset.monthly_depreciation
        if amount <= 0:
            raise ValidationError("Asset has no depreciable base.")

        if as_of is not None:
            end = as_of.replace(day=1)
        else:
            end = _add_months(asset.acquisition_date.replace(day=1), months - 1)
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
        if asset.approval_status != AssetApprovalStatus.POSTED:
            raise ValidationError(
                f"Asset {asset.asset_no} is not posted — depreciation cannot "
                "accrue on a draft or unapproved acquisition."
            )
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
            status=PostingStatus.APPROVED,
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

    @classmethod
    @transaction.atomic
    def post_all(cls, *, period_start: date, user=None) -> dict:
        """Month-end batch (ADR-038): post the period's depreciation JE for
        every active asset. Idempotent — months already posted are skipped.

        Returns a summary {"period_start", "posted": [asset_no...],
        "skipped": [asset_no...]} so callers (UI view / management command /
        month-end close) can report what actually moved.
        """
        period_start = period_start.replace(day=1)
        already_posted = set(
            DepreciationSchedule.objects.filter(
                period_start=period_start, journal_entry__isnull=False
            ).values_list("asset_id", flat=True)
        )
        posted, skipped = [], []
        for asset in Asset.objects.filter(status=AssetStatus.ACTIVE).order_by("asset_no"):
            row = cls.post_month(asset, period_start=period_start, user=user)
            if row.journal_entry_id and asset.id not in already_posted:
                posted.append(asset.asset_no)
            else:
                skipped.append(asset.asset_no)
        return {"period_start": period_start, "posted": posted, "skipped": skipped}


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
        if asset.approval_status != AssetApprovalStatus.POSTED:
            raise ValidationError(
                f"Asset {asset.asset_no} is not posted — only a posted asset "
                "may be disposed."
            )
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
            status=PostingStatus.APPROVED,
            description=f"Disposal {asset.asset_no} {asset.name}",
            source_doc_type="DISPOSAL",
            source_doc_no=asset.asset_no,
            created_by=user,
        )
        line_no = 1
        if proceeds > 0:
            JournalEntryLine.objects.create(
                entry=entry, line_no=line_no,
                account=cash_account or resolve_segment_account(asset.segment, SegmentAccountMap.ROLE_CASH),
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
                account=loss_account or resolve_segment_account(asset.segment, SegmentAccountMap.ROLE_DISPOSAL_LOSS),
                debit=loss, description=f"Loss on disposal {asset.name}",
            )
        elif gain > 0:
            JournalEntryLine.objects.create(
                entry=entry, line_no=line_no,
                account=resolve_segment_account(asset.segment, SegmentAccountMap.ROLE_DISPOSAL_GAIN), credit=gain,
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


class ReversalService:
    """Overstated-asset reversal (ADR-038 §2.c).

    Mirrors the acquisition funding source for the overstated amount at the
    reversal date:

        Dr {funding source} {amount}   |   Cr {asset account} {amount}

    then reduces the asset's booked cost so future depreciation accrues on the
    corrected base. Prospective only — prior-period depreciation is never
    restated, and each reversal carries its own JE (audit trail separate from
    depreciation entries).
    """

    @classmethod
    @transaction.atomic
    def reverse(
        cls,
        *,
        asset: Asset,
        reversal_date: date,
        amount: Decimal,
        reason: str = "",
        funding_account=None,
        user=None,
    ) -> AssetReversal:
        amount = money(amount)
        if asset.approval_status != AssetApprovalStatus.POSTED:
            raise ValidationError(
                f"Asset {asset.asset_no} is not posted — only a posted asset "
                "may be reversed."
            )
        if amount <= 0:
            raise ValidationError("Reversal amount must be positive.")
        if amount > asset.cost:
            raise ValidationError("Reversal amount cannot exceed the asset's booked cost.")
        if asset.status == AssetStatus.DISPOSED:
            raise ValidationError("A disposed asset cannot be reversed.")

        fund_role = {
            "ap": SegmentAccountMap.ROLE_AP,
            "cash": SegmentAccountMap.ROLE_CASH,
            "loan": SegmentAccountMap.ROLE_LOANS,
        }
        try:
            debit_account = funding_account or resolve_segment_account(
                asset.segment, fund_role[asset.funding_source]
            )
        except KeyError:
            raise ValidationError(f"Unknown funding source '{asset.funding_source}'.")

        entry = JournalEntry.objects.create(
            entry_no=(f"REV-{asset.asset_no}-{reversal_date.strftime('%Y%m')}"
                      f"-{asset.reversals.count() + 1}"),
            company=asset.segment.company,
            segment=asset.segment,
            transaction_date=reversal_date,
            status=PostingStatus.APPROVED,
            description=f"Overstated asset reversal {asset.asset_no} {asset.name}",
            source_doc_type="ASSET_REVERSAL",
            source_doc_no=asset.asset_no,
            created_by=user,
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=1, account=debit_account, debit=amount,
            description=f"Reverse overstated funding {asset.name}",
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=2, account=asset.asset_account, credit=amount,
            description=f"Reduce overstated cost {asset.name}",
        )
        entry.recalc_totals()
        PostingService.post(entry, user=user)

        asset.cost -= amount
        asset.save(update_fields=["cost", "updated_at"])

        # Prospective: recompute unposted future schedule rows on the corrected
        # monthly base; posted (past) rows are left untouched.
        month = reversal_date.replace(day=1)
        new_monthly = asset.monthly_depreciation
        pending_ids = list(
            asset.depreciation_schedule.filter(
                status="pending", period_start__gte=month
            ).values_list("id", flat=True)
        )
        if pending_ids:
            DepreciationSchedule.objects.filter(id__in=pending_ids).update(amount=new_monthly)

        reversal = AssetReversal.objects.create(
            asset=asset,
            reversal_date=reversal_date,
            amount=amount,
            reason=reason,
            journal_entry=entry,
            status="posted",
            created_by=user,
        )
        return reversal


def _month_end(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _add_months(d: date, months: int) -> date:
    """Calendar-accurate month arithmetic (end-of-month safe)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)
