"""Phase-2 projection tests — item purchasing, prices, pro-rata payments.

Seeds a PO (two item lines), a linked posted RFP and one cleared CV, then
asserts the projection math (units, latest price, 80% pro-rata attribution)
and the catalog routing of the flipped A/J questions.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.ap.models import CheckVoucher, POLine, PurchaseOrder, RFPDocument, RFPLine, Supplier
from apps.assistant.answers.context import Entities, QContext
from apps.assistant.answers import purchase_projection as proj
from apps.assistant.services import AssistantService
from apps.foundation.models import UserProfile
from apps.inventory.models import InventoryEvent, InventoryEventType
from apps.posting.models import PostingStatus

from .test_answer_handlers import _post

User = get_user_model()


@pytest.fixture
def staff(db):
    u = User.objects.create_user(username="proj", password="x")
    UserProfile.objects.create(user=u, approval_role="staff")
    return u


@pytest.fixture
def books(company, segment, accounts, staff):
    """PO 100K (Diesel 80K + Oil filter 20K), RFP 100K posted, CV 60K cleared."""
    limdon = Supplier.objects.create(
        code="S001", name="Limdon Sales Corporation", default_segment=segment, approval_status="approved"
    )
    po = PurchaseOrder.objects.create(
        po_number="PO-2026-0042", po_date=date(2026, 8, 1), supplier=limdon,
        segment=segment, amount=Decimal("100000.00"), status="approved",
    )
    POLine.objects.create(po=po, line_no=1, pr_number="2026-300", qty=Decimal("10"), unit="LTR",
                          description="Diesel", unit_price=Decimal("8000.00"), amount=Decimal("80000.00"))
    POLine.objects.create(po=po, line_no=2, pr_number="2026-301", qty=Decimal("1"), unit="PC",
                          description="Oil filter", unit_price=Decimal("20000.00"), amount=Decimal("20000.00"))
    # Old item with no recent movement (for J88)
    old = Supplier.objects.create(code="S002", name="Old Parts Co", default_segment=segment, approval_status="approved")
    old_po = PurchaseOrder.objects.create(
        po_number="PO-2025-0099", po_date=date(2026, 1, 15), supplier=old,
        segment=segment, amount=Decimal("5000.00"), status="approved",
    )
    POLine.objects.create(po=old_po, line_no=1, pr_number="2025-77", qty=Decimal("2"), unit="PC",
                          description="Obsolete spare part", unit_price=Decimal("2500.00"), amount=Decimal("5000.00"))

    rfp_je = _post(company, segment, date(2026, 8, 10), [("61100", "100000.00"), ("20000", "-100000.00")], "JE-2026-0300", "RFP - Limdon fuel")
    rfp = RFPDocument.objects.create(
        ap_number="A2026-0300", rfp_date=date(2026, 8, 10), payee=limdon, segment=segment,
        particulars="Fuel purchase", amount=Decimal("100000.00"), status="posted",
        journal_entry=rfp_je, po=po, created_by=staff,
    )
    RFPLine.objects.create(rfp=rfp, line_no=1, side="dr", segment=segment, account=accounts["61100"], amount=Decimal("100000.00"))
    RFPLine.objects.create(rfp=rfp, line_no=2, side="cr", segment=segment, account=accounts["20000"], amount=Decimal("100000.00"))
    cv_je = _post(company, segment, date(2026, 8, 20), [("20000", "60000.00"), ("10110", "-60000.00")], "JE-2026-0301", "CV clearing - Limdon")
    CheckVoucher.objects.create(
        cv_number="CV-2026-0042", cv_date=date(2026, 8, 20), rfp=rfp, payee=limdon,
        bank_account=accounts["10110"], gross_amount=Decimal("60000.00"),
        withheld_tax=Decimal("0.00"), net_amount=Decimal("60000.00"),
        check_no="777007", status="cleared", journal_entry=cv_je,
    )
    InventoryEvent.objects.create(
        event_key="INV-2026-0001", event_type=InventoryEventType.GOODS_RECEIPT,
        segment=segment, company=company, occurred_on=date(2026, 8, 5),
        payload={"product": "Diesel", "qty": "10", "unit_cost": "8000"}, status="posted",
    )
    return {"limdon": limdon, "po": po, "old_po": old_po, "rfp": rfp}


def _ctx(books, entities, lower):
    return QContext(user=None, raw=lower, lower=lower, terms=[], companies=[books["po"].segment.company], entities=entities)


class TestProjectionMath:
    def test_item_totals(self, books):
        t = proj.item_totals("diesel")
        assert t["lines"] == 1
        assert t["total_qty"] == Decimal("10.00")
        assert t["total_amount"] == Decimal("80000.00")

    def test_price_history_orders(self, books):
        rows = proj.price_history("diesel")
        assert rows[0]["unit_price"] == Decimal("8000.00")
        rows2 = proj.price_history("oil")
        assert rows2[0]["unit_price"] == Decimal("20000.00")

    def test_pro_rata_paid(self, books):
        # PO cleared 60K; diesel is 80% of PO lines -> 48K attributed.
        assert proj.item_paid("diesel") == Decimal("48000.00")
        assert proj.item_paid("oil filter") == Decimal("12000.00")

    def test_payment_status(self, books):
        data = proj.item_payment_status("diesel")
        assert data["total_paid"] == Decimal("48000.00")
        assert len(data["rows"]) == 1

    def test_item_suppliers_distinct(self, books):
        rows = proj.item_suppliers("part")
        assert [r["supplier"] for r in rows] == ["Old Parts Co"]

    def test_supplier_items(self, books):
        rows = proj.supplier_items(books["limdon"])
        assert len(rows) == 2
        assert rows[0]["description"] == "Diesel"

    def test_event_items(self, books):
        rows = proj.event_items("diesel")
        assert rows and rows[0]["qty"] == "10"

    def test_no_movement_excludes_recent_and_includes_old(self, books):
        from apps.assistant.answers.handlers.inventory import no_movement

        e = Entities()
        ans = no_movement(_ctx(books, e, "no movement items"), e)
        assert any("Obsolete spare part" in r["Item"] for r in ans.rows)
        assert all("Diesel" not in r["Item"] for r in ans.rows)


class TestHandlers:
    def test_item_units_handler(self, books):
        from apps.assistant.answers.handlers.purchase_items import item_units

        e = Entities(item_text="diesel")
        ans = item_units(_ctx(books, e, "how many units"), e)
        assert "10.00" in ans.summary

    def test_latest_price_handler(self, books):
        from apps.assistant.answers.handlers.purchase_items import item_prices

        e = Entities(item_text="oil filter")
        ctx = _ctx(books, e, "latest price")
        ctx.entry = type("E", (), {"qid": "A9"})()
        ans = item_prices(ctx, e)
        assert "20,000.00" in ans.summary

    def test_paid_handler(self, books):
        from apps.assistant.answers.handlers.purchase_items import item_paid

        e = Entities(item_text="diesel")
        ctx = _ctx(books, e, "how much did we pay for diesel")
        ctx.entry = type("E", (), {"qid": "A3"})()
        ans = item_paid(ctx, e)
        assert "48,000.00" in ans.summary
        assert "60%" in ans.summary  # 48K of 80K attributed paid

    def test_fully_paid_doc_handler(self, books):
        from apps.assistant.answers.handlers.purchase import fully_paid

        e = Entities(po=books["po"])
        ans = fully_paid(_ctx(books, e, "is this purchase fully paid"), e)
        assert ans.qid == "A15"
        assert "partially paid" in ans.summary

    def test_inventory_cost_handler(self, books):
        from apps.assistant.answers.handlers.inventory import inventory_cost

        e = Entities(item_text="diesel")
        ans = inventory_cost(_ctx(books, e, "inventory cost"), e)
        assert "80,000.00" in ans.summary

    def test_inventory_history_handler(self, books):
        from apps.assistant.answers.handlers.inventory import inventory_history

        e = Entities(item_text="diesel")
        ans = inventory_history(_ctx(books, e, "history"), e)
        assert len(ans.rows) >= 2  # purchase line + event


class TestRouting:
    def test_item_questions_answer_via_service(self, staff, books):
        svc = AssistantService()
        resp = svc.process_query(staff, "how many units of diesel did we purchase")
        block = resp["answer_block"]
        assert block["qid"] == "A6"
        assert "10.00" in resp["text"]

    def test_price_question_via_service(self, staff, books):
        resp = AssistantService().process_query(staff, "what was the unit cost of the oil filter")
        block = resp["answer_block"]
        assert block["qid"] in ("A7", "A9")

    def test_supplier_of_item_via_service(self, staff, books):
        resp = AssistantService().process_query(staff, "who supplied the diesel")
        assert resp["answer_block"]["qid"] in ("A1", "A2", "J83")
        assert "Limdon" in resp["text"]

    def test_inventory_movement_via_service(self, staff, books):
        resp = AssistantService().process_query(staff, "what is the item movement of diesel")
        assert resp["answer_block"]["qid"] == "J86"

    def test_no_movement_via_service(self, staff, books):
        resp = AssistantService().process_query(staff, "what items have no movement")
        assert resp["answer_block"]["qid"] == "J88"