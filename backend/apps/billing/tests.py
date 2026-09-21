"""Billing module contract tests.

Covers the two billing types, balanced distribution grid, the draft ->
submitted -> approved -> posted lifecycle, and the RFP tracing requirements:
  * the posted JE's Note/Reference (``ref_number``) captures the RFP number;
  * credit lines on the unbilled receivable accounts 15550 / 15560 carry the
    RFP number AND the amount billed in their per-line reference.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.ap.models import RFPDocument, Supplier
from apps.billing.models import BillingDocument, BillingStatus, BillingType
from apps.billing.services import BillingService
from apps.core.exceptions import ValidationError
from apps.posting.models import GeneralLedger, JournalEntry, PostingStatus


@pytest.fixture
def billing_accounts(db):
    from apps.foundation.models import Account

    rows = [
        ("15550", "Reimbursable Expenses—Unbilled", "asset"),
        ("15560", "Due from Customers—Unbilled", "asset"),
        ("41010", "Sales-Retail", "revenue"),
        ("10010", "Cash on Hand", "asset"),
    ]
    return {
        code: Account.objects.create(
            code=code, name=name, account_type=atype, segment=Account.segment_for_code(code)
        )
        for code, name, atype in rows
    }


@pytest.fixture
def supplier(db, segment):
    return Supplier.objects.create(code="S001", name="STPC Holdings", default_segment=segment)


@pytest.fixture
def posted_rfp(db, segment, supplier):
    return RFPDocument.objects.create(
        ap_number="A0001",
        rfp_date=date(2026, 1, 15),
        payee=supplier,
        segment=segment,
        amount=Decimal("1000.00"),
        status="posted",
    )


def _lines(segment, accounts, *, dr="41010", cr="15560", amount="1000.00"):
    return [
        {"side": "dr", "segment": segment, "account": accounts[dr], "amount": amount,
         "description": "Service billed", "cost_center": "OS"},
        {"side": "cr", "segment": segment, "account": accounts[cr], "amount": amount,
         "description": "Unbilled receivable", "cost_center": "OS"},
    ]


def _create(company, segment, accounts, *, rfp=None, billing_type=BillingType.THIRD_PARTY,
            party="STPC Holdings", billing_no="BI-2026-0001", lines=None):
    return BillingService.create_billing(
        billing_no=billing_no,
        billing_date=date(2026, 2, 1),
        billing_type=billing_type,
        company=company,
        segment=segment,
        party_name=party,
        lines=lines or _lines(segment, accounts),
        rfp=rfp,
        user=None,
    )


class TestBillingCreation:
    def test_balanced_billing_created(self, company, segment, billing_accounts):
        billing = _create(company, segment, billing_accounts)
        assert billing.amount == Decimal("1000.00")
        assert billing.status == BillingStatus.DRAFT
        assert billing.lines.count() == 2
        assert billing.is_balanced

    def test_unbalanced_rejected(self, company, segment, billing_accounts):
        lines = [
            {"side": "dr", "segment": segment, "account": billing_accounts["41010"], "amount": "1000.00"},
            {"side": "cr", "segment": segment, "account": billing_accounts["15560"], "amount": "600.00"},
        ]
        with pytest.raises(ValidationError, match="does not balance"):
            _create(company, segment, billing_accounts, lines=lines)

    def test_no_debit_rejected(self, company, segment, billing_accounts):
        lines = [
            {"side": "cr", "segment": segment, "account": billing_accounts["15560"], "amount": "1000.00"},
        ]
        with pytest.raises(ValidationError, match="at least one debit"):
            _create(company, segment, billing_accounts, lines=lines)

    def test_zero_amount_rejected(self, company, segment, billing_accounts):
        lines = [
            {"side": "dr", "segment": segment, "account": billing_accounts["41010"], "amount": "0"},
            {"side": "cr", "segment": segment, "account": billing_accounts["15560"], "amount": "1000.00"},
        ]
        with pytest.raises(ValidationError, match="greater than zero"):
            _create(company, segment, billing_accounts, lines=lines)

    def test_invalid_billing_type_rejected(self, company, segment, billing_accounts):
        with pytest.raises(ValidationError, match="billing type"):
            _create(company, segment, billing_accounts, billing_type="bogus")


class TestBillingLifecycle:
    def test_full_lifecycle_posts_je(self, company, segment, billing_accounts, role_users, posted_rfp):
        billing = _create(company, segment, billing_accounts, rfp=posted_rfp)
        BillingService.submit(billing, user=role_users["staff"])
        billing.refresh_from_db()
        assert billing.status == BillingStatus.SUBMITTED

        BillingService.approve(billing, user=role_users["head"])
        billing.refresh_from_db()
        assert billing.status == BillingStatus.APPROVED

        entry = BillingService.post(billing, user=role_users["head"])
        billing.refresh_from_db()
        assert billing.status == BillingStatus.POSTED
        assert billing.journal_entry_id == entry.id
        assert entry.status == PostingStatus.POSTED
        assert entry.is_balanced
        assert GeneralLedger.objects.filter(entry=entry).count() == 2

    def test_non_head_cannot_approve(self, company, segment, billing_accounts, role_users):
        billing = _create(company, segment, billing_accounts)
        BillingService.submit(billing, user=role_users["staff"])
        with pytest.raises(ValidationError):
            BillingService.approve(billing, user=role_users["staff"])

    def test_post_requires_approved(self, company, segment, billing_accounts, role_users):
        billing = _create(company, segment, billing_accounts)
        with pytest.raises(ValidationError, match="must be approved"):
            BillingService.post(billing, user=role_users["head"])

    def test_reject_returns_to_draft(self, company, segment, billing_accounts, role_users):
        billing = _create(company, segment, billing_accounts)
        BillingService.submit(billing, user=role_users["staff"])
        BillingService.reject(billing, user=role_users["head"], note="Fix the account coding")
        billing.refresh_from_db()
        assert billing.status == BillingStatus.DRAFT
        assert billing.rejection_note == "Fix the account coding"

    def test_large_amount_posts_after_head_approval(self, company, segment, billing_accounts, role_users):
        lines = _lines(segment, billing_accounts, amount="150000.00")
        billing = _create(company, segment, billing_accounts, lines=lines)
        BillingService.submit(billing, user=role_users["staff"])
        BillingService.approve(billing, user=role_users["head"])
        entry = BillingService.post(billing, user=role_users["head"])
        assert entry.status == PostingStatus.POSTED


class TestRFPTracing:
    def test_je_header_captures_rfp_number(self, company, segment, billing_accounts, role_users, posted_rfp):
        billing = _create(company, segment, billing_accounts, rfp=posted_rfp)
        BillingService.submit(billing, user=role_users["staff"])
        BillingService.approve(billing, user=role_users["head"])
        entry = BillingService.post(billing, user=role_users["head"])

        assert entry.ref_number == "A0001"
        assert "RFP A0001" in entry.description
        assert entry.source_doc_type == "BILL"
        assert entry.source_doc_no == billing.billing_no

    def test_15560_credit_line_notes_rfp_and_amount(
        self, company, segment, billing_accounts, role_users, posted_rfp
    ):
        billing = _create(company, segment, billing_accounts, rfp=posted_rfp)
        BillingService.submit(billing, user=role_users["staff"])
        BillingService.approve(billing, user=role_users["head"])
        entry = BillingService.post(billing, user=role_users["head"])

        credit_line = entry.lines.get(account__code="15560")
        assert credit_line.reference == "RFP A0001 — billed 1,000.00"
        # A non-target line still notes the originating RFP.
        debit_line = entry.lines.get(account__code="41010")
        assert debit_line.reference == "RFP A0001"

    def test_15550_is_also_tagged(self, company, segment, billing_accounts, role_users, posted_rfp):
        lines = _lines(segment, billing_accounts, dr="41010", cr="15550")
        billing = _create(company, segment, billing_accounts, rfp=posted_rfp, lines=lines)
        BillingService.submit(billing, user=role_users["staff"])
        BillingService.approve(billing, user=role_users["head"])
        entry = BillingService.post(billing, user=role_users["head"])
        assert entry.lines.get(account__code="15550").reference == "RFP A0001 — billed 1,000.00"

    def test_without_rfp_no_references(self, company, segment, billing_accounts, role_users):
        billing = _create(company, segment, billing_accounts)
        BillingService.submit(billing, user=role_users["staff"])
        BillingService.approve(billing, user=role_users["head"])
        entry = BillingService.post(billing, user=role_users["head"])
        assert entry.ref_number == ""
        assert all(line.reference == "" for line in entry.lines.all())


class TestApprovalQueue:
    def test_submitted_billing_appears_in_head_queue(self, company, segment, billing_accounts, role_users):
        from apps.core.approvals import billing_queue

        billing = _create(company, segment, billing_accounts)
        BillingService.submit(billing, user=role_users["staff"])
        items = billing_queue({"head"})
        assert any(item["number"] == billing.billing_no for item in items)


class TestBillingAPI:
    def test_api_create_and_post(self, company, segment, billing_accounts, role_users, posted_rfp):
        from rest_framework.test import APIClient

        staff = APIClient()
        staff.force_authenticate(user=role_users["staff"])
        resp = staff.post(
            "/api/v1/billing/billings/",
            {
                "billing_type": "stpc",
                "billing_date": "2026-02-01",
                "segment": segment.id,
                "party_name": "STPC Holdings",
                "rfp": posted_rfp.id,
                "lines": [
                    {"side": "dr", "account_code": "41010", "segment": segment.id, "amount": "1000.00"},
                    {"side": "cr", "account_code": "15560", "segment": segment.id, "amount": "1000.00"},
                ],
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        bid = resp.json()["id"]

        head = APIClient()
        head.force_authenticate(user=role_users["head"])
        assert head.post(f"/api/v1/billing/billings/{bid}/submit/").status_code == 200
        assert head.post(f"/api/v1/billing/billings/{bid}/approve/").status_code == 200
        posted = head.post(f"/api/v1/billing/billings/{bid}/post/")
        assert posted.status_code == 200, posted.content

        entry = JournalEntry.objects.get(source_doc_no="BI-2026-0001")
        assert entry.ref_number == "A0001"
        assert entry.lines.get(account__code="15560").reference == "RFP A0001 — billed 1,000.00"


@pytest.mark.django_db
class TestBillingReversalUI:
    """Reversal parity: a posted Billing's own detail screen offers the
    Request-reversal action (shared partial), the pending banner returns to the
    billing, and the generic JE screen no longer duplicates the trigger."""

    def _post_billing(self, company, segment, billing_accounts, role_users):
        billing = _create(company, segment, billing_accounts)
        BillingService.submit(billing, user=role_users["staff"])
        BillingService.approve(billing, user=role_users["head"])
        entry = BillingService.post(billing, user=role_users["head"])
        billing.refresh_from_db()
        return billing, entry

    def test_detail_offers_reversal_and_pending_returns(self, client, company, segment, billing_accounts, role_users):
        billing, entry = self._post_billing(company, segment, billing_accounts, role_users)
        staff = role_users["staff"]
        head = role_users["head"]

        client.force_login(staff)
        body = client.get(f"/billing/{billing.pk}/").content.decode()
        assert "Request reversal" in body
        assert "bg-amber-600" in body          # modal submit button styling present

        resp = client.post(
            f"/journal/{entry.pk}/reverse/",
            {"reason": "duplicate billing", "next": f"/billing/{billing.pk}/"},
        )
        assert resp.status_code == 302
        assert resp.url == f"/billing/{billing.pk}/"
        body = client.get(f"/billing/{billing.pk}/").content.decode()
        assert "Reversal requested" in body
        assert "Approve reversal" not in body   # staff can't approve their own request

        client.force_login(head)
        body = client.get(f"/billing/{billing.pk}/").content.decode()
        assert "Approve reversal" in body

    def test_source_doc_entry_hides_je_detail_reversal_button(self, client, company, segment, billing_accounts, role_users):
        billing, entry = self._post_billing(company, segment, billing_accounts, role_users)
        client.force_login(role_users["head"])
        body = client.get(f"/journal/{entry.pk}/").content.decode()
        # the reversal trigger lives on the Billing screen now, not on the JE
        assert "Open Billing" in body
        assert ">Request reversal<" not in body

    def test_head_approves_reversal_from_billing(self, client, company, segment, billing_accounts, role_users):
        billing, entry = self._post_billing(company, segment, billing_accounts, role_users)
        staff = role_users["staff"]
        head = role_users["head"]
        client.force_login(staff)
        client.post(
            f"/journal/{entry.pk}/reverse/",
            {"reason": "wrong amount", "next": f"/billing/{billing.pk}/"},
        )
        from apps.posting.models import ReversalRequest

        req = ReversalRequest.objects.get(entry=entry)
        client.force_login(head)
        resp = client.post(
            f"/journal/reversal/{req.pk}/approve/",
            {"next": f"/billing/{billing.pk}/"},
        )
        assert resp.status_code == 302
        assert resp.url == f"/billing/{billing.pk}/"
        entry.refresh_from_db()
        assert entry.status == PostingStatus.REVERSED
        body = client.get(f"/billing/{billing.pk}/").content.decode()
        assert "reversed" in body.lower()