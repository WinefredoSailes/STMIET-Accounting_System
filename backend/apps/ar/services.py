"""AR services: collection posting, cycle ledger derivation, aging.

Posting contract (RESOLUTION #9 / POSTING_RULES §12.3, §15.1):
  collection with no prior AR -> Dr Cash | Cr Unearned 21000/21016/21023
  collection applied to AR      -> Dr Cash | Cr AR 12020/12023/12026 (or 12030)
The deposit is a state change only and NEVER posts a JE (ADR-016).
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from apps.core.exceptions import ValidationError
from apps.core.money import money
from apps.foundation.calendar import cycle_range_for
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService

from .models import AcknowledgmentReceipt, ARInvoice, Customer, PaymentMethod

# Segment -> (Unearned account, AR-Other account, AR-Fuel account)
SEGMENT_ACCOUNTS = {
    "DHPP": ("21000", "12020", "12030"),
    "DMIE": ("21023", "12023", "12023"),
    "OPS": ("21016", "12026", "12026"),
}


def _account_code(*codes: str) -> str:
    """Resolve the first code that exists in the COA (segment fallbacks)."""
    from apps.foundation.models import Account

    for code in codes:
        if Account.objects.filter(code=code).exists():
            return code
    raise ValidationError(f"No COA account found for any of {codes}.")


class CollectionService:
    """Owns the single `cash.collection` posting event."""

    @classmethod
    def record_collection(
        cls,
        *,
        receipt_no: str,
        customer,
        transaction_date: date,
        amount,
        cash_account,
        payment_method: str = PaymentMethod.CASH,
        check_no: str = "",
        segment=None,
        applied_to: ARInvoice | None = None,
        user=None,
    ) -> AcknowledgmentReceipt:
        """Create the AR#, validate, and post the collection JE atomically."""
        amount = money(amount)
        if amount <= 0:
            raise ValidationError("Collection amount must be positive.")

        seg = segment or customer.segment
        if applied_to is not None and applied_to.customer_id != customer.id:
            raise ValidationError("Applied invoice belongs to a different customer.")
        if applied_to is not None and applied_to.balance <= 0:
            raise ValidationError(f"Invoice {applied_to.invoice_no} is fully paid.")

        unearned, ar_other, ar_fuel = SEGMENT_ACCOUNTS[seg.code]
        credit_code = _account_code(ar_other, ar_fuel) if applied_to else _account_code(unearned)

        with transaction.atomic():
            receipt = AcknowledgmentReceipt.objects.create(
                receipt_no=receipt_no,
                customer=customer,
                transaction_date=transaction_date,
                amount=amount,
                payment_method=payment_method,
                cash_account=cash_account,
                check_no=check_no,
                collected_by=user,
                segment=seg,
                applied_to=applied_to,
            )

            entry = JournalEntry.objects.create(
                entry_no=receipt_no,
                company=customer.segment.company,
                segment=seg,
                transaction_date=transaction_date,
                status=PostingStatus.DRAFT,
                description=f"Collection {receipt_no} {customer.name}",
                source_doc_type="AR",
                source_doc_no=receipt_no,
                created_by=user,
            )
            JournalEntryLine.objects.create(
                entry=entry, line_no=1, account=cash_account, debit=amount,
                description=f"Collection {receipt_no}",
            )
            JournalEntryLine.objects.create(
                entry=entry, line_no=2, account=_account_object(credit_code), credit=amount,
                description=f"Applied to {applied_to.invoice_no}" if applied_to else "Unearned revenue",
            )
            entry.recalc_totals()
            PostingService.post(entry, user=user)
            receipt.journal_entry = entry
            receipt.save(update_fields=["journal_entry", "updated_at"])

        if applied_to:
            _refresh_invoice_status(applied_to)
        return receipt


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
        for r in receipts:
            start, _ = cycle_range_for(r["transaction_date"])
            events.append((start, "paid", r["paid"]))
        for inv in invoices:
            start, _ = cycle_range_for(inv["transaction_date"])
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
        """AR aging buckets 30/60/90/120+ from open invoice balances."""
        buckets = {"0-30": Decimal("0.00"), "31-60": Decimal("0.00"),
                   "61-90": Decimal("0.00"), "91-120": Decimal("0.00"),
                   "120+": Decimal("0.00")}
        invoices = ARInvoice.objects.filter(status__in=("open", "partially_paid"))
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


def _account_object(code: str):
    from apps.foundation.models import Account

    return Account.objects.get(code=code)


def _refresh_invoice_status(invoice: ARInvoice) -> None:
    if invoice.balance <= 0:
        invoice.status = "paid"
    elif invoice.amount_paid > 0:
        invoice.status = "partially_paid"
    invoice.save(update_fields=["status", "updated_at"])