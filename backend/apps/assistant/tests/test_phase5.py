"""Phase 5 tests — small talk, count aggregates (L101–L116), who-prepared (L117).

All tests run through the real AssistantService where routing matters, plus
direct handler math checks with seeded documents.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlparse

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import resolve
from django.utils import timezone

from apps.ap.models import CheckVoucher, POLine, PurchaseOrder, RFPDocument, Supplier
from apps.ar.models import Customer
from apps.assistant.services import AssistantService
from apps.foundation.models import UserProfile

User = get_user_model()


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def staff(db):
    u = User.objects.create_user(username="phase5", password="x")
    UserProfile.objects.create(user=u, approval_role="staff")
    return u


@pytest.fixture
def other_user(db):
    u = User.objects.create_user(username="preparer2", password="x")
    UserProfile.objects.create(user=u, approval_role="staff")
    return u


@pytest.fixture
def supplier(segment):
    return Supplier.objects.create(code="S901", name="Limdon Fuel Depot", default_segment=segment, approval_status="approved")


def _cv(segment, supplier, accounts, days_ago, status="created", rfp=None, idx=0):
    from apps.ap.models import CheckVoucher

    return CheckVoucher.objects.create(
        cv_number=f"CV-2026-P5-{idx}",
        cv_date=date.today() - timedelta(days=days_ago),
        rfp=rfp,
        payee=supplier,
        bank_account=accounts["10110"],
        gross_amount=Decimal("100.00"),
        withheld_tax=Decimal("0.00"),
        net_amount=Decimal("100.00"),
        status=status,
    )


def _ask(user, message):
    return AssistantService().process_query(user, message)


class TestSmallTalk:
    @pytest.mark.parametrize("message,needle", [
        ("hi", "Hello"),
        ("hello", "Hello"),
        ("how are you?", "great"),
        ("thank you", "welcome"),
        ("who are you?", "Smart Search Assistant"),
        ("what can you do?", "Smart Search Assistant"),
    ])
    def test_english_small_talk(self, staff, db, message, needle):
        resp = _ask(staff, message)
        block = resp.get("answer_block")
        assert block is not None, resp["text"]
        assert block["qid"] == "CHAT"
        assert block["module"] == "assistant"
        assert needle.lower() in resp["text"].lower()

    def test_date_and_time(self, staff, db):
        date_resp = _ask(staff, "What is today's date?")
        assert date_resp["answer_block"]["qid"] == "CHAT"
        expected = timezone.localdate().strftime("%B %d, %Y")
        assert expected in date_resp["text"]
        time_resp = _ask(staff, "what time is it?")
        assert time_resp["answer_block"]["qid"] == "CHAT"

    def test_weather_is_polite_cant_do(self, staff, db):
        resp = _ask(staff, "what's the weather today")
        assert resp["answer_block"]["qid"] == "CHAT"
        assert "can't check" in resp["text"]

    def test_cebuano_greeting(self, staff, db):
        resp = _ask(staff, "kumusta ka?")
        assert resp["answer_block"]["qid"] == "CHAT"

    def test_small_talk_prefix_with_real_question_still_searches(self, staff, db, supplier):
        # "hi ... limdon" must NOT be intercepted as small talk
        resp = _ask(staff, "hi show me any reference from limdon")
        block = resp.get("answer_block")
        assert block is None or block["qid"] != "CHAT"


class TestCounts:
    def _week_bounds(self):
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        return today, monday

    def test_cv_counts_week_windows(self, staff, db, segment, supplier, accounts):
        today, monday = self._week_bounds()
        _cv(segment, supplier, accounts, 0, idx=1)                      # this week
        _cv(segment, supplier, accounts, (today - monday).days, idx=2)  # this week (monday)
        _cv(segment, supplier, accounts, (today - monday).days + 5, idx=3)  # before monday

        total = _ask(staff, "how many cvs do we have")
        assert total["answer_block"]["qid"] == "L102"
        assert "3 check vouchers in total" in total["text"]

        week = _ask(staff, "how many cvs this week")
        assert "2 check vouchers in" in week["text"]

        last = _ask(staff, "how many cvs last week")
        assert "1 check voucher"  in last["text"]

    def test_rfp_count_status_filter(self, staff, db, segment, supplier, accounts):
        _cv(segment, supplier, accounts, 0, status="cleared", idx=4)
        _cv(segment, supplier, accounts, 0, status="created", idx=5)
        resp = _ask(staff, "how many cv cleared")
        block = resp["answer_block"]
        assert block["qid"] == "L102"
        assert "1 check voucher" in resp["text"]

    def test_pr_count_distinct(self, staff, db, segment, supplier):
        po_a = PurchaseOrder.objects.create(
            po_number="PO-2026-0601", po_date=date.today(), supplier=supplier,
            segment=segment, amount=Decimal("10.00"), status="approved",
        )
        POLine.objects.create(po=po_a, line_no=1, pr_number="2026-77", qty=Decimal("1"), unit="PC", description="Tire", unit_price=Decimal("5.00"), amount=Decimal("5.00"))
        POLine.objects.create(po=po_a, line_no=2, pr_number="2026-77", qty=Decimal("1"), unit="PC", description="Tube", unit_price=Decimal("5.00"), amount=Decimal("5.00"))
        po_b = PurchaseOrder.objects.create(
            po_number="PO-2026-0602", po_date=date.today(), supplier=supplier,
            segment=segment, amount=Decimal("5.00"), status="approved",
        )
        POLine.objects.create(po=po_b, line_no=1, pr_number="2026-78", qty=Decimal("1"), unit="PC", description="Cable", unit_price=Decimal("5.00"), amount=Decimal("5.00"))
        resp = _ask(staff, "how many purchase requests do we have")
        assert resp["answer_block"]["qid"] == "L107"
        assert "2 purchase requests" in resp["text"]

    def test_explicit_month_count(self, staff, db, segment, supplier, accounts):
        from apps.ap.models import CheckVoucher

        CheckVoucher.objects.create(
            cv_number="CV-2026-SEP1", cv_date=date(2026, 9, 5), payee=supplier,
            bank_account=accounts["10110"], gross_amount=Decimal("10.00"),
            net_amount=Decimal("10.00"),
        )
        CheckVoucher.objects.create(
            cv_number="CV-2026-OCT1", cv_date=date(2026, 10, 5), payee=supplier,
            bank_account=accounts["10110"], gross_amount=Decimal("10.00"),
            net_amount=Decimal("10.00"),
        )
        sep = _ask(staff, "how many check vouchers in september 2026")
        assert "1 check voucher" in sep["text"]
        assert "September 2026" in sep["text"]

    def test_master_counts(self, staff, db, segment, supplier):
        Supplier.objects.create(code="S902", name="Second Depot", default_segment=segment, approval_status="approved")
        Customer.objects.create(code="C901", name="Maple Client", approval_status="approved")
        resp = _ask(staff, "how many suppliers do we have")
        assert resp["answer_block"]["qid"] == "L116"
        assert "2 suppliers" in resp["text"]
        cust = _ask(staff, "how many customers do we have")
        assert "1 customer" in cust["text"]
        for link in cust["answer_block"]["links"]:
            resolve(urlparse(link["url"]).path)


class TestRfpPerCv:
    def test_aggregate_math(self, staff, db, segment, supplier, accounts):
        r1 = RFPDocument.objects.create(
            ap_number="A2026-0701", rfp_date=date.today(), payee=supplier,
            segment=segment, amount=Decimal("100.00"), status="posted",
        )
        r2 = RFPDocument.objects.create(
            ap_number="A2026-0702", rfp_date=date.today(), payee=supplier,
            segment=segment, amount=Decimal("50.00"), status="posted",
        )
        _cv(segment, supplier, accounts, 0, rfp=r1, idx=6)
        _cv(segment, supplier, accounts, 0, rfp=r1, idx=7)  # split settlement
        _cv(segment, supplier, accounts, 0, rfp=None, idx=8)

        resp = _ask(staff, "how many rfps are made per cv")
        block = resp["answer_block"]
        assert block["qid"] == "L101"
        assert "3 check voucher" in resp["text"]
        assert "2 RFP" in resp["text"]
        assert "66.7%" in resp["text"]
        assert "0.67" in resp["text"]
        split_rows = block["rows"] or []
        assert any(r["RFP split across"] == "A2026-0701" and r["CVs"] == 2 for r in split_rows)
        for link in block["links"]:
            resolve(urlparse(link["url"]).path)


class TestWhoPrepared:
    def test_rfp_and_po_preparers(self, staff, other_user, db, segment, supplier, accounts):
        from .test_answer_handlers import _post

        po = PurchaseOrder.objects.create(
            po_number="PO-2026-0710", po_date=date(2026, 9, 8), supplier=supplier,
            segment=segment, amount=Decimal("20.00"), status="approved",
            created_by=other_user,
        )
        POLine.objects.create(po=po, line_no=1, pr_number="2026-99", qty=Decimal("4"), unit="PC",
                              description="Replacement tire", unit_price=Decimal("5.00"), amount=Decimal("20.00"))
        rfp = RFPDocument.objects.create(
            ap_number="A2026-0720", rfp_date=date(2026, 9, 9), payee=supplier,
            segment=segment, amount=Decimal("20.00"), status="posted",
            particulars="replacement tire for limdon", created_by=staff, po=po,
        )
        resp = _ask(staff, "who processed the tire for limdon")
        block = resp["answer_block"]
        assert block is not None, resp["text"]
        assert block["qid"] == "L117"
        assert "PO-2026-0710" in resp["text"]
        assert "A2026-0720" in resp["text"]
        assert "preparer2" in resp["text"]          # PO preparer
        assert "phase5" in resp["text"]             # RFP preparer
        for link in block["links"]:
            resolve(urlparse(link["url"]).path)

    def test_no_match_answers_gracefully(self, staff, db, segment, supplier):
        resp = _ask(staff, "who processed the widget for limdon")
        assert resp.get("answer_block") is not None
        assert "No matching purchase or payment" in resp["text"]


class TestPhase5LinksResolve:
    def test_comment_all_new_registry_links(self, staff, db, segment, supplier, accounts):
        _cv(segment, supplier, accounts, 0, idx=9)
        for message in (
            "how many cvs do we have",
            "how many rfps do we have",
            "how many journal entries do we have",
            "how many ftvs do we have",
            "how many purchase orders do we have",
            "how many conso batches do we have",
            "how many sales invoices do we have",
            "how many receipts do we have",
            "how many pcf replenishments do we have",
            "how many advances do we have",
            "how many billing transactions do we have",
            "how many assets do we have",
        ):
            resp = _ask(staff, message)
            block = resp.get("answer_block")
            assert block is not None, message
            assert block["qid"].startswith("L1"), message
            for link in block.get("links", []):
                resolve(urlparse(link["url"]).path)