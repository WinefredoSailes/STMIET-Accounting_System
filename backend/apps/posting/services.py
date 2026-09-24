"""PostingService: validate, balance-check, post, and publish.

Invariants enforced here are the heart of the system (ADR-002/004/005):

1. Drafts can be edited; POSTED entries are frozen — a posted entry cannot be
   modified or deleted, only reversed with a matching reversing entry.
2. Debits == credits is REQUIRED. No force-balancing: UnbalancedEntryError
   carries the difference for human reconciliation.
3. Money is always Decimal(2dp) via apps.core.money.money().
4. Posting is atomic: the entry + lines + GL projection commit or fail
   together, inside one transaction.
5. Approval gate: entries above the JE_APPROVAL_THRESHOLD need a second
   approval before POSTED (ADR-033 workflow).
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import PostingError, UnbalancedEntryError
from apps.core.money import approve_threshold, money

from .models import (
    GeneralLedger,
    JournalEntry,
    JournalEntryLine,
    PostingRule,
    PostingRuleLine,
    PostingStatus,
    ReversalRequest,
)


def entry_source_doc(entry):
    """The business document that owns a JournalEntry, or None for a manual JE.

    Source-document entries are driven by their own module's approval flow
    (CV/RFP/Transfer/PCF/AR/Billing) — never through the generic JE editor,
    the JE approval workflow, or the JE API. Returns
    ``{"label", "detail", "pk"}`` or None.
    """
    # (reverse accessor, label, detail url name) — checked in priority order.
    checks = (
        ("cv", "Check Voucher", "ui:cv_detail"),
        ("rfps", "RFP", "ui:rfp_detail"),
        ("billing_documents", "Billing", "ui:billing_detail"),
        ("transfers", "Inter-Account Transfer", "ui:transfer_detail"),
        ("pcf_replenishments", "PCF Voucher", "ui:pcf_replenishment_detail"),
        ("ar_receipts", "Acknowledgment Receipt", "ui:receipt_detail"),
        ("ar_deposits", "Bank Deposit", "ui:receipt_list"),
    )
    for accessor, label, detail in checks:
        manager = getattr(entry, accessor, None)
        if manager is None:
            continue
        doc = manager.first()
        if doc is not None:
            return {"label": label, "detail": detail, "pk": doc.id}
    return None


class PostingService:
    """Stateless engine; all state lives on the models or in the caller."""

    # ------------------------------------------------------------------ crea

    @classmethod
    def create_rule_entry(
        cls,
        *,
        rule_code: str,
        company,
        segment,
        transaction_date,
        description,
        amount: Decimal,
        source_doc_type: str = "",
        source_doc_no: str = "",
        entry_no: str = "",
        fiscal_period=None,
        user=None,
    ) -> JournalEntry:
        """Build a draft JE from a PostingRule + amount (ADR-004, ADR-018).

        Line amount resolution, in order of precedence:
        1. fixed_amount (absolute value, e.g. the 20,000 advances leg);
        2. share * total (distribution legs, e.g. payroll by event);
        3. use_balance — takes the remainder so the entry balances by
           construction. At most one balance line per side: the Dr balance
           line makes debits sum to `total`: the Cr balance line makes
           credits sum to `total` minus its fixed/share legs (the canonical
           RFP formula Dr TOTAL | Cr advances | Cr AP remainder).
        """
        try:
            rule = PostingRule.objects.get(code=rule_code, is_active=True)
        except PostingRule.DoesNotExist as exc:
            raise PostingError(f"Posting rule '{rule_code}' not found.") from exc

        total = money(amount)
        rule_lines = list(rule.lines.order_by("line_no"))

        with transaction.atomic():
            je = JournalEntry(
                entry_no=entry_no or "(unassigned)",
                company=company,
                segment=segment,
                transaction_date=transaction_date,
                description=description,
                source_doc_type=source_doc_type,
                source_doc_no=source_doc_no,
                fiscal_period=fiscal_period,
                created_by=user,
            )
            je.save()

            # Two passes: fixed/share legs first so balance legs can absorb
            # the remainder per side. Precedence: fixed > balance > share.
            per_side = {"debit": Decimal("0.00"), "credit": Decimal("0.00")}
            amounts = {}
            for i, rl in enumerate(rule_lines, start=1):
                if rl.fixed_amount > 0:
                    amounts[i] = money(rl.fixed_amount)
                elif rl.use_balance:
                    continue  # balance leg; resolved in pass 2
                elif rl.share > 0:
                    amounts[i] = money(total * rl.share)
                else:
                    raise PostingError(f"Rule line {rl.line_no} on {rule.code} has no amount source.")
                per_side[rl.side] += amounts[i]
            for i, rl in enumerate(rule_lines, start=1):
                if i in amounts:
                    continue
                if not rl.use_balance:
                    continue
                amounts[i] = money(total - per_side[rl.side])
                if amounts[i] < 0:
                    raise PostingError(
                        f"Rule line {rl.line_no} on {rule.code} went negative "
                        f"({amounts[i]}); fixed/share legs exceed the amount."
                    )

            for i, rl in enumerate(rule_lines, start=1):
                kwargs = {rl.side: amounts[i]}
                JournalEntryLine.objects.create(
                    entry=je,
                    line_no=i,
                    account=_resolve_account(rl.account_code),
                    segment=segment,
                    description=rl.description or description,
                    **kwargs,
                )
            je.recalc_totals()
        return je

    # ------------------------------------------------------------------ pos

    @classmethod
    def post(cls, entry: JournalEntry, *, approver=None, user=None) -> JournalEntry:
        """Validate + post an entry atomically (immutability gate included)."""
        if entry.is_posted:
            raise PostingError(f"Entry {entry.entry_no} is already posted.")

        # Rule 2: no force-balance.
        debit_total = sum(money(l.debit) for l in entry.lines.all())
        credit_total = sum(money(l.credit) for l in entry.lines.all())
        if debit_total != credit_total:
            diff = debit_total - credit_total
            raise UnbalancedEntryError(
                f"Entry {entry.entry_no} is out of balance by {money(diff)} "
                f"(Dr {debit_total} vs Cr {credit_total}). No auto-adjust is performed."
            )

        # Rule 5: approval gate (ADR-033).
        threshold = approve_threshold()
        if debit_total > threshold and entry.status != PostingStatus.APPROVED:
            raise PostingError(
                f"Entry {entry.entry_no} exceeds the approval threshold "
                f"({threshold}); it must be APPROVED before posting."
            )

        with transaction.atomic():
            entry.status = PostingStatus.POSTED
            entry.total_debit = debit_total
            entry.total_credit = credit_total
            entry.updated_by = user
            entry.save(update_fields=["status", "total_debit", "total_credit", "updated_by", "updated_at"])

            # Rule 4: build GL projection inside the same transaction. One row
            # per JE line (line is a OneToOneField) — update_or_create keeps the
            # projection idempotent so re-posting or a concurrent approval can
            # never violate the unique line_id constraint.
            _lines = list(entry.lines.all().select_related("account", "segment"))
            for line in _lines:
                GeneralLedger.objects.update_or_create(
                    line=line,
                    defaults=dict(
                        entry=entry,
                        account=line.account,
                        company=entry.company,
                        segment=line.segment or entry.segment,
                        fiscal_period=entry.fiscal_period,
                        transaction_date=entry.transaction_date,
                        debit=line.debit,
                        credit=line.credit,
                    ),
                )

        _log_je(entry, "posted", actor=approver or user)
        return entry

    # ------------------------------------------------------------------ rev

    @classmethod
    def reverse(
        cls,
        entry: JournalEntry,
        *,
        reason: str,
        user=None,
        reversal_date: date | None = None,
    ) -> JournalEntry:
        """Create the reversing entry: exact mirror, posted to the CURRENT OPEN
        cycle (next cycle only when it is locked), linked by reversal_token.

        Correcting the books in the open period is what keeps the cycle-based
        ledger (ADR-013) netting to zero without restating a locked period.
        The original is marked REVERSED; its GL rows remain and both entries are
        summed by the GL readers so the pair nets to zero (ADR-004/005).
        """
        if not entry.is_posted:
            raise PostingError("Only posted entries can be reversed.")

        rev_date = cls._reversal_date(entry, reversal_date)

        with transaction.atomic():
            token = f"REV:{entry.entry_no}:{entry.id}"
            rev = JournalEntry.objects.create(
                entry_no=f"REV-{entry.entry_no}",
                company=entry.company,
                segment=entry.segment,
                fiscal_period=entry.fiscal_period,
                transaction_date=rev_date,
                status=PostingStatus.POSTED,
                description=f"Reversal of {entry.entry_no}: {reason}",
                source_doc_type=entry.source_doc_type,
                source_doc_no=entry.source_doc_no,
                reversal_token=token,
                created_by=user,
            )
            for line in entry.lines.all():
                JournalEntryLine.objects.create(
                    entry=rev,
                    line_no=line.line_no,
                    account=line.account,
                    segment=line.segment or entry.segment,
                    description=f"REV of {entry.entry_no}: {line.description}",
                    debit=line.credit,
                    credit=line.debit,
                )
            rev.recalc_totals()
            entry.reversal_token = token
            entry.status = PostingStatus.REVERSED
            entry.updated_by = user
            entry.save(update_fields=["reversal_token", "status", "updated_by", "updated_at"])

            # GL projection for the reversing entry (same idempotent pattern
            # as post()).
            for line in rev.lines.all().select_related("account", "segment"):
                GeneralLedger.objects.update_or_create(
                    line=line,
                    defaults=dict(
                        entry=rev,
                        account=line.account,
                        company=rev.company,
                        segment=line.segment or rev.segment,
                        fiscal_period=rev.fiscal_period,
                        transaction_date=rev.transaction_date,
                        debit=line.debit,
                        credit=line.credit,
                    ),
                )
            _log_je(rev, "posted", actor=user)
        return rev

    @staticmethod
    def _reversal_date(entry: JournalEntry, requested: date | None = None) -> date:
        """Reversal posts to the current open cycle; if today's cycle for the
        entry's segment is locked, advance to the first day of the next cycle."""
        from apps.cash.models import WeeklyCashCycle
        from apps.foundation.calendar import cycle_range_for

        target = requested or date.today()
        start, _end = cycle_range_for(target, company=entry.company)
        cycle = (
            WeeklyCashCycle.objects.filter(segment=entry.segment, cycle_start=start)
            .only("status", "cycle_end")
            .first()
        )
        if cycle and cycle.status == "locked":
            return cycle.cycle_end + timedelta(days=1)
        return target


def _resolve_account(code: str):
    from apps.foundation.models import Account

    try:
        return Account.objects.get(code=code, is_postable=True)
    except Account.DoesNotExist as exc:
        raise PostingError(f"Account {code} missing or not postable.") from exc


def _log_je(entry: JournalEntry, action: str, *, actor=None, note: str = "") -> None:
    """Audit-trail entry for a JournalEntry (DocType.JE, never mixed with RFP)."""
    from apps.ap.models import ActionLog

    ActionLog.objects.create(
        doc_type=ActionLog.DocType.JE,
        doc_id=entry.id,
        action=action,
        actor=actor,
        note=(note or "").strip(),
    )


def mark_source_reversed(request: ReversalRequest) -> None:
    """Propagate an approved reversal to its source document + derived data.

    Recompute contract (ADR-004/013):
      - GL balance readers sum POSTED + REVERSED, so the pair nets to zero.
      - Document ledgers exclude reversed documents (a reversed RFP / receipt is
        not a live document) — PO billed, AR invoice paid, AP/supplier ledger.
      - The open cash cycle the reversal landed in is regenerated; locked
        cycles are never restated.
    """
    entry = request.entry
    rev = request.reversal_entry
    if rev is None:
        return

    src = (entry.source_doc_type or "").upper()

    # AR: re-open the invoice a reversed collection receipt was applied to.
    if src == "AR" and entry.source_doc_no:
        from apps.ar.models import AcknowledgmentReceipt
        from apps.ar.services import _refresh_invoice_status

        receipt = (
            AcknowledgmentReceipt.objects.filter(receipt_no=entry.source_doc_no)
            .select_related("applied_to")
            .first()
        )
        if receipt and receipt.applied_to_id:
            _refresh_invoice_status(receipt.applied_to)

    # Cash cycle: reflect the reversal in the cycle it posted to (open only).
    _regenerate_open_cycle(entry.segment, rev.transaction_date, entry.company)


def _regenerate_open_cycle(segment, when, company) -> None:
    from apps.cash.models import WeeklyCashCycle
    from apps.cash.services import CashCycleService
    from apps.foundation.calendar import cycle_range_for

    start, _end = cycle_range_for(when, company=company)
    cycle = WeeklyCashCycle.objects.filter(segment=segment, cycle_start=start).first()
    if cycle and cycle.status == "open":
        CashCycleService.generate_cycle(segment, start)


class ReversalService:
    """Maker-checker reversal workflow for posted journal entries (ADR-004).

    Any accounting user requests a reversal with a reason; the entry stays
    POSTED and in the GL. Only the Accounting & Finance Head approves (which
    posts the mirror entry and propagates to the source document) or rejects
    (with a note). Posted entries are never deleted or edited.
    """

    @classmethod
    @transaction.atomic
    def request(
        cls, entry: JournalEntry, *, reason: str, user=None
    ) -> ReversalRequest:
        if not entry.is_posted:
            raise PostingError("Only posted entries can be reversed.")
        if entry.reversal_token:
            raise PostingError("This entry has already been reversed.")
        if not (reason or "").strip():
            raise PostingError("A reversal reason is required.")
        if entry.reversal_requests.filter(status=ReversalRequest.Status.REQUESTED).exists():
            raise PostingError("A reversal request is already pending for this entry.")
        req = ReversalRequest.objects.create(
            entry=entry,
            source_doc_type=entry.source_doc_type or "",
            source_doc_no=entry.source_doc_no or "",
            reason=reason.strip(),
            status=ReversalRequest.Status.REQUESTED,
            requested_by=user,
            requested_at=timezone.now(),
        )
        _log_je(entry, "reversal_requested", actor=user, note=reason)
        return req

    @classmethod
    @transaction.atomic
    def approve(cls, request: ReversalRequest, *, user=None) -> ReversalRequest:
        from apps.core.approvals import require_approval_role

        require_approval_role(user, "head")
        if request.status != ReversalRequest.Status.REQUESTED:
            raise PostingError("Only a requested reversal can be approved.")
        # Self-approval is allowed for the Head: the role gate above means the
        # Head is the only one who can ever reach this line, and blocking them
        # from approving their own request would leave it permanently stuck
        # (nobody outranks the Head). The audit trail logs requester and
        # approver separately, so the double role is visible on the entry.

        entry = request.entry
        rev = PostingService.reverse(entry, reason=request.reason, user=user)
        request.status = ReversalRequest.Status.APPROVED
        request.approved_by = user
        request.approved_at = timezone.now()
        request.reversal_entry = rev
        request.save(
            update_fields=[
                "status", "approved_by", "approved_at", "reversal_entry", "updated_at",
            ]
        )
        mark_source_reversed(request)
        _log_je(entry, "reversal_approved", actor=user, note=request.reason)
        return request

    @classmethod
    @transaction.atomic
    def reject(
        cls, request: ReversalRequest, *, user=None, note: str = ""
    ) -> ReversalRequest:
        from apps.core.approvals import require_approval_role

        require_approval_role(user, "head")
        if request.status != ReversalRequest.Status.REQUESTED:
            raise PostingError("Only a requested reversal can be rejected.")
        if not (note or "").strip():
            raise PostingError("A rejection note is required.")
        request.status = ReversalRequest.Status.REJECTED
        request.rejected_by = user
        request.rejected_at = timezone.now()
        request.reject_note = note.strip()
        request.save(
            update_fields=["status", "rejected_by", "rejected_at", "reject_note", "updated_at"]
        )
        _log_je(request.entry, "reversal_rejected", actor=user, note=note)
        return request

    @classmethod
    def pending(cls):
        return (
            ReversalRequest.objects.filter(status=ReversalRequest.Status.REQUESTED)
            .select_related("entry")
        )

    @classmethod
    def pending_count(cls) -> int:
        return cls.pending().count()