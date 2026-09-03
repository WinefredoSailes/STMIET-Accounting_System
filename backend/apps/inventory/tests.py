"""Inventory integration bridge contract tests (BUILD-PLAN Phase 5).

Covers:
- Idempotent ingest (a replayed event_key never double-posts)
- §5.1 goods receipt  Dr 130xx | Cr 20000-20006
- §5.2/5.3 write-off  Dr 632xx | Cr 130xx (and gain reversal)
- Transfer           Dr Inventory-To | Cr Inventory-From
- Revaluation        Dr/Cr Inventory | Cr/Dr COGS
- Error/retry queue  (failed → run_retry_queue → posted)
- HTTP ingest + status endpoints
"""

from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.foundation.models import Account

from .models import InventoryEvent, InventoryEventStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def inv_accounts(db, company, segment):
    """COA slice for inventory events: 130xx stocks + 632xx loss + 61100 COGS."""
    rows = [
        ("13000", "Fuel Inventory", "asset"),
        ("13030", "Spare Parts Inventory", "asset"),
        ("13040", "Lubricants Inventory", "asset"),
        ("20000", "A/Payables - Current - DHPP", "liability"),
        ("63200", "Other Fees/Charges", "expense"),
        ("61100", "Cost of Sales", "expense"),
    ]
    out = {}
    for code, name, atype in rows:
        out[code] = Account.objects.create(
            code=code, name=name, account_type=atype, segment=Account.segment_for_code(code)
        )
    return out


@pytest.fixture
def api(client):
    return APIClient()


class TestGoodsReceipt:
    def test_books_balanced_je(self, segment, inv_accounts):
        from .services import InventoryBridgeService

        event = InventoryBridgeService.ingest(
            event_key="GR-0001", event_type="goods_receipt", segment_code=segment.code,
            occurred_on=date(2026, 1, 15),
            payload={
                "reference": "PO-001",
                "quantity": "100.00",
                "unit_cost": "55.00",
                "inventory_account": "13000",
                "ap_account": "20000",
            },
        )
        assert event.status == InventoryEventStatus.POSTED
        journal = event.journal_entry
        assert journal.is_balanced and journal.is_posted
        lines = {l.account.code: l for l in journal.lines.all()}
        assert lines["13000"].debit == 5500
        assert lines["20000"].credit == 5500

    def test_duplicate_key_is_noop(self, segment, inv_accounts):
        from .services import InventoryBridgeService

        payload = {
            "reference": "PO-001", "quantity": "100.00", "unit_cost": "55.00",
            "inventory_account": "13000", "ap_account": "20000",
        }
        InventoryBridgeService.ingest(
            event_key="GR-0001", event_type="goods_receipt", segment_code=segment.code,
            occurred_on=date(2026, 1, 15), payload=payload,
        )
        # Replay - DUPLICATE, no second JE.
        dup = InventoryBridgeService.ingest(
            event_key="GR-0001", event_type="goods_receipt", segment_code=segment.code,
            occurred_on=date(2026, 1, 15), payload=payload,
        )
        assert dup.status == InventoryEventStatus.DUPLICATE
        assert InventoryEvent.objects.filter(event_key="GR-0001").count() == 1
        from apps.posting.models import JournalEntry

        assert JournalEntry.objects.filter(source_doc_no="PO-001").count() == 1


class TestWriteOff:
    def test_loss_posts_expense_to_inventory(self, segment, inv_accounts):
        from .services import InventoryBridgeService

        event = InventoryBridgeService.ingest(
            event_key="WO-0001", event_type="write_off", segment_code=segment.code,
            occurred_on=date(2026, 1, 16),
            payload={"reference": "WO-01", "amount": "500.00", "is_loss": True,
                     "expense_account": "63200", "inventory_account": "13000"},
        )
        assert event.status == InventoryEventStatus.POSTED
        lines = {l.account.code: l for l in event.journal_entry.lines.all()}
        assert lines["63200"].debit == 500
        assert lines["13000"].credit == 500

    def test_gain_reverses(self, segment, inv_accounts):
        from .services import InventoryBridgeService

        event = InventoryBridgeService.ingest(
            event_key="WO-GAIN", event_type="write_off", segment_code=segment.code,
            occurred_on=date(2026, 1, 16),
            payload={"reference": "ADJ", "amount": "200.00", "is_loss": False,
                     "expense_account": "63200", "inventory_account": "13000"},
        )
        lines = {l.account.code: l for l in event.journal_entry.lines.all()}
        assert lines["13000"].debit == 200
        assert lines["63200"].credit == 200

    def test_physical_count_same_rule(self, segment, inv_accounts):
        from .services import InventoryBridgeService

        event = InventoryBridgeService.ingest(
            event_key="PC-0001", event_type="physical_count", segment_code=segment.code,
            occurred_on=date(2026, 1, 17),
            payload={"reference": "COUNT-1", "amount": "75.00", "is_loss": True,
                     "expense_account": "63200", "inventory_account": "13030"},
        )
        lines = {l.account.code: l for l in event.journal_entry.lines.all()}
        assert lines["63200"].debit == 75
        assert lines["13030"].credit == 75


class TestTransferAndRevaluation:
    def test_transfer_moves_between_stock_accounts(self, segment, inv_accounts):
        from .services import InventoryBridgeService

        event = InventoryBridgeService.ingest(
            event_key="TR-0001", event_type="transfer", segment_code=segment.code,
            occurred_on=date(2026, 1, 18),
            payload={"reference": "MV-1", "amount": "300.00",
                     "to_account": "13040", "from_account": "13000"},
        )
        lines = {l.account.code: l for l in event.journal_entry.lines.all()}
        assert lines["13040"].debit == 300
        assert lines["13000"].credit == 300

    def test_revaluation_increase(self, segment, inv_accounts):
        from .services import InventoryBridgeService

        event = InventoryBridgeService.ingest(
            event_key="RV-UP", event_type="revaluation", segment_code=segment.code,
            occurred_on=date(2026, 1, 19),
            payload={"reference": "RV-1", "amount": "250.00", "increase": True,
                     "inventory_account": "13000", "cogs_account": "61100"},
        )
        lines = {l.account.code: l for l in event.journal_entry.lines.all()}
        assert lines["13000"].debit == 250
        assert lines["61100"].credit == 250

    def test_revaluation_decrease(self, segment, inv_accounts):
        from .services import InventoryBridgeService

        event = InventoryBridgeService.ingest(
            event_key="RV-DN", event_type="revaluation", segment_code=segment.code,
            occurred_on=date(2026, 1, 19),
            payload={"reference": "RV-2", "amount": "120.00", "increase": False,
                     "inventory_account": "13000", "cogs_account": "61100"},
        )
        lines = {l.account.code: l for l in event.journal_entry.lines.all()}
        assert lines["61100"].debit == 120
        assert lines["13000"].credit == 120


class TestErrorQueue:
    def test_unknown_account_fails_then_retries(self, segment, inv_accounts):
        from .services import InventoryBridgeService

        # Ends up FAILED (bad account code) -> ingest raises ValidationError.
        with pytest.raises(Exception):
            InventoryBridgeService.ingest(
                event_key="GR-BAD", event_type="goods_receipt", segment_code=segment.code,
                occurred_on=date(2026, 1, 20),
                payload={"reference": "PO-X", "quantity": "1.00", "unit_cost": "10.00",
                         "inventory_account": "13000", "ap_account": "99999"},
            )
        evt = InventoryEvent.objects.get(event_key="GR-BAD")
        assert evt.status == InventoryEventStatus.FAILED
        assert evt.retry_count == 0

        # Fix the payload and retry.
        evt.payload["ap_account"] = "20000"
        evt.save(update_fields=["payload"])
        processed = InventoryBridgeService.run_retry_queue(segment=segment.code)
        evt.refresh_from_db()
        assert evt.status == InventoryEventStatus.POSTED
        assert evt.journal_entry is not None
        assert len([e for e in processed if e.event_key == "GR-BAD"]) == 1


class TestHttpEndpoint:
    def test_ingest_returns_created(self, api, segment, inv_accounts, company):
        resp = api.post(
            "/api/v1/inventory/events/",
            {
                "event_key": "GR-HTTP", "event_type": "goods_receipt", "segment": segment.code,
                "occurred_on": "2026-01-21",
                "payload": {"reference": "PO-H", "quantity": "2.00", "unit_cost": "50.00",
                            "inventory_account": "13000", "ap_account": "20000"},
            },
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["status"] == "posted"
        assert resp.data["journal_entry"]

    def test_status_lists_queue(self, api, segment, inv_accounts, company):
        from .services import InventoryBridgeService

        InventoryBridgeService.ingest(
            event_key="ST-1", event_type="goods_receipt", segment_code=segment.code,
            occurred_on=date(2026, 1, 22),
            payload={"reference": "P1", "quantity": "1.00", "unit_cost": "10.00",
                     "inventory_account": "13000", "ap_account": "20000"},
        )
        resp = api.get("/api/v1/inventory/events/status/")
        assert resp.status_code == 200
        keys = [row["event_key"] for row in resp.data]
        assert "ST-1" in keys

    def test_ingest_missing_field_returns_400(self, api):
        resp = api.post("/api/v1/inventory/events/", {"event_type": "goods_receipt"}, format="json")
        assert resp.status_code == 400