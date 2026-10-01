"""End-to-end routing tests: computed answers win, legacy search survives,
RBAC gates, and answers persist into history. Everything rides the real
AssistantService pipeline (parser -> dispatcher -> formatter -> history)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from apps.ap.models import RFPDocument, RFPLine, Supplier
from apps.assistant.services import AssistantService
from apps.foundation.models import UserProfile

from .test_answer_handlers import _post

User = get_user_model()


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def staff(db):
    u = User.objects.create_user(username="staff", password="x")
    UserProfile.objects.create(user=u, approval_role="staff")
    return u


@pytest.fixture
def coo(db):
    u = User.objects.create_user(username="coo", password="x")
    UserProfile.objects.create(user=u, approval_role="coo")
    return u


@pytest.fixture
def books(company, segment, accounts, staff):
    """One supplier with a posted-but-unpaid RFP + one open AR invoice."""
    limdon = Supplier.objects.create(
        code="S001", name="Limdon Sales Corporation", default_segment=segment, approval_status="approved"
    )
    je = _post(
        company, segment, date(2026, 9, 5),
        [("61100", "55000.00"), ("20000", "-55000.00")],
        "JE-2026-0101", "RFP - Limdon",
    )
    je.source_doc_no = "A2026-0009"
    je.save(update_fields=["source_doc_no", "updated_at"])
    rfp = RFPDocument.objects.create(
        ap_number="A2026-0009", rfp_date=date(2026, 9, 5), payee=limdon,
        segment=segment, particulars="Fuel", amount=Decimal("55000.00"),
        status="posted", journal_entry=je, created_by=staff,
    )
    RFPLine.objects.create(rfp=rfp, line_no=1, side="dr", segment=segment, account=accounts["61100"], amount=Decimal("55000.00"))
    RFPLine.objects.create(rfp=rfp, line_no=2, side="cr", segment=segment, account=accounts["20000"], amount=Decimal("55000.00"))

    from apps.ar.models import ARInvoice, Customer

    customer = Customer.objects.create(code="C001", name="Maple Fuel Corp", approval_status="approved")
    inv_je = _post(
        company, segment, date(2026, 9, 10),
        [("12030", "30000.00"), ("41010", "-30000.00")],
        "JE-2026-0102", "SI 1003 - Maple",
    )
    ARInvoice.objects.create(
        invoice_no="SI-2026-1003", customer=customer, transaction_date=date(2026, 9, 10),
        segment=segment, total=Decimal("30000.00"), status="open", journal_entry=inv_je,
    )
    return {"limdon": limdon, "rfp": rfp}


def _ask(user, message, session_id=None):
    return AssistantService().process_query(user, message, session_id=session_id)


class TestComputedAnswers:
    def test_supplier_balance_answer(self, staff, books):
        resp = _ask(staff, "How much do we owe Limdon?")
        block = resp.get("answer_block")
        assert block is not None
        assert block["qid"] == "C25"
        assert block["kind"] == "answer"
        assert "55,000.00" in resp["text"]
        assert resp["results"] == []

    def test_open_payables_answer(self, staff, books):
        resp = _ask(staff, "unpaid invoices")
        block = resp.get("answer_block")
        assert block is not None
        assert block["qid"] == "D32"
        assert block["rows"], "AR default for a bare 'unpaid invoices'"

    def test_unpaid_rfps_go_ap(self, staff, books):
        resp = _ask(staff, "which unpaid rfps do we have")
        assert resp["answer_block"]["qid"] == "C26"

    def test_journal_lookup_via_rfp(self, staff, books):
        resp = _ask(staff, "What journal entry was recorded for A2026-0009?")
        block = resp["answer_block"]
        assert block["qid"] == "H65"
        assert "JE-2026-0101" in resp["text"]

    def test_net_income_uses_latest_activity_note(self, staff, books):
        resp = _ask(staff, "what is our net income")
        block = resp["answer_block"]
        assert block["qid"] == "K90"
        assert "September" in resp["text"] or "latest month" in resp["text"]

    def test_explicit_month_honored(self, staff, books):
        resp = _ask(staff, "net income for january 2026")
        block = resp["answer_block"]
        assert block["qid"] == "K90"
        assert "January 2026" in resp["text"]
        assert "latest month" not in resp["text"]


class TestLegacySearchUnchanged:
    """Every previously-working search question still behaves as before."""

    def test_latest_posted_rfp(self, staff, books):
        resp = _ask(staff, "latest posted rfp")
        assert resp.get("answer_block") is None
        assert resp["results"]
        assert any(g.get("module_name") == "RFPs" for g in resp["results"])

    def test_any_reference_from_supplier(self, staff, books):
        resp = _ask(staff, "any reference from Limdon?")
        assert resp.get("answer_block") is None
        assert resp["results"]

    def test_pending_cvs(self, staff, books):
        resp = _ask(staff, "What are the pending CVs?")
        assert resp.get("answer_block") is None
        assert "results" in resp  # empty data set -> no records, no crash

    def test_browse_suppliers(self, staff, books):
        resp = _ask(staff, "show all suppliers")
        assert resp.get("answer_block") is None
        assert resp["results"]

    def test_browse_sales_invoices(self, staff, books):
        resp = _ask(staff, "show all sales invoices")
        assert resp.get("answer_block") is None
        assert resp["results"]

    def test_journal_entries_last_week(self, staff, books):
        resp = _ask(staff, "Journal entries last week")
        assert resp.get("answer_block") is None
        assert resp["results"]


class TestRBACGate:
    def test_coo_denied_reports(self, coo, books):
        resp = _ask(coo, "what is our net income")
        block = resp.get("answer_block")
        assert block is not None
        assert block["kind"] == "denied"

    def test_staff_allowed_reports(self, staff, books):
        resp = _ask(staff, "what is our net income")
        assert resp["answer_block"]["kind"] == "answer"

    def test_coo_denied_payables(self, coo, books):
        resp = _ask(coo, "how much do we owe Limdon")
        assert resp["answer_block"]["kind"] == "denied"


class TestHistoryAndSession:
    def test_answer_persists_in_history(self, staff, books):
        first = _ask(staff, "how much do we owe Limdon")
        session_id = first["session_id"]
        history = AssistantService().get_history(session_id, staff)
        answers = [m.get("answer") for m in history if m.get("answer")]
        assert answers and answers[-1].get("qid") == "C25"

    def test_repeat_query_hits_cache_same_shape(self, staff, books):
        a = _ask(staff, "how much do we owe Limdon")
        b = _ask(staff, "how much do we owe Limdon")
        assert a["answer_block"]["qid"] == b["answer_block"]["qid"]


class TestRobustness:
    def test_gibberish_falls_back_gracefully(self, staff, books):
        resp = _ask(staff, "asdf qwerty zxcv")
        assert resp.get("answer_block") is None
        assert "text" in resp

    def test_empty_catalog_match_never_500(self, staff, books):
        assert _ask(staff, "what is the meaning of life") is not None