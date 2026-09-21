"""AR services: collection lifecycle, bank deposits, cycle ledger, aging.

AR receipt lifecycle (draft -> submitted -> posted):
  draft     staff builds the Account Distribution (Dr segment Cash on Hand |
            user credit lines). No JE exists yet.
  submitted awaiting the Accounting & Finance Head (ADR-033 gate).
  posted    the Head approves; the collection JE is built from the receipt
            lines and posted to the GL.

The Head then records a Bank Deposit covering one or more posted receipts:
  Dr Cash in Bank (bank_account) | Cr segment Cash on Hand
This supersedes ADR-016 ("deposit = state change, NO JE") — moving cash from
on-hand to a bank account is a real transfer between cash accounts.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import AccountingError, ValidationError
from apps.core.money import money
from apps.foundation.calendar import cycle_range_for
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService

from .models import (
    AcknowledgmentReceipt,
    AcknowledgmentReceiptLine,
    ARInvoice,
    Customer,
    Deposit,
    PaymentMethod,
    ReceiptStatus,
)

# Segment -> (Unearned account, AR-Other account, AR-Fuel account)
SEGMENT_ACCOUNTS = {
    "DHPP": ("21000", "12020", "12030"),
    "DMIE": ("21023", "12023", "12023"),
    "OPS": ("21016", "12026", "12026"),
}

# Segment -> canonical Cash on Hand GL code (ADR-003/016). Resolved against the
# COA (and SegmentAccountMap when seeded); never assumed to exist.
SEGMENT_CASH_ON_HAND = {
    "DHPP": "10010",
    "DMIE": "10013",
    "OPS": "10016",
}


def _account_code(*codes: str) -> str:
    """Resolve the first code that exists in the COA (segment fallbacks)."""
    from apps.foundation.models import Account

    for code in codes:
        if code and Account.objects.filter(code=code).exists():
            return code
    raise ValidationError(f"No COA account found for any of {codes}.")


def _account_object(code: str):
    from apps.foundation.models import Account

    return Account.objects.get(code=code)


def cash_on_hand_account(segment):
    """The segment's Cash on Hand COA account (auto debit for AR receipts).

    Resolution order: explicit SegmentAccountMap role 'cash' -> canonical
    per-segment code -> any of the known COH codes. Fails loudly when the COA
    has no Cash on Hand account, because the collection JE cannot be built.
    """
    from apps.foundation.models import Account, SegmentAccountMap

    try:
        from apps.foundation.models import resolve_segment_account

        return resolve_segment_account(segment, SegmentAccountMap.ROLE_CASH)
    except ValidationError:
        pass

    candidates = [SEGMENT_CASH_ON_HAND.get(segment.code), "10010", "10013", "10016"]
    for code in candidates:
        if code:
            account = Account.objects.filter(code=code).first()
            if account is not None:
                return account
    raise ValidationError(
        f"Segment {segment.code} has no Cash on Hand account configured in the COA."
    )


def _fiscal_period_for(transaction_date):
    from apps.foundation.models import FiscalPeriod

    return FiscalPeriod.objects.filter(
        start_date__lte=transaction_date, end_date__gte=transaction_date
    ).first()


def _log(doc, action, *, actor=None, note=""):
    """Append to the shared append-only audit trail (ActionLog)."""
    try:
        from apps.ap.services import log_action

        log_action(doc, action, actor=actor, note=note)
    except Exception:  # audit logging must never break the business action
        pass


def _normalize_lines(lines):
    """Validate/normalize prepared line dicts into money-clean rows."""
    out = []
    for i, line in enumerate(lines, start=1):
        account = line["account"]
        segment = line.get("segment")
        if segment is None:
            raise ValidationError(f"Line {i}: a segment is required.")
        debit = money(line.get("debit") or 0)
        credit = money(line.get("credit") or 0)
        if debit < 0 or credit < 0:
            raise ValidationError(f"Line {i}: amounts cannot be negative.")
        if debit and credit:
            raise ValidationError(
                f"Line {i}: enter the amount in only one of Debit or Credit."
            )
        if not debit and not credit:
            continue
        out.append(
            {
                "account": account,
                "segment": segment,
                "cost_center": (line.get("cost_center") or "")[:64],
                "description": (line.get("description") or "")[:500],
                "debit": debit,
                "credit": credit,
            }
        )
    if not out:
        raise ValidationError("Add at least one line with an amount.")
    return out


def _default_lines(*, customer, segment, amount, cash_account, applied_to, receipt_label):
    """Legacy single-amount collection -> two lines (Dr COH | Cr Unearned/AR)."""
    unearned, ar_other, ar_fuel = SEGMENT_ACCOUNTS[segment.code]
    credit_code = _account_code(ar_other, ar_fuel) if applied_to else _account_code(unearned)
    credit_desc = (
        f"Applied to {applied_to.invoice_no}" if applied_to else "Unearned revenue"
    )
    return [
        {
            "account": cash_account,
            "segment": segment,
            "cost_center": "",
            "description": f"Collection {receipt_label}",
            "debit": amount,
            "credit": Decimal("0.00"),
        },
        {
            "account": _account_object(credit_code),
            "segment": applied_to.segment if applied_to else segment,
            "cost_center": "",
            "description": credit_desc,
            "debit": Decimal("0.00"),
            "credit": amount,
        },
    ]


class CollectionService:
    """Owns the AR receipt lifecycle and the `cash.collection` posting event."""

    # ------------------------------------------------------------------ create

    @classmethod
    def create_receipt(
        cls,
        *,
        customer: Customer,
        transaction_date: date,
        amount=None,
        cash_account=None,
        payment_method: str = PaymentMethod.CASH,
        check_no: str = "",
        transaction_no: str = "",
        ref_po_no: str = "",
        segment=None,
        applied_to: ARInvoice | None = None,
        lines=None,
        receipt_no: str | None = None,
        attachment=None,
        created_by=None,
    ) -> AcknowledgmentReceipt:
        """Create a DRAFT AR receipt + its account-distribution lines.

        ``lines`` (list of dicts with account/segment/debit/credit) is the new
        columnar path. When omitted, the legacy single-``amount`` collection is
        converted into Dr Cash on Hand | Cr Unearned (or Cr AR when applied).
        No journal entry is posted here — that happens on Head approval.
        """
        seg = segment or customer.segment
        if applied_to is not None and applied_to.customer_id != customer.id:
            raise ValidationError("Applied invoice belongs to a different customer.")
        if applied_to is not None and applied_to.balance <= 0:
            raise ValidationError(f"Invoice {applied_to.invoice_no} is fully paid.")

        cash_account = cash_account or cash_on_hand_account(seg)

        if lines is None:
            amount = money(amount)
            if amount <= 0:
                raise ValidationError("Collection amount must be positive.")
            generated = receipt_no or cls._next_receipt_no(customer, transaction_date)
            norm_lines = _default_lines(
                customer=customer,
                segment=seg,
                amount=amount,
                cash_account=cash_account,
                applied_to=applied_to,
                receipt_label=generated,
            )
        else:
            norm_lines = _normalize_lines(lines)

        debit_total = sum((l["debit"] for l in norm_lines), Decimal("0.00"))
        credit_total = sum((l["credit"] for l in norm_lines), Decimal("0.00"))
        if debit_total <= 0:
            raise ValidationError("The account distribution total must be positive.")
        if debit_total != credit_total:
            raise ValidationError(
                f"Account distribution is out of balance by "
                f"{money(debit_total - credit_total)} (Dr {debit_total} vs Cr {credit_total})."
            )

        if receipt_no is None:
            receipt_no = cls._next_receipt_no(customer, transaction_date)

        with transaction.atomic():
            receipt = AcknowledgmentReceipt.objects.create(
                receipt_no=receipt_no,
                customer=customer,
                transaction_date=transaction_date,
                amount=debit_total,
                payment_method=payment_method,
                cash_account=cash_account,
                check_no=check_no,
                transaction_no=transaction_no,
                ref_po_no=ref_po_no,
                collected_by=created_by,
                created_by=created_by,
                segment=seg,
                applied_to=applied_to,
                status=ReceiptStatus.DRAFT,
            )
            for i, line in enumerate(norm_lines, start=1):
                AcknowledgmentReceiptLine.objects.create(
                    receipt=receipt,
                    line_no=i,
                    account=line["account"],
                    segment=line["segment"],
                    cost_center=line["cost_center"],
                    description=line["description"],
                    debit=line["debit"],
                    credit=line["credit"],
                )
            if attachment:
                receipt.attachment = attachment
                receipt.save(update_fields=["attachment", "updated_at"])
            receipt.recalc_totals()
            _log(receipt, "created", actor=created_by)

        return receipt

    @staticmethod
    def _next_receipt_no(customer, transaction_date):
        from apps.sequences.models import DocumentSequence

        return DocumentSequence.next_number(
            company=customer.segment.company,
            form_code="AR",
            year=transaction_date.year,
            pattern="AR-{YYYY}-{SEQ:05d}",
        )

    # ------------------------------------------------------------------ edit

    @classmethod
    def update_draft(
        cls,
        *,
        receipt: AcknowledgmentReceipt,
        lines,
        cash_account=None,
        payment_method: str | None = None,
        check_no: str | None = None,
        transaction_no: str | None = None,
        ref_po_no: str | None = None,
        transaction_date: date | None = None,
        applied_to=None,
        attachment=None,
        user=None,
    ) -> AcknowledgmentReceipt:
        """Replace a DRAFT receipt's lines/header (immutability gate)."""
        if receipt.status != ReceiptStatus.DRAFT:
            raise ValidationError("Only draft receipts can be edited.")
        norm_lines = _normalize_lines(lines)
        debit_total = sum((l["debit"] for l in norm_lines), Decimal("0.00"))
        credit_total = sum((l["credit"] for l in norm_lines), Decimal("0.00"))
        if debit_total != credit_total:
            raise ValidationError(
                f"Account distribution is out of balance by "
                f"{money(debit_total - credit_total)}."
            )
        with transaction.atomic():
            receipt.lines.all().delete()
            for i, line in enumerate(norm_lines, start=1):
                AcknowledgmentReceiptLine.objects.create(
                    receipt=receipt,
                    line_no=i,
                    account=line["account"],
                    segment=line["segment"],
                    cost_center=line["cost_center"],
                    description=line["description"],
                    debit=line["debit"],
                    credit=line["credit"],
                )
            if cash_account is not None:
                receipt.cash_account = cash_account
            if payment_method is not None:
                receipt.payment_method = payment_method
            if check_no is not None:
                receipt.check_no = check_no
            if transaction_no is not None:
                receipt.transaction_no = transaction_no
            if ref_po_no is not None:
                receipt.ref_po_no = ref_po_no
            if transaction_date is not None:
                receipt.transaction_date = transaction_date
            if applied_to is not None:
                receipt.applied_to = applied_to or None
            if attachment is not None:
                receipt.attachment = attachment
            receipt.save()
            receipt.recalc_totals()
            _log(receipt, "revised", actor=user)
        return receipt

    # ------------------------------------------------------------------ workflow

    @classmethod
    def submit(cls, receipt: AcknowledgmentReceipt, *, user=None) -> AcknowledgmentReceipt:
        """draft -> submitted (routes to the Accounting & Finance Head)."""
        if receipt.status != ReceiptStatus.DRAFT:
            raise ValidationError("Only draft receipts can be submitted.")
        if not receipt.lines.exists():
            raise ValidationError("Add at least one account-distribution line.")
        if not receipt.is_balanced:
            raise ValidationError(
                f"Receipt {receipt.receipt_no} is out of balance and cannot be submitted."
            )
        receipt.status = ReceiptStatus.SUBMITTED
        receipt.approved_by = None
        receipt.approved_at = None
        receipt.rejected_by = None
        receipt.rejected_at = None
        receipt.rejection_note = ""
        receipt.save(
            update_fields=[
                "status", "approved_by", "approved_at", "rejected_by",
                "rejected_at", "rejection_note", "updated_at",
            ]
        )
        _log(receipt, "submitted", actor=user)
        return receipt

    @classmethod
    def approve(cls, receipt: AcknowledgmentReceipt, *, user) -> AcknowledgmentReceipt:
        """Head approves a submitted receipt: post the collection JE."""
        from apps.core.approvals import require_approval_role

        require_approval_role(user, "head")
        return cls._post_receipt(receipt, user=user)

    @classmethod
    def _post_receipt(cls, receipt: AcknowledgmentReceipt, *, user) -> AcknowledgmentReceipt:
        """Build + post the collection JE for a submitted receipt (atomic)."""
        if receipt.status != ReceiptStatus.SUBMITTED:
            raise ValidationError("Only submitted receipts can be approved.")
        if not receipt.is_balanced:
            raise ValidationError(
                f"Receipt {receipt.receipt_no} is out of balance by "
                f"{money(receipt.debit_total - receipt.credit_total)}."
            )
        with transaction.atomic():
            entry = cls._build_collection_je(receipt, user=user)
            PostingService.post(entry, approver=user, user=user)
            receipt.journal_entry = entry
            receipt.status = ReceiptStatus.POSTED
            receipt.approved_by = user
            receipt.approved_at = timezone.now()
            receipt.rejected_by = None
            receipt.rejected_at = None
            receipt.rejection_note = ""
            receipt.save(
                update_fields=[
                    "journal_entry", "status", "approved_by", "approved_at",
                    "rejected_by", "rejected_at", "rejection_note", "updated_at",
                ]
            )
            _log(receipt, "approved", actor=user)
        if receipt.applied_to_id:
            _refresh_invoice_status(receipt.applied_to)
        return receipt

    @staticmethod
    def _build_collection_je(receipt, *, user) -> JournalEntry:
        entry_no = (
            receipt.receipt_no
            if receipt.receipt_no.startswith("AR-")
            else f"AR-{receipt.receipt_no}"
        )
        entry = JournalEntry.objects.create(
            entry_no=entry_no,
            company=receipt.segment.company,
            segment=receipt.segment,
            fiscal_period=_fiscal_period_for(receipt.transaction_date),
            transaction_date=receipt.transaction_date,
            status=PostingStatus.APPROVED,
            description=f"Collection {receipt.receipt_no} {receipt.customer.name}",
            source_doc_type="AR",
            source_doc_no=receipt.receipt_no,
            created_by=user,
            approved_by=user,
            approved_at=timezone.now(),
        )
        for i, line in enumerate(
            receipt.lines.select_related("account", "segment").order_by("line_no"), start=1
        ):
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
        return entry

    @classmethod
    def reject(
        cls, receipt: AcknowledgmentReceipt, *, user, note: str
    ) -> AcknowledgmentReceipt:
        """Head rejects a submitted receipt, returning it to draft."""
        from apps.core.approvals import require_approval_role

        require_approval_role(user, "head")
        if receipt.status != ReceiptStatus.SUBMITTED:
            raise ValidationError("Only submitted receipts can be rejected.")
        note = (note or "").strip()
        if not note:
            raise ValidationError("A rejection note is required.")
        receipt.status = ReceiptStatus.DRAFT
        receipt.rejected_by = user
        receipt.rejected_at = timezone.now()
        receipt.rejection_note = note
        receipt.approved_by = None
        receipt.approved_at = None
        receipt.save(
            update_fields=[
                "status", "rejected_by", "rejected_at", "rejection_note",
                "approved_by", "approved_at", "updated_at",
            ]
        )
        _log(receipt, "rejected", actor=user, note=note)
        return receipt

    # ------------------------------------------------------------------ legacy

    @classmethod
    def record_collection(
        cls,
        *,
        receipt_no: str = None,
        customer,
        transaction_date: date,
        amount,
        cash_account,
        payment_method: str = PaymentMethod.CASH,
        check_no: str = "",
        transaction_no: str = "",
        ref_po_no: str = "",
        segment=None,
        applied_to: ARInvoice | None = None,
        user=None,
    ) -> AcknowledgmentReceipt:
        """Create + immediately approve/post a collection (legacy convenience).

        Used by the demo seeder and callers that intentionally bypass the
        approval queue. The UI/API use create_receipt() + submit() + approve().
        """
        receipt = cls.create_receipt(
            customer=customer,
            transaction_date=transaction_date,
            amount=amount,
            cash_account=cash_account,
            payment_method=payment_method,
            check_no=check_no,
            transaction_no=transaction_no,
            ref_po_no=ref_po_no,
            segment=segment,
            applied_to=applied_to,
            receipt_no=receipt_no,
            created_by=user,
        )
        receipt.status = ReceiptStatus.SUBMITTED
        receipt.save(update_fields=["status", "updated_at"])
        return cls._post_receipt(receipt, user=user)


class DepositService:
    """Bank deposit covering one or more posted AR receipts (posts a real JE)."""

    @classmethod
    def record_deposit(
        cls,
        *,
        receipts,
        bank_account,
        transaction_date: date,
        reference: str = "",
        deposit_no: str | None = None,
        attachment=None,
        user=None,
    ) -> Deposit:
        from apps.sequences.models import DocumentSequence

        receipts = list(receipts)
        if not receipts:
            raise ValidationError("Select at least one posted receipt to deposit.")
        if transaction_date is None:
            raise ValidationError("Deposit date is required.")

        company = receipts[0].segment.company
        # Group the credit side by each receipt's segment Cash on Hand account.
        credits = {}
        total = Decimal("0.00")
        for receipt in receipts:
            if receipt.status != ReceiptStatus.POSTED:
                raise ValidationError(
                    f"Receipt {receipt.receipt_no} is not posted to the GL yet."
                )
            if receipt.deposit_id:
                raise ValidationError(
                    f"Receipt {receipt.receipt_no} was already deposited."
                )
            coh = cash_on_hand_account(receipt.segment)
            if coh.pk == bank_account.pk:
                raise ValidationError(
                    f"Deposit account cannot be the same as the Cash on Hand "
                    f"account {coh.code}."
                )
            credits[coh] = credits.get(coh, Decimal("0.00")) + money(receipt.amount)
            total += money(receipt.amount)
        if total <= 0:
            raise ValidationError("Deposit total must be positive.")

        if deposit_no is None:
            deposit_no = DocumentSequence.next_number(
                company=company,
                form_code="BD",
                year=transaction_date.year,
                pattern="BD-{YYYY}-{SEQ:05d}",
            )

        with transaction.atomic():
            deposit = Deposit.objects.create(
                bank_account=bank_account,
                transaction_date=transaction_date,
                deposit_no=deposit_no,
                amount=total,
                reference=reference,
                deposited_by=user,
                created_by=user,
                attachment=attachment or "",
            )
            entry = JournalEntry.objects.create(
                entry_no=deposit_no,
                company=company,
                segment=receipts[0].segment,
                fiscal_period=_fiscal_period_for(transaction_date),
                transaction_date=transaction_date,
                status=PostingStatus.APPROVED,
                description=f"Bank deposit {deposit_no}",
                source_doc_type="DEP",
                source_doc_no=deposit_no,
                created_by=user,
                approved_by=user,
                approved_at=timezone.now(),
            )
            JournalEntryLine.objects.create(
                entry=entry,
                line_no=1,
                account=bank_account,
                debit=total,
                description=f"Deposit {deposit_no}",
            )
            for i, (coh, amount) in enumerate(credits.items(), start=2):
                JournalEntryLine.objects.create(
                    entry=entry,
                    line_no=i,
                    account=coh,
                    credit=amount,
                    description=f"Deposit {deposit_no} from Cash on Hand",
                )
            entry.recalc_totals()
            PostingService.post(entry, approver=user, user=user)
            deposit.journal_entry = entry
            deposit.save(update_fields=["journal_entry", "updated_at"])
            for receipt in receipts:
                receipt.deposit = deposit
                receipt.save(update_fields=["deposit", "updated_at"])
            _log(deposit, "posted", actor=user)

        return deposit


class CycleLedgerService:
    """ADR-013 cumulative Over/(Short) customer ledger per Tue-Mon cycle.

    Derivation (never stored): for each cycle the customer's payments
    (collections) minus billings (invoices) produce over/(short), carried
    forward cumulatively like the legacy COLLECTIBLES sheet.
    """

    @classmethod
    def for_customer(cls, customer: Customer) -> list[dict]:
        """Return per-cycle entries for the customer, oldest cycle first."""
        from django.db.models import Sum

        rows = []
        receipts = (
            AcknowledgmentReceipt.objects.filter(customer=customer, journal_entry__isnull=False)
            .values("transaction_date")
            .annotate(paid=Sum("amount"))
            .order_by("transaction_date")
        )
        invoices = (
            ARInvoice.objects.filter(customer=customer)
            .values("transaction_date")
            .annotate(billed=Sum("total"))
            .order_by("transaction_date")
        )

        events = []
        company = customer.segment.company if customer.segment_id else None
        for r in receipts:
            start, _ = cycle_range_for(r["transaction_date"], company=company)
            events.append((start, "paid", r["paid"]))
        for inv in invoices:
            start, _ = cycle_range_for(inv["transaction_date"], company=company)
            events.append((start, "billed", inv["billed"]))

        events.sort(key=lambda e: (e[0], e[1]))
        cumulative = Decimal("0.00")
        seen = {}
        for start, kind, amt in events:
            bucket = seen.setdefault(start, {"paid": Decimal("0.00"), "billed": Decimal("0.00")})
            bucket[kind] += amt
        for start in sorted(seen):
            b = seen[start]
            cycle_over_short = b["paid"] - b["billed"]
            cumulative += cycle_over_short
            rows.append(
                {
                    "cycle_start": start,
                    "paid": money(b["paid"]),
                    "billed": money(b["billed"]),
                    "over_short": money(cycle_over_short),
                    "cumulative": money(cumulative),
                }
            )
        return rows

    @classmethod
    def aging(cls, as_of: date) -> list[dict]:
        """AR aging buckets 30/60/90/120+ from open invoice balances.

        Future-dated invoices are excluded because they have not entered the
        aging period yet.
        """
        buckets = {"0-30": Decimal("0.00"), "31-60": Decimal("0.00"),
                   "61-90": Decimal("0.00"), "91-120": Decimal("0.00"),
                   "120+": Decimal("0.00")}
        invoices = ARInvoice.objects.filter(
            status__in=("open", "partially_paid"),
            transaction_date__lte=as_of,
        )
        for inv in invoices:
            balance = inv.balance
            if balance <= 0:
                continue
            age_days = (as_of - inv.transaction_date).days
            key = (
                "0-30" if age_days <= 30
                else "31-60" if age_days <= 60
                else "61-90" if age_days <= 90
                else "91-120" if age_days <= 120
                else "120+"
            )
            buckets[key] += balance
        return [{"bucket": k, "amount": money(v)} for k, v in buckets.items()]


def _refresh_invoice_status(invoice: ARInvoice) -> None:
    # Recompute from live receipts; a reversed collection drops out of
    # amount_paid, so a fully reversed payment re-opens the invoice.
    if invoice.balance <= 0:
        invoice.status = "paid"
    elif invoice.amount_paid > 0:
        invoice.status = "partially_paid"
    else:
        invoice.status = "open"
    invoice.save(update_fields=["status", "updated_at"])
