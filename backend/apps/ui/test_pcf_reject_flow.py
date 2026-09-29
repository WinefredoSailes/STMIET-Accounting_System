"""Petty cash voucher reject/revise flow (head approval gap fix).

The head could approve PCV replenishments but had no Reject option anywhere —
unlike every other approval flow. Covers: the inbox Reject button for `pcf`
items, the head-only reject endpoint (note required), the rejected banner on
the detail page, and the custodian's edit-and-resubmit round trip.
"""

from datetime import date

import pytest

from apps.ap.models import Supplier
from apps.cash.models import PCFReplenishment, PettyCashFund
from apps.core.approvals import pending_approval_queue

pytestmark = pytest.mark.django_db


@pytest.fixture
def fund(db, company, accounts, role_users):
    return PettyCashFund.objects.create(
        fund_code="PCF-REJ", name="Reject Flow Fund", custodian=role_users["staff"],
        custodian_name="Staff", imprest_amount="20000.00",
        gl_account=accounts["10010"], company=company, is_active=True,
    )


@pytest.fixture
def supplier(db, segment):
    return Supplier.objects.create(name="Alpha Supplies", tin="123-456", default_segment=segment)


@pytest.fixture
def replen(fund, role_users, accounts, supplier):
    return PCFReplenishment.objects.create(
        fund=fund,
        request_date=date(2026, 9, 2),
        amount="500.00",
        payee_name="Clerk",
        reference="REF-REJ",
        voucher_no="PCV-2026-0001",
        requested_by=role_users["staff"],
        status="requested",
        expenses=[
            {
                "account_code": accounts["61100"].code,
                "side": "dr",
                "amount": "500.00",
                "description": "Supplies",
                "segment": "DHPP",
                "cost_center": "OS",
                "supplier_id": supplier.pk,
                "business_name": supplier.name,
                "tin": supplier.tin,
            }
        ],
    )


def _pcf_items(user):
    return [i for i in pending_approval_queue(user) if i["kind"] == "pcf"]


class TestInboxReject:
    def test_pcf_inbox_rows_get_reject_button(self, client, replen, role_users):
        client.force_login(role_users["head"])
        body = client.get("/approvals/").content.decode()
        assert "data-inbox-reject" in body
        assert f"/cash/pcf/replenishments/{replen.id}/reject/" in body

    def test_queue_drops_after_reject(self, client, replen, role_users):
        client.force_login(role_users["head"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/reject/", {"note": "No receipts"})
        assert _pcf_items(role_users["head"]) == []

    def test_queue_reappears_after_resubmit(self, client, replen, role_users, fund, accounts, supplier):
        client.force_login(role_users["head"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/reject/", {"note": "No receipts"})
        client.force_login(role_users["staff"])
        client.post(
            f"/cash/pcf/replenishments/{replen.id}/revise/",
            {
                "fund": fund.pk,
                "payee_name": "Clerk",
                "reference": "REF-REJ",
                "request_date": "2026-09-02",
                "exp_account": [accounts["61100"].code],
                "exp_debit": ["500.00"],
                "exp_credit": [""],
                "exp_description": ["Supplies"],
                "exp_segment": ["DHPP"],
                "exp_cost_center": ["OS"],
                "exp_supplier": [supplier.pk],
            },
        )
        assert [i["doc"].id for i in _pcf_items(role_users["head"])] == [replen.id]


class TestRejectEndpoint:
    def test_head_rejects_with_note(self, client, replen, role_users):
        client.force_login(role_users["head"])
        client.post(
            f"/cash/pcf/replenishments/{replen.id}/reject/", {"note": "Attach ORs"}
        )
        replen.refresh_from_db()
        assert replen.status == "rejected"
        assert replen.rejected_by_id == role_users["head"].id
        assert replen.rejection_note == "Attach ORs"

    def test_note_is_required(self, client, replen, role_users):
        client.force_login(role_users["head"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/reject/", {"note": ""})
        replen.refresh_from_db()
        assert replen.status == "requested"

    def test_staff_cannot_reject(self, client, replen, role_users):
        client.force_login(role_users["staff"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/reject/", {"note": "nope"})
        replen.refresh_from_db()
        assert replen.status == "requested"

    def test_rejected_banner_shows_on_detail(self, client, replen, role_users):
        client.force_login(role_users["head"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/reject/", {"note": "Attach ORs"})
        client.force_login(role_users["staff"])
        body = client.get(f"/cash/pcf/replenishments/{replen.id}/").content.decode()
        assert "Attach ORs" in body
        assert "Rejected — returned for revision" in body
        assert f"/cash/pcf/replenishments/{replen.id}/revise/" in body

    def test_register_shows_rejected_badge(self, client, replen, role_users):
        client.force_login(role_users["head"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/reject/", {"note": "Attach ORs"})
        body = client.get("/cash/pcf/replenishments/").content.decode()
        assert "bg-rose-100 text-rose-800" in body
        assert ">rejected" in body or "rejected" in body


class TestEditAndResubmit:
    def test_custodian_edits_and_resubmits(self, client, replen, role_users, fund, accounts, supplier):
        client.force_login(role_users["head"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/reject/", {"note": "Amount wrong"})
        client.force_login(role_users["staff"])
        form = {
            "fund": fund.pk,
            "payee_name": "Clerk Fixed",
            "reference": "REF-REJ",
            "request_date": "2026-09-03",
            "exp_account": ["", accounts["61100"].code],
            "exp_debit": ["", "750.00"],
            "exp_credit": ["", ""],
            "exp_description": ["", "Supplies (revised)"],
            "exp_segment": ["", "DHPP"],
            "exp_cost_center": ["", "OS"],
            "exp_supplier": ["", supplier.pk],
        }
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/revise/", form)
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "requested"
        assert str(replen.amount) == "750.00"
        assert replen.rejection_note == ""
        assert replen.rejected_by_id is None
        assert replen.expenses[0]["description"] == "Supplies (revised)"

    def test_revise_form_prefills_rejected_values(self, client, replen, role_users):
        client.force_login(role_users["head"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/reject/", {"note": "Amount wrong"})
        client.force_login(role_users["staff"])
        body = client.get(f"/cash/pcf/replenishments/{replen.id}/revise/").content.decode()
        assert "Amount wrong" in body
        assert "value=\"500.00\"" in body
        assert "REF-REJ" in body

    def test_requested_voucher_is_not_editable(self, client, replen, role_users):
        """Once submitted it is off the preparer's desk: edits only via the
        reject/revise cycle (same contract as RFP)."""
        client.force_login(role_users["staff"])
        resp = client.get(f"/cash/pcf/replenishments/{replen.id}/edit/", follow=True)
        replen.refresh_from_db()
        assert replen.status == "requested"
        assert "Only draft vouchers can be edited" in resp.content.decode()

    def test_other_users_cannot_open_revise(self, client, replen, company, accounts, role_users):
        client.force_login(role_users["head"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/reject/", {"note": "x"})
        resp = client.get(f"/cash/pcf/replenishments/{replen.id}/revise/")
        replen.refresh_from_db()
        assert resp.status_code == 403
        assert replen.status == "rejected"


class TestApproveGuardsUnchanged:
    def test_approve_still_works(self, client, replen, role_users):
        """The pre-existing approve path must not regress."""
        client.force_login(role_users["head"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/approve/")
        replen.refresh_from_db()
        assert replen.status == "approved"
        assert replen.approved_at is not None
