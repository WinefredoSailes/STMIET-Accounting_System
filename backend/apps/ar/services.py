"""AR services: collection lifecycle, business invoices, bank deposits, ledgers.

AR receipt lifecycle (draft -> submitted -> posted):
  draft     staff builds the Account Distribution (Dr segment Cash on Hand |
            user credit lines). No JE exists yet.
  submitted awaiting the Accounting & Finance Head (ADR-033 gate).
  posted    the Head approves; the collection JE is built from the receipt
            lines and posted to the GL.

AR invoice (SI) lifecycle mirrors the receipt gate (see InvoiceService):
  draft -> submitted -> posted; the Head's approval posts the revenue JE
  (Dr Unearned | Cr Sales for paid-on-delivery, Dr AR | Cr Sales for credit).

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
    ARInvoiceLine,
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

# Segment -> Sales (Revenue) GL code, the Cr side of the SI revenue JE
# (POSTING_RULES §12 B-phase resolution). Resolved against the COA like
# SEGMENT_ACCOUNTS; never assumed to exist.
SEGMENT_SALES_ACCOUNTS = {
    "DHPP": "40000",
    "DMIE": "41003",
    "OPS": "42006",
}

# Segment -> canonical Cash on Hand GL code (ADR-003/016). Resolved against the
# COA (and SegmentAccountMap when seeded); never assumed to exist.
SEGMENT_CASH_ON_HAND = {
    "DHPP": "10010",
    "DMIE": "10013",
    "OPS": "10016",
}

_APPLIED_UNSET = object()  # update_draft sentinel: "leave applied_to as-is"


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


def segment_ar_account(segment):
    """The segment's Accounts-Receivable COA account (credit side of an
    applied collection), or None when the COA has no AR account configured.

    Mirrors ``_default_lines``' credit resolution (``_account_code`` over the
    segment's other/fuel AR codes) so the UI's applied-to guard uses the exact
    account the legacy auto-post would have credited."""
    entry = SEGMENT_ACCOUNTS.get(segment.code)
    if not entry:
        return None
    _, ar_other, ar_fuel = entry
    from apps.foundation.models import Account

    for code in (ar_other, ar_fuel):
        account = Account.objects.filter(code=code).first() if code else None
        if account is not None:
            return account
    return None


def segment_unearned_account(segment):
    """The segment's Unearned revenue COA account (Debit side of a paid-on-
    delivery SI posting — an advance collection is converted into revenue),
    or None when the COA has no unearned account configured."""
    entry = SEGMENT_ACCOUNTS.get(segment.code)
    if not entry:
        return None
    from apps.foundation.models import Account

    return Account.objects.filter(code=entry[0]).first()


def segment_sales_account(segment):
    """The segment's Sales/Revenue COA account (Credit side of the SI revenue
    JE, POSTING_RULES §12), or None when the COA has no sales account mapped."""
    code = SEGMENT_SALES_ACCOUNTS.get(segment.code)
    if not code:
        return None
    from apps.foundation.models import Account

    return Account.objects.filter(code=code).first()


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


def _check_applied_within_balance(applied_to, norm_lines):
    """Credits aimed at the applied invoice's AR account must not exceed its
    outstanding balance (over-application would leave a phantom prepayment
    hidden inside a "paid" invoice — the AR subledger must stay truthful).
    Matches any configured AR code so segment-mapped variants (other/fuel)
    are all caught."""
    if applied_to is None:
        return
    ar_codes = {code for entry in SEGMENT_ACCOUNTS.values() for code in entry[1:]}
    applied_amt = sum(
        (
            l["credit"]
            for l in norm_lines
            if getattr(l["account"], "code", None) in ar_codes
        ),
        Decimal("0.00"),
    )
    if applied_amt > applied_to.balance:
        raise ValidationError(
            f"Applying {money(applied_amt)} exceeds the outstanding balance "
            f"{money(applied_to.balance)} of invoice {applied_to.invoice_no}."
        )


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
        if segment is None:
            raise ValidationError("A segment is required for a receipt.")
        seg = segment
        if applied_to is not None and applied_to.customer_id != customer.id:
            raise ValidationError("Applied invoice belongs to a different customer.")
        if applied_to is not None and applied_to.balance <= 0:
            raise ValidationError(f"Invoice {applied_to.invoice_no} is fully paid.")

        cash_account = cash_account or cash_on_hand_account(seg)

        if lines is None:
            amount = money(amount)
            if amount <= 0:
                raise ValidationError("Collection amount must be positive.")
            generated = receipt_no or cls._next_receipt_no(seg, transaction_date)
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

        _check_applied_within_balance(applied_to, norm_lines)

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
            receipt_no = cls._next_receipt_no(seg, transaction_date)

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
    def _next_receipt_no(segment, transaction_date):
        from apps.sequences.models import DocumentSequence

        return DocumentSequence.next_number(
            company=segment.company,
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
        segment=None,
        applied_to=_APPLIED_UNSET,
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
        if applied_to is not _APPLIED_UNSET and applied_to is not None:
            if applied_to.customer_id != receipt.customer_id:
                raise ValidationError("Applied invoice belongs to a different customer.")
            if applied_to.balance <= 0:
                raise ValidationError(f"Invoice {applied_to.invoice_no} is fully paid.")
        _check_applied_within_balance(
            receipt.applied_to if applied_to is _APPLIED_UNSET else applied_to,
            norm_lines,
        )
        with transaction.atomic():
            saved_fields = []
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
                saved_fields.append("cash_account")
            if payment_method is not None:
                receipt.payment_method = payment_method
                saved_fields.append("payment_method")
            if check_no is not None:
                receipt.check_no = check_no
                saved_fields.append("check_no")
            if transaction_no is not None:
                receipt.transaction_no = transaction_no
                saved_fields.append("transaction_no")
            if ref_po_no is not None:
                receipt.ref_po_no = ref_po_no
                saved_fields.append("ref_po_no")
            if transaction_date is not None:
                receipt.transaction_date = transaction_date
                saved_fields.append("transaction_date")
            if applied_to is not _APPLIED_UNSET:
                receipt.applied_to = applied_to
                saved_fields.append("applied_to")
            if attachment is not None:
                receipt.attachment = attachment
                saved_fields.append("attachment")
            if segment is not None:
                receipt.segment = segment
                saved_fields.append("segment")
            receipt.save(update_fields=saved_fields or ["amount"])
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
        rows = []
        seen = {}
        receipts = (
            AcknowledgmentReceipt.objects.filter(customer=customer, journal_entry__isnull=False)
            .select_related("segment")
        )
        for r in receipts:
            start, _ = cycle_range_for(r.transaction_date, company=r.segment.company)
            bucket = seen.setdefault(start, {"paid": Decimal("0.00"), "billed": Decimal("0.00")})
            bucket["paid"] += r.amount
        invoices = ARInvoice.objects.filter(customer=customer).select_related("segment")
        for inv in invoices:
            start, _ = cycle_range_for(inv.transaction_date, company=inv.segment.company)
            bucket = seen.setdefault(start, {"paid": Decimal("0.00"), "billed": Decimal("0.00")})
            bucket["billed"] += inv.total

        cumulative = Decimal("0.00")
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
    if invoice.status in ("draft", "submitted"):
        # Not posted yet — payments are never applied to a draft/submitted SI.
        return
    if invoice.balance <= 0:
        invoice.status = "paid"
    elif invoice.amount_paid > 0:
        invoice.status = "partially_paid"
    else:
        invoice.status = "open"
    invoice.save(update_fields=["status", "updated_at"])


class InvoiceService:
    """Owns the Sales Invoice (SI) lifecycle and its revenue posting event.

    Lifecycle (ADR-033 gate, mirroring AR receipts):
      draft     staff builds header + line items. No JE exists yet.
      submitted awaiting the Accounting & Finance Head approval.
      posted    the Head approves; the revenue JE is built and posted to GL.

    Posting paths (POSTING_RULES §12, B-phase resolution):
      - paid on delivery: Dr Unearned (segment 210xx) | Cr Sales (segment 4xxxx)
      - unpaid (credit):  Dr AR (segment 120xx)      | Cr Sales (segment 4xxxx)

    Paid-on-delivery approval first checks the customer's available advance
    (unearned collections not yet consumed by a posted POD invoice) — the
    delivery cannot be booked into revenue beyond the advance on hand.
    """

    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_POSTED = "posted"

    # ------------------------------------------------------------------ create

    @classmethod
    def create_invoice(
        cls,
        *,
        customer,
        transaction_date: date,
        segment,
        is_paid_on_delivery: bool,
        lines,
        invoice_no: str | None = None,
        created_by=None,
    ) -> ARInvoice:
        """Create a DRAFT invoice + its line items. No JE is posted here —
        that happens when the Head approves the submitted invoice.
        """
        if segment is None:
            raise ValidationError("A segment is required for an invoice.")
        norm_lines = cls._normalize_lines(lines)
        total = sum((line["amount"] for line in norm_lines), Decimal("0.00"))
        if total <= 0:
            raise ValidationError("Invoice total must be positive.")
        if invoice_no is None:
            invoice_no = cls._next_invoice_no(segment, transaction_date)

        with transaction.atomic():
            invoice = ARInvoice.objects.create(
                invoice_no=invoice_no,
                customer=customer,
                transaction_date=transaction_date,
                segment=segment,
                total=total,
                is_paid_on_delivery=bool(is_paid_on_delivery),
                status=cls.STATUS_DRAFT,
                created_by=created_by,
            )
            for i, line in enumerate(norm_lines, start=1):
                ARInvoiceLine.objects.create(
                    invoice=invoice,
                    line_no=i,
                    product_code=line["product_code"],
                    description=line.get("description", ""),
                    quantity=line["quantity"],
                    unit_price=line["unit_price"],
                    amount=line["amount"],
                )
            _log(invoice, "created", actor=created_by)
        return invoice

    @staticmethod
    def _next_invoice_no(segment, transaction_date: date) -> str:
        from apps.sequences.models import DocumentSequence

        return DocumentSequence.next_number(
            company=segment.company,
            form_code="SI",
            year=transaction_date.year,
            pattern="SI-{YYYY}-{SEQ:05d}",
        )

    @staticmethod
    def _normalize_lines(lines):
        """Validate/normalize invoice line dicts: money-clean quantity/unit
        price with the line amount recomputed as qty x unit price."""
        if not lines:
            raise ValidationError("Add at least one line item.")
        out = []
        for i, line in enumerate(lines, start=1):
            product_code = (line.get("product_code") or "").strip()
            if not product_code:
                raise ValidationError(f"Line {i}: product code is required.")
            quantity = money(line.get("quantity") or 0)
            if quantity <= 0:
                raise ValidationError(f"Line {i}: quantity must be positive.")
            unit_price = money(line.get("unit_price") or 0)
            if unit_price <= 0:
                raise ValidationError(f"Line {i}: unit price must be positive.")
            out.append(
                {
                    "product_code": product_code[:32],
                    "description": (line.get("description") or "").strip()[:255],
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "amount": money(quantity * unit_price),
                }
            )
        return out

    # ------------------------------------------------------------------ edit

    @classmethod
    def update_draft(
        cls,
        *,
        invoice: ARInvoice,
        transaction_date: date | None = None,
        segment=None,
        is_paid_on_delivery: bool | None = None,
        lines=None,
        user=None,
    ) -> ARInvoice:
        """Replace a DRAFT invoice's header/lines (immutability gate)."""
        if invoice.status != cls.STATUS_DRAFT:
            raise ValidationError("Only draft invoices can be edited.")
        with transaction.atomic():
            saved = []
            if transaction_date is not None:
                invoice.transaction_date = transaction_date
                saved.append("transaction_date")
            if segment is not None:
                invoice.segment = segment
                saved.append("segment")
            if is_paid_on_delivery is not None:
                invoice.is_paid_on_delivery = bool(is_paid_on_delivery)
                saved.append("is_paid_on_delivery")
            if lines is not None:
                norm_lines = cls._normalize_lines(lines)
                invoice.lines.all().delete()
                for i, line in enumerate(norm_lines, start=1):
                    ARInvoiceLine.objects.create(
                        invoice=invoice,
                        line_no=i,
                        product_code=line["product_code"],
                        description=line.get("description", ""),
                        quantity=line["quantity"],
                        unit_price=line["unit_price"],
                        amount=line["amount"],
                    )
                invoice.total = sum((line["amount"] for line in norm_lines), Decimal("0.00"))
                saved.append("total")
            if saved:
                invoice.save(update_fields=[*saved, "updated_at"])
            _log(invoice, "revised", actor=user)
        return invoice

    # ------------------------------------------------------------------ submit

    @classmethod
    def submit(cls, invoice: ARInvoice, *, user=None) -> ARInvoice:
        if invoice.status != cls.STATUS_DRAFT:
            raise ValidationError("Only draft invoices can be submitted.")
        if not invoice.lines.exists():
            raise ValidationError("Add at least one line item before submitting.")
        if invoice.total <= 0:
            raise ValidationError("Invoice total must be positive.")
        invoice.status = cls.STATUS_SUBMITTED
        invoice.approved_by = None
        invoice.approved_at = None
        invoice.rejected_by = None
        invoice.rejected_at = None
        invoice.rejection_note = ""
        invoice.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "rejected_by",
                "rejected_at",
                "rejection_note",
                "updated_at",
            ]
        )
        _log(invoice, "submitted", actor=user)
        return invoice

    # ------------------------------------------------------------------ approve

    @classmethod
    def approve(cls, invoice: ARInvoice, *, user) -> ARInvoice:
        from apps.core.approvals import require_approval_role

        require_approval_role(user, "head")
        if invoice.status != cls.STATUS_SUBMITTED:
            raise ValidationError("Only submitted invoices can be approved.")
        if invoice.is_paid_on_delivery:
            available = cls.available_unearned(invoice.customer)
            if available < invoice.total:
                raise ValidationError(
                    f"Customer advance of only ₱{money(available)} covers this "
                    f"₱{money(invoice.total)} delivery — record the collection first."
                )
        return cls._post_invoice(invoice, user=user)

    @staticmethod
    def available_unearned(customer) -> Decimal:
        """Unearned advance available to consume: posted un-applied collections
        minus the total of already-posted paid-on-delivery invoices."""
        from django.db.models import Sum

        unearned = (
            customer.receipts.filter(
                applied_to__isnull=True,
                journal_entry__status="posted",
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        consumed = (
            customer.invoices.filter(
                is_paid_on_delivery=True,
                journal_entry__isnull=False,
            ).aggregate(total=Sum("total"))["total"]
            or Decimal("0.00")
        )
        return money(unearned - consumed)

    @classmethod
    def _post_invoice(cls, invoice: ARInvoice, *, user) -> ARInvoice:
        with transaction.atomic():
            entry = cls._build_invoice_je(invoice, user=user)
            PostingService.post(entry, approver=user, user=user)
            invoice.journal_entry = entry
            # Paid-on-delivery invoices are closed by their advance collection
            # (stay "posted"); credit-sale invoices open a live receivable, so
            # they enter aging and the apply-to picker as "open".
            invoice.status = cls.STATUS_POSTED if invoice.is_paid_on_delivery else "open"
            invoice.approved_by = user
            invoice.approved_at = timezone.now()
            invoice.rejected_by = None
            invoice.rejected_at = None
            invoice.rejection_note = ""
            invoice.save(
                update_fields=[
                    "journal_entry",
                    "status",
                    "approved_by",
                    "approved_at",
                    "rejected_by",
                    "rejected_at",
                    "rejection_note",
                    "updated_at",
                ]
            )
            _log(invoice, "approved", actor=user)
        from apps.tax.services import VATService

        VATService.extract_from_invoice(invoice)
        return invoice

    @staticmethod
    def _build_invoice_je(invoice: ARInvoice, *, user):
        """Build the revenue JE for the approved invoice (not yet posted)."""
        if invoice.is_paid_on_delivery:
            debit_account = segment_unearned_account(invoice.segment)
            debit_description = f"Unearned revenue applied - {invoice.invoice_no}"
        else:
            debit_account = segment_ar_account(invoice.segment)
            debit_description = f"Accounts Receivable - {invoice.customer.name}"
        credit_account = segment_sales_account(invoice.segment)
        missing = [
            name
            for name, account in (
                ("AR/Unearned", debit_account),
                ("Sales", credit_account),
            )
            if account is None
        ]
        if missing:
            raise ValidationError(
                f"Segment {invoice.segment.code} is missing COA accounts for "
                f"SI posting ({', '.join(missing)})."
            )

        entry_no = invoice.invoice_no
        entry = JournalEntry.objects.create(
            entry_no=entry_no,
            company=invoice.segment.company,
            segment=invoice.segment,
            fiscal_period=_fiscal_period_for(invoice.transaction_date),
            transaction_date=invoice.transaction_date,
            status=PostingStatus.APPROVED,
            description=f"Sales Invoice {invoice.invoice_no} {invoice.customer.name}",
            source_doc_type="SI",
            source_doc_no=invoice.invoice_no,
            created_by=user,
            approved_by=user,
            approved_at=timezone.now(),
        )
        JournalEntryLine.objects.create(
            entry=entry,
            line_no=1,
            account=debit_account,
            segment=invoice.segment,
            description=debit_description,
            debit=invoice.total,
        )
        JournalEntryLine.objects.create(
            entry=entry,
            line_no=2,
            account=credit_account,
            segment=invoice.segment,
            description=f"Sales - {invoice.invoice_no}",
            credit=invoice.total,
        )
        entry.recalc_totals()
        return entry

    # ------------------------------------------------------------------ reject

    @classmethod
    def reject(cls, invoice: ARInvoice, *, user, note: str) -> ARInvoice:
        from apps.core.approvals import require_approval_role

        require_approval_role(user, "head")
        if invoice.status != cls.STATUS_SUBMITTED:
            raise ValidationError("Only submitted invoices can be rejected.")
        if not (note and note.strip()):
            raise ValidationError("A rejection note is required.")
        invoice.status = cls.STATUS_DRAFT
        invoice.rejected_by = user
        invoice.rejected_at = timezone.now()
        invoice.rejection_note = note.strip()
        invoice.save(
            update_fields=[
                "status",
                "rejected_by",
                "rejected_at",
                "rejection_note",
                "updated_at",
            ]
        )
        _log(invoice, "rejected", actor=user, note=note.strip())
        return invoice
