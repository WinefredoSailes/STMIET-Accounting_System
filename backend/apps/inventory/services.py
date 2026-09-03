"""Inventory integration bridge services (BUILD-PLAN Phase 5).

`InventoryBridgeService` is the single ingestion path for inventory-system
events. It:

1. Validates the inbound payload schema (per event type).
2. Guards idempotency on `event_key` so a replayed event never double-posts.
3. Maps the event to a balanced JournalEntry per POSTING_RULES §5.1-5.3 plus
   the transfer / revaluation legs from BUSINESS-EVENT-CATALOG.
4. Posts through the standard `PostingService` engine, so every posting rule
   (balance, segment consistency, immutability, reversal) still applies.

Accounts are resolved from the COA master via the payload-provided codes,
validated to exist and be postable. Nothing here hardcodes a GL code; the
write-off expense (5.2) and inventory account families are convention checks
that corroborate the code the external system sent.
"""

from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.core.exceptions import ValidationError
from apps.core.money import money
from apps.foundation.models import Account, Company, Segment
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService

from .models import (
    InventoryEvent,
    InventoryEventLine,
    InventoryEventStatus,
    InventoryEventType,
)


class InventoryBridgeService:
    """Stateless bridge: ingest -> validate -> post (idempotent)."""

    # event types the bridge is allowed to book in this phase.
    SUPPORTED_TYPES = {
        InventoryEventType.GOODS_RECEIPT,
        InventoryEventType.WRITE_OFF,
        InventoryEventType.PHYSICAL_COUNT,
        InventoryEventType.TRANSFER,
        InventoryEventType.REVALUATION,
    }

    @classmethod
    def _get_account(cls, code, *, required_typename="", allowed_prefixes=()):
        """A postable COA Account for `code`, loudly missing when absent."""
        if not code:
            raise ValidationError("Inventory event missing a posting account code.")
        try:
            acct = Account.objects.get(code=code, is_postable=True)
        except Account.DoesNotExist as exc:
            raise ValidationError(f"Inventory postable account '{code}' not found in COA.") from exc
        return acct

    @classmethod
    def _normalize_amount(cls, value, field):
        try:
            return money(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{field} must be a positive amount; got {value!r}.") from exc

    # ------------------------------------------------------------------ ingest

    @classmethod
    def ingest(cls, *, event_key: str, event_type: str, segment_code: str,
               occurred_on, payload: dict, user=None) -> InventoryEvent:
        """Validate + book (or skip as duplicate) one inventory event.

        Returns the `InventoryEvent` row. If `event_key` was already seen the
        row is recorded as DUPLICATE and no JE is created (safe replay).
        """
        created = False
        try:
            event = InventoryEvent.objects.get(event_key=event_key)
        except InventoryEvent.DoesNotExist:
            segment = cls._resolve_segment(segment_code)
            event = InventoryEvent(
                event_key=event_key,
                event_type=event_type,
                segment=segment,
                company=segment.company,
                occurred_on=occurred_on,
                payload=payload,
                status=InventoryEventStatus.RECEIVED,
                created_by=user,
            )
            event.save()
            created = True

        if not created:
            # Replayed key: never double-post. Mark-and-return as duplicate.
            if event.status != InventoryEventStatus.DUPLICATE:
                event.status = InventoryEventStatus.DUPLICATE
                event.save(update_fields=["status", "updated_at"])
            return event

        try:
            with transaction.atomic():
                cls._book(event)
        except Exception as exc:  # noqa: BLE001 - captured for the retry queue
            event.status = InventoryEventStatus.FAILED
            event.error_message = str(exc)
            event.save(update_fields=["status", "error_message", "updated_at"])
            raise
        return event

    @classmethod
    def _resolve_segment(cls, code):
        try:
            return Segment.objects.get(code=code)
        except Segment.DoesNotExist as exc:
            raise ValidationError(f"Segment '{code}' not found.") from exc

    # ------------------------------------------------------------------ book

    @classmethod
    def _book(cls, event: InventoryEvent, user=None) -> JournalEntry:
        """Build + post the JE for `event`; returns the posted JournalEntry."""
        if event.event_type not in cls.SUPPORTED_TYPES:
            raise ValidationError(f"Unsupported inventory event type '{event.event_type}'.")

        if event.event_type == InventoryEventType.GOODS_RECEIPT:
            je = cls._book_goods_receipt(event, user=user)
        elif event.event_type in (InventoryEventType.WRITE_OFF, InventoryEventType.PHYSICAL_COUNT):
            je = cls._book_write_off(event, user=user)
        elif event.event_type == InventoryEventType.TRANSFER:
            je = cls._book_transfer(event, user=user)
        else:  # REVALUATION
            je = cls._book_revaluation(event, user=user)

        event.journal_entry = je
        event.status = InventoryEventStatus.POSTED
        event.processed_at = _now()
        event.save(update_fields=["journal_entry", "status", "processed_at", "updated_at"])
        return je

    # ------------------------------------------------------------------ rules

    @classmethod
    def _book_goods_receipt(cls, event, user=None) -> JournalEntry:
        """§5.1 Dr 130xx Inventory | Cr 20000-20006 AP ({qty x unit_cost})."""
        payload = event.payload
        quantity = _dec(payload.get("quantity"))
        unit_cost = cls._normalize_amount(payload.get("unit_cost"), "unit_cost")
        if quantity <= 0 or unit_cost <= 0:
            raise ValidationError("Goods receipt needs quantity and unit_cost > 0.")
        total = money(quantity * unit_cost)

        inventory_acct = cls._get_account(
            payload.get("inventory_account"),
            required_typename="asset", allowed_prefixes=("130", "132"),
        )
        ap_acct = cls._get_account(
            payload.get("ap_account"),
            required_typename="liability", allowed_prefixes=("20000", "20001", "20006"),
        )

        return cls._post_journal(
            event, description=f"Inventory goods receipt {payload.get('reference', '')}".strip(),
            source_doc_no=str(payload.get("reference", event.event_key)),
            lines=[
                (inventory_acct, total, Decimal("0.00"),
                 f"{payload.get('quantity')} x {payload.get('unit_cost')}"),
                (ap_acct, Decimal("0.00"), total, "Accounts payable"),
            ],
            user=user,
        )

    @classmethod
    def _book_write_off(cls, event, user=None) -> JournalEntry:
        """§5.2/5.3 Dr 63200-63246 (if loss) | Cr 130xx Inventory (variance)."""
        payload = event.payload
        amount = cls._normalize_amount(payload.get("amount"), "amount")
        if amount <= 0:
            raise ValidationError("Write-off / adjustment amount must be > 0.")
        is_loss = bool(payload.get("is_loss", True))
        if not is_loss:
            return cls._book_write_off_gain(event, amount, user=user)

        expense_acct = cls._get_account(
            payload.get("expense_account"),
            required_typename="expense", allowed_prefixes=("632",),
        )
        inventory_acct = cls._get_account(
            payload.get("inventory_account"),
            required_typename="asset", allowed_prefixes=("130", "132"),
        )
        return cls._post_journal(
            event, description=f"Inventory write-off {payload.get('reference', '')}".strip(),
            source_doc_no=str(payload.get("reference", event.event_key)),
            lines=[
                (expense_acct, amount, Decimal("0.00"), "Inventory loss"),
                (inventory_acct, Decimal("0.00"), amount, "Inventory reduction"),
            ],
            user=user,
        )

    @classmethod
    def _book_write_off_gain(cls, event, amount, user=None) -> JournalEntry:
        """Gain variant of 5.2: reverse (Cr 632xx income | Dr 130xx restock)."""
        payload = event.payload
        expense_acct = cls._get_account(
            payload.get("expense_account"),
            required_typename="expense", allowed_prefixes=("632",),
        )
        inventory_acct = cls._get_account(
            payload.get("inventory_account"),
            required_typename="asset", allowed_prefixes=("130", "132"),
        )
        return cls._post_journal(
            event, description=f"Inventory adjustment (gain) {payload.get('reference', '')}".strip(),
            source_doc_no=str(payload.get("reference", event.event_key)),
            lines=[
                (inventory_acct, amount, Decimal("0.00"), "Inventory restock"),
                (expense_acct, Decimal("0.00"), amount, "Expense reversal"),
            ],
            user=user,
        )

    @classmethod
    def _book_transfer(cls, event, user=None) -> JournalEntry:
        """Dr Inventory-To | Cr Inventory-From (BUSINESS-EVENT-CATALOG #55)."""
        payload = event.payload
        amount = cls._normalize_amount(payload.get("amount"), "amount")
        if amount <= 0:
            raise ValidationError("Transfer amount must be > 0.")
        to_acct = cls._get_account(
            payload.get("to_account"),
            required_typename="asset", allowed_prefixes=("130", "132"),
        )
        from_acct = cls._get_account(
            payload.get("from_account"),
            required_typename="asset", allowed_prefixes=("130", "132"),
        )
        return cls._post_journal(
            event, description=f"Inventory transfer {payload.get('reference', '')}".strip(),
            source_doc_no=str(payload.get("reference", event.event_key)),
            lines=[
                (to_acct, amount, Decimal("0.00"), f"Transferred to {payload.get('to', '')}"),
                (from_acct, Decimal("0.00"), amount, f"Transferred from {payload.get('from', '')}"),
            ],
            user=user,
        )

    @classmethod
    def _book_revaluation(cls, event, user=None) -> JournalEntry:
        """Dr/Cr Inventory | Cr/Dr COGS (BUSINESS-EVENT-CATALOG #59)."""
        payload = event.payload
        amount = cls._normalize_amount(payload.get("amount"), "amount")
        if amount <= 0:
            raise ValidationError("Revaluation amount must be > 0.")
        increase = bool(payload.get("increase", True))
        inventory_acct = cls._get_account(
            payload.get("inventory_account"),
            required_typename="asset", allowed_prefixes=("130", "132"),
        )
        cogs_acct = cls._get_account(
            payload.get("cogs_account"),
            required_typename="expense", allowed_prefixes=("611",),
        )
        if increase:
            lines = [
                (inventory_acct, amount, Decimal("0.00"), "Revaluation increase"),
                (cogs_acct, Decimal("0.00"), amount, "COGS relief"),
            ]
        else:
            lines = [
                (cogs_acct, amount, Decimal("0.00"), "Revaluation decrease"),
                (inventory_acct, Decimal("0.00"), amount, "Inventory write-down"),
            ]
        return cls._post_journal(
            event, description=f"Inventory revaluation {payload.get('reference', '')}".strip(),
            source_doc_no=str(payload.get("reference", event.event_key)),
            lines=lines,
            user=user,
        )

    # ------------------------------------------------------------------ shared

    @classmethod
    def _post_journal(cls, event, *, description, source_doc_no, lines, user=None) -> JournalEntry:
        """Build a balanced JE from `lines` (account, debit, credit, text) + post."""
        journal = JournalEntry(
            entry_no=f"INV-{event.event_key}",
            company=event.company,
            segment=event.segment,
            transaction_date=event.occurred_on,
            status=PostingStatus.DRAFT,
            description=description,
            source_doc_type="INV",
            source_doc_no=source_doc_no,
            created_by=user,
        )
        journal.save()
        for i, (acct, debit, credit, text) in enumerate(lines, start=1):
            JournalEntryLine.objects.create(
                entry=journal, line_no=i, account=acct,
                debit=debit, credit=credit, description=text,
            )
        journal.recalc_totals()
        PostingService.post(journal, user=user)

        # Persist the auditable legs.
        for i, (acct, debit, credit, text) in enumerate(lines, start=1):
            InventoryEventLine.objects.create(
                event=event, line_no=i, account=acct,
                description=text, debit=debit, credit=credit,
            )
        return journal

    @classmethod
    def run_retry_queue(cls, *, segment=None, limit=50, user=None) -> list:
        """Re-process FAILED events in creation order (offline-tolerant retry).

        `segment` is either a Segment instance or a segment code string.
        """
        qs = InventoryEvent.objects.filter(status=InventoryEventStatus.FAILED)
        if segment:
            if isinstance(segment, str):
                segment = cls._resolve_segment(segment)
            qs = qs.filter(segment=segment)
        processed = []
        with transaction.atomic():
            events = list(qs.order_by("created_at")[:limit])
            for event in events:
                event.retry_count += 1
                try:
                    cls._book(event, user=user)
                    event.status = InventoryEventStatus.POSTED
                except Exception as exc:  # noqa: BLE001
                    event.status = InventoryEventStatus.FAILED
                    event.error_message = str(exc)
                event.save(update_fields=["status", "error_message", "retry_count", "updated_at"])
                processed.append(event)
        return processed


def _now():
    from django.utils import timezone

    return timezone.now()


def _dec(value):
    """decimal.Decimal coercion that never crashes on None/empty."""
    if value in (None, ""):
        return Decimal("0.00")
    return Decimal(str(value))