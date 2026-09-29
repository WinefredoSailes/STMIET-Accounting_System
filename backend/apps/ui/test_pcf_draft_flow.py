"""Petty cash voucher DRAFT step (RFP-parity preparer flow).

The voucher form saves a draft the custodian can edit freely; only
``Submit for approval`` moves it to ``requested`` and onto the Head's queue.
Drafts must be invisible to the approval inbox and refused by every
approver-side endpoint; the API mirrors the RFP contract (draft + preparer
only for edit/delete, explicit submit).
"""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.ap.models import Supplier
from apps.cash.models import PCFReplenishment, PettyCashFund
from apps.core.approvals import pending_approval_queue
from apps.foundation.models import UserProfile
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db


@pytest.fixture
def fund(db, company, accounts, role_users):
    return PettyCashFund.objects.create(
        fund_code="PCF-DRF", name="Draft Flow Fund", custodian=role_users["staff"],
        custodian_name="Staff", imprest_amount="20000.00",
        gl_account=accounts["10010"], company=company, is_active=True,
    )


@pytest.fixture
def supplier(db, segment):
    return Supplier.objects.create(name="Draftline Supplies", tin="999-888", default_segment=segment)


@pytest.fixture
def other_staff(db):
    u = get_user_model().objects.create_user(username="otherstaff", password="x")
    UserProfile.objects.create(user=u, approval_role="staff")
    return u


def _form(fund, accounts, supplier, **over):
    data = {
        "fund": fund.pk,
        "payee_name": "Office Clerk",
        "request_date": "2026-09-05",
        "reference": "REF-DRF",
        "exp_account": [accounts["61100"].code],
        "exp_debit": ["850.00"],
        "exp_credit": [""],
        "exp_description": ["Panlabot ink"],
        "exp_segment": ["DHPP"],
        "exp_cost_center": ["OS"],
        "exp_supplier": [supplier.pk],
    }
    data.update(over)
    return data


def _create(client, fund, accounts, supplier):
    resp = client.post("/cash/pcf/replenish/", _form(fund, accounts, supplier))
    assert resp.status_code == 302
    return PCFReplenishment.objects.get()


def _pcf_items(user):
    return [i for i in pending_approval_queue(user) if i["kind"] == "pcf"]


class TestCreateLandsDraft:
    def test_form_creates_draft_off_queue(self, client, role_users, fund, accounts, supplier):
        from django.test import Client as PlainClient

        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        assert replen.status == "draft"
        assert replen.voucher_no.startswith(f"PCV-{date.today().year}-")
        # the Head sees nothing: queue empty, and the inbox page has no rows for it
        assert _pcf_items(role_users["head"]) == []
        head_client = PlainClient()
        head_client.force_login(role_users["head"])
        body = head_client.get("/approvals/").content.decode()
        assert replen.voucher_no not in body

    def test_detail_shows_draft_actions_to_custodian(self, client, role_users, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        body = client.get(f"/cash/pcf/replenishments/{replen.id}/").content.decode()
        assert "Draft — not yet submitted for approval" in body
        assert f"/cash/pcf/replenishments/{replen.id}/edit/" in body
        assert f"/cash/pcf/replenishments/{replen.id}/submit/" in body
        assert "Submit for approval" in body

    def test_detail_hides_actions_from_head(self, client, role_users, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        client.force_login(role_users["head"])
        body = client.get(f"/cash/pcf/replenishments/{replen.id}/").content.decode()
        assert "not on the Head's approval queue yet" in body
        # no approver controls on a draft
        assert f"/cash/pcf/replenishments/{replen.id}/approve/" not in body
        assert "Reject with note" not in body

    def test_register_shows_draft_badge_filter_and_card(self, client, role_users, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        _create(client, fund, accounts, supplier)
        body = client.get("/cash/pcf/replenishments/").content.decode()
        assert "bg-surface-100 text-surface-700" in body  # neutral draft badge
        assert 'value="draft"' in body                    # register filter choice
        assert "Drafts" in body                           # stat card


class TestDraftCannotBeProcessed:
    """Every approver-side verb must refuse a draft (status unchanged)."""

    @pytest.mark.parametrize("verb", ["approve", "reject", "post"])
    def test_head_verbs_refuse_draft(self, client, role_users, fund, accounts, supplier, verb):
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        client.force_login(role_users["head"])
        data = {"note": "nope"} if verb == "reject" else {}
        client.post(f"/cash/pcf/replenishments/{replen.id}/{verb}/", data)
        replen.refresh_from_db()
        assert replen.status == "draft"

    def test_service_refuses_draft_verbs(self, fund, accounts, role_users):
        from apps.cash.services import PCFService
        from apps.core.exceptions import ValidationError

        replen = PCFService.request_replenishment(
            fund, [{"account_code": accounts["61100"].code, "amount": "100.00", "description": "x"}],
            user=role_users["staff"],
        )
        with pytest.raises(ValidationError):
            PCFService.approve_replenishment(replen, user=role_users["head"])
        with pytest.raises(ValidationError):
            PCFService.reject_replenishment(replen, user=role_users["head"], note="x")
        with pytest.raises(ValidationError):
            PCFService.post_replenishment(replen, user=role_users["head"])


class TestEditDraft:
    def test_edit_form_prefills_and_saves_as_draft(self, client, role_users, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        body = client.get(f"/cash/pcf/replenishments/{replen.id}/edit/").content.decode()
        assert "Panlabot ink" in body          # description prefilled
        assert 'value="850.00"' in body        # debit prefilled
        assert "REF-DRF" in body               # reference prefilled
        assert "Save changes" in body          # draft label, not resubmit
        assert "Save &amp; resubmit" not in body

        form = _form(
            fund, accounts, supplier,
            exp_description=["Smoother ink"], exp_debit=["1,250.00"],
        )
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/edit/", form)
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "draft"
        assert replen.amount == Decimal("1250.00")
        assert replen.expenses[0]["description"] == "Smoother ink"

    def test_non_preparer_cannot_edit(self, client, role_users, other_staff, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        client.force_login(other_staff)
        assert client.get(f"/cash/pcf/replenishments/{replen.id}/edit/").status_code == 403
        assert client.post(f"/cash/pcf/replenishments/{replen.id}/submit/").status_code == 302
        replen.refresh_from_db()
        assert replen.status == "draft"  # submit by stranger did nothing (service gate)


class TestSubmitDraft:
    def test_submit_queues_for_head(self, client, role_users, fund, accounts, supplier):
        from django.test import Client as PlainClient

        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/submit/")
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "requested"
        assert [i["doc"].id for i in _pcf_items(role_users["head"])] == [replen.id]
        head_client = PlainClient()
        head_client.force_login(role_users["head"])
        body = head_client.get("/approvals/").content.decode()
        assert replen.voucher_no in body
        assert f"/cash/pcf/replenishments/{replen.id}/approve/" in body
        assert f"/cash/pcf/replenishments/{replen.id}/reject/" in body

    def test_double_submit_refused(self, client, role_users, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        client.post(f"/cash/pcf/replenishments/{replen.id}/submit/")
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/submit/", follow=True)
        assert "Only draft vouchers can be submitted" in resp.content.decode()
        replen.refresh_from_db()
        assert replen.status == "requested"


class TestFullRoundTrip:
    def test_draft_edit_submit_reject_revise_approve(self, client, role_users, fund, accounts, supplier):
        """draft -> (edit) -> requested -> rejected -> (revise) -> requested
        -> approved -> CONSO-posted, entirely through the UI."""
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)

        client.post(
            f"/cash/pcf/replenishments/{replen.id}/edit/",
            _form(fund, accounts, supplier, exp_debit=["900.00"], exp_description=["Ink v2"]),
        )
        replen.refresh_from_db()
        assert (replen.status, str(replen.amount)) == ("draft", "900.00")

        client.post(f"/cash/pcf/replenishments/{replen.id}/submit/")
        replen.refresh_from_db()
        assert replen.status == "requested"

        client.force_login(role_users["head"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/reject/", {"note": "Too high this week"})
        replen.refresh_from_db()
        assert replen.status == "rejected"

        client.force_login(role_users["staff"])
        client.post(
            f"/cash/pcf/replenishments/{replen.id}/revise/",
            _form(fund, accounts, supplier, exp_debit=["450.00"], exp_description=["Ink (trimmed)"]),
        )
        replen.refresh_from_db()
        assert replen.status == "requested"
        assert replen.amount == Decimal("450.00")
        assert replen.rejection_note == ""

        client.force_login(role_users["head"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/approve/")
        replen.refresh_from_db()
        assert replen.status == "approved"
        resp = client.post(f"/ap/conso/{replen.conso_id}/post/")
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "posted"


class TestApiDraftContract:
    def test_api_replenish_creates_draft_and_submit_queues(self, role_users, fund, accounts):
        api = APIClient()
        api.force_authenticate(user=role_users["staff"])
        resp = api.post(
            f"/api/v1/cash/pcf-funds/{fund.pk}/replenish/",
            {"expenses": [{"account_code": accounts["61100"].code, "amount": "300.00", "description": "x"}]},
            format="json",
        )
        assert resp.status_code == 201
        replen_id = resp.json()["id"]
        assert resp.json()["status"] == "draft"

        resp = api.post(f"/api/v1/cash/pcf-replenishments/{replen_id}/submit/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "requested"

    def test_status_is_not_client_writable(self, role_users, fund, accounts):
        api = APIClient()
        api.force_authenticate(user=role_users["staff"])
        resp = api.post(
            f"/api/v1/cash/pcf-funds/{fund.pk}/replenish/",
            {"expenses": [{"account_code": accounts["61100"].code, "amount": "100.00", "description": "x"}]},
            format="json",
        )
        pk = resp.json()["id"]
        resp = api.patch(f"/api/v1/cash/pcf-replenishments/{pk}/", {"status": "approved"}, format="json")
        assert resp.status_code == 200
        assert resp.json()["status"] == "draft"

    def test_edit_and_delete_gated_to_draft_preparer(self, role_users, other_staff, fund, accounts):
        api = APIClient()
        api.force_authenticate(user=role_users["staff"])
        resp = api.post(
            f"/api/v1/cash/pcf-funds/{fund.pk}/replenish/",
            {"expenses": [{"account_code": accounts["61100"].code, "amount": "100.00", "description": "x"}]},
            format="json",
        )
        pk = resp.json()["id"]

        # preparer may edit while draft
        resp = api.patch(f"/api/v1/cash/pcf-replenishments/{pk}/", {"reference": "R1"}, format="json")
        assert resp.status_code == 200
        assert resp.json()["reference"] == "R1"

        # a stranger may not touch it
        other = APIClient()
        other.force_authenticate(user=other_staff)
        assert other.patch(f"/api/v1/cash/pcf-replenishments/{pk}/", {"reference": "R2"}, format="json").status_code == 403
        assert other.delete(f"/api/v1/cash/pcf-replenishments/{pk}/").status_code == 403

        # after it leaves the desk, edits/deletes are refused even for the preparer
        api.post(f"/api/v1/cash/pcf-replenishments/{pk}/submit/")
        assert api.patch(f"/api/v1/cash/pcf-replenishments/{pk}/", {"reference": "R3"}, format="json").status_code == 403
        assert api.delete(f"/api/v1/cash/pcf-replenishments/{pk}/").status_code == 403

    def test_preparer_can_discard_own_draft(self, role_users, fund, accounts):
        api = APIClient()
        api.force_authenticate(user=role_users["staff"])
        resp = api.post(
            f"/api/v1/cash/pcf-funds/{fund.pk}/replenish/",
            {"expenses": [{"account_code": accounts["61100"].code, "amount": "50.00", "description": "x"}]},
            format="json",
        )
        pk = resp.json()["id"]
        assert api.delete(f"/api/v1/cash/pcf-replenishments/{pk}/").status_code == 204
        assert not PCFReplenishment.objects.filter(pk=pk).exists()
