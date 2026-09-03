"""Inventory integration bridge (BUILD-PLAN Phase 5).

The accounting system does NOT re-implement inventory. A separate live Django
inventory system emits domain events (stock received, stock issued, transfer,
physical count, write-off, revaluation). This app consumes those events and
books the resulting journal entries into the posting engine, eliminating the
manual JE -> CONSO re-entry (ADR-004 / ADR-009 / BUSINESS-EVENT-CATALOG).

Design:
- `InventoryEvent` is the intake record: one row per inbound event, carrying a
  JSON payload, a client-supplied idempotency key, a processing status, and an
  error/retry queue for offline-tolerant handling.
- `InventoryEventLine` captures the resolved GL legs for a multi-leg event so
  the bridge stays auditable (the exact Dr/Cr that was booked).
- Idempotency: an event with a duplicate `event_key` is a no-op (never
  double-posts), so retries are safe.
"""

import uuid

from django.conf import settings
from django.db import models

from apps.core.models import AuditableModel


class InventoryEventType(models.TextChoices):
    GOODS_RECEIPT = "goods_receipt", "Goods Receipt (5.1)"
    WRITE_OFF = "write_off", "Inventory Write-off / Adjustment (5.2)"
    PHYSICAL_COUNT = "physical_count", "Physical Count Adjustment (5.3)"
    TRANSFER = "transfer", "Stock Transfer"
    REVALUATION = "revaluation", "Inventory Revaluation"


class InventoryEventStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    VALIDATED = "validated", "Validated"
    POSTED = "posted", "Posted"
    FAILED = "failed", "Failed"
    DUPLICATE = "duplicate", "Duplicate (ignored)"


class InventoryEvent(AuditableModel):
    """Intake record for one inventory-system domain event (Phase 5).

    `event_key` is the client's idempotency key: a replayed event with the same
    key is recorded as DUPLICATE and never books a second JE. `payload` holds
    the normalized event body (product, qty, unit_cost, accounts, reference).
    A `journal_entry` is linked after the JE posts.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_key = models.CharField(max_length=128, unique=True)
    event_type = models.CharField(max_length=24, choices=InventoryEventType.choices)
    segment = models.ForeignKey(
        "foundation.Segment", on_delete=models.PROTECT, related_name="inventory_events"
    )
    company = models.ForeignKey(
        "foundation.Company", on_delete=models.PROTECT, related_name="inventory_events"
    )
    occurred_on = models.DateField(db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16, choices=InventoryEventStatus.choices, default=InventoryEventStatus.RECEIVED
    )
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    journal_entry = models.ForeignKey(
        "posting.JournalEntry", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-occurred_on", "-created_at"]

    def __str__(self):
        return f"{self.event_type} {self.event_key} [{self.status}]"


class InventoryEventLine(models.Model):
    """Resolved GL leg for an `InventoryEvent` (audit of exactly what posted)."""

    event = models.ForeignKey(InventoryEvent, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveIntegerField()
    account = models.ForeignKey(
        "foundation.Account", on_delete=models.PROTECT, related_name="+"
    )
    description = models.CharField(max_length=255, blank=True)
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        ordering = ["line_no"]

    def __str__(self):
        return f"{self.event.event_type} #{self.line_no}: {self.account.code}"