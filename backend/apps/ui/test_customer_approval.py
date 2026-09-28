"""Customer master approval flow (staff adds -> Head approves).

Every customer created by accounting staff lands ``pending`` and is invisible
to transaction pickers until the Accounting & Finance Head approves it; the
Head's own creations are approved immediately (no approval round). A rejected
customer goes back to its creator, who edits and resubmits. Mirrors the
transfer/RFP reject-with-note ergonomics.
"""

import pytest
from rest_framework.test import APIClient

from apps.ar.models import Customer, CustomerApprovalStatus
from apps.ar.services import CustomerService
from apps.core.approvals import pending_approval_queue
from apps.core.exceptions import ValidationError

pytestmark = pytest.mark.django_db

FORM = {
    "code": "C900",
    "name": "Hopedale Fuel Corp",
    "group": "fuel",
    "pricing_tier": "regular",
    "tin": "251-442-0081",
    "address": "Hopedale",
    "contact_no": "0917-000-0000",
    "owner_name": "Dale Hopedale",
    "notes": "",
}


def _items(user):
    return [i for i in pending_approval_queue(user) if i["kind"] == "customer"]


class TestCreateApprovalRule:
    def test_staff_creation_lands_pending(self, client, role_users):
        client.force_login(role_users["staff"])
        client.post("/ar/customers/new/", FORM)
        c = Customer.objects.get(code="C900")
        assert c.approval_status == CustomerApprovalStatus.PENDING
        assert c.approved_by_id is None
        assert c.created_by_id == role_users["staff"].id

    def test_head_creation_is_auto_approved(self, client, role_users):
        client.force_login(role_users["head"])
        client.post("/ar/customers/new/", FORM)
        c = Customer.objects.get(code="C900")
        assert c.approval_status == CustomerApprovalStatus.APPROVED
        assert c.approved_by_id == role_users["head"].id
        assert _items(role_users["head"]) == []

    def test_pending_customer_enters_head_inbox_only(self, client, role_users):
        client.force_login(role_users["staff"])
        client.post("/ar/customers/new/", FORM)
        assert [i["doc"].code for i in _items(role_users["head"])] == ["C900"]
        assert _items(role_users["staff"]) == []
        body = client.get("/approvals/").content.decode()  # staff inbox: none
        assert "Hopedale Fuel Corp" not in body
        client.force_login(role_users["head"])
        body = client.get("/approvals/").content.decode()
        assert f"/ar/customers/{Customer.objects.get(code='C900').pk}/approve/" in body
        assert f"/ar/customers/{Customer.objects.get(code='C900').pk}/reject/" in body


class TestPendingIsInactive:
    def test_hidden_from_customer_picker(self, client, role_users):
        client.force_login(role_users["staff"])
        client.post("/ar/customers/new/", FORM)
        resp = client.get("/foundation/customer-options/", {"q": "Hopedale"})
        assert "Hopedale Fuel Corp" not in resp.content.decode()

    def test_approved_customer_shows_in_picker(self, client, role_users):
        client.force_login(role_users["staff"])
        client.post("/ar/customers/new/", FORM)
        c = Customer.objects.get(code="C900")
        client.force_login(role_users["head"])
        client.post(f"/ar/customers/{c.pk}/approve/")
        resp = client.get("/foundation/customer-options/", {"q": "Hopedale"})
        assert "Hopedale Fuel Corp" in resp.content.decode()

    def test_service_blocks_transacting_on_pending(self, role_users):
        clientless = CustomerService.create_customer(created_by=role_users["staff"], **FORM)
        assert clientless.approval_status == CustomerApprovalStatus.PENDING
        with pytest.raises(ValidationError, match="not approved"):
            CustomerService.require_approved(clientless)


class TestRejectAndResubmit:
    def test_reject_requires_note(self, client, role_users):
        client.force_login(role_users["staff"])
        client.post("/ar/customers/new/", FORM)
        c = Customer.objects.get(code="C900")
        client.force_login(role_users["head"])
        client.post(f"/ar/customers/{c.pk}/reject/", {"note": ""})
        c.refresh_from_db()
        assert c.approval_status == CustomerApprovalStatus.PENDING

    def test_head_rejects_and_creator_resubmits(self, client, role_users):
        client.force_login(role_users["staff"])
        client.post("/ar/customers/new/", FORM)
        c = Customer.objects.get(code="C900")
        client.force_login(role_users["head"])
        client.post(f"/ar/customers/{c.pk}/reject/", {"note": "Duplicate of C100"})
        c.refresh_from_db()
        assert c.approval_status == CustomerApprovalStatus.REJECTED
        assert c.rejected_by_id == role_users["head"].id
        assert _items(role_users["head"]) == []
        # rejected stays hidden from the picker too
        resp = client.get("/foundation/customer-options/", {"q": "Hopedale"})
        assert "Hopedale Fuel Corp" not in resp.content.decode()
        # the creator edits & resubmits
        client.force_login(role_users["staff"])
        form = dict(FORM, name="Hopedale Fuel Corporation")
        client.post(f"/ar/customers/{c.pk}/update/", form)
        c.refresh_from_db()
        assert c.approval_status == CustomerApprovalStatus.PENDING
        assert c.name == "Hopedale Fuel Corporation"
        assert c.rejection_note == ""
        assert c.rejected_by_id is None
        assert [i["doc"].id for i in _items(role_users["head"])] == [c.id]

    def test_stranger_cannot_edit(self, client, role_users, company):
        other = CustomerService.create_customer(created_by=role_users["staff"], **FORM)
        client.force_login(role_users["staff"])
        resp = client.post(f"/ar/customers/{other.pk}/update/", dict(FORM, code="C901"))
        assert resp.status_code == 403
        other.refresh_from_db()
        assert other.code == "C900"

    def test_approve_is_head_only(self, client, role_users):
        c = CustomerService.create_customer(created_by=role_users["staff"], **FORM)
        client.force_login(role_users["staff"])
        client.post(f"/ar/customers/{c.pk}/approve/")
        c.refresh_from_db()
        assert c.approval_status == CustomerApprovalStatus.PENDING


class TestApiRule:
    def test_api_staff_create_pending_head_create_approved(self, role_users):
        staff_api = APIClient()
        staff_api.force_authenticate(user=role_users["staff"])
        resp = staff_api.post("/api/v1/ar/customers/", FORM, format="json")
        assert resp.status_code == 201
        assert resp.json()["approval_status"] == "pending"

        head_api = APIClient()
        head_api.force_authenticate(user=role_users["head"])
        resp = head_api.post(
            "/api/v1/ar/customers/", dict(FORM, code="C902"), format="json"
        )
        assert resp.status_code == 201
        assert resp.json()["approval_status"] == "approved"

    def test_api_status_not_client_writable(self, role_users):
        staff_api = APIClient()
        staff_api.force_authenticate(user=role_users["staff"])
        resp = staff_api.post(
            "/api/v1/ar/customers/",
            dict(FORM, approval_status="approved"),
            format="json",
        )
        assert resp.json()["approval_status"] == "pending"

    def test_api_approve_reject_gated(self, role_users):
        c = CustomerService.create_customer(created_by=role_users["staff"], **FORM)
        staff_api = APIClient()
        staff_api.force_authenticate(user=role_users["staff"])
        resp = staff_api.post(f"/api/v1/ar/customers/{c.pk}/approve/")
        assert resp.status_code == 422
        head_api = APIClient()
        head_api.force_authenticate(user=role_users["head"])
        resp = head_api.post(f"/api/v1/ar/customers/{c.pk}/reject/", {"note": "bad TIN"})
        assert resp.status_code == 200
        c.refresh_from_db()
        assert c.approval_status == CustomerApprovalStatus.REJECTED

    def test_api_pending_cannot_be_invoiced(self, role_users, segment, accounts):
        from apps.foundation.models import Account

        c = CustomerService.create_customer(created_by=role_users["head"], **FORM)
        head_api = APIClient()
        head_api.force_authenticate(user=role_users["head"])
        # snapshot the approved state, then push it back to pending manually
        Customer.objects.filter(pk=c.pk).update(approval_status="pending")
        c.refresh_from_db()
        resp = head_api.post(
            "/api/v1/ar/invoices/",
            {
                "customer": c.pk,
                "transaction_date": "2026-09-01",
                "segment": segment.pk,
                "total": "100.00",
                "is_paid_on_delivery": True,
            },
            format="json",
        )
        assert resp.status_code == 400
        assert "not approved" in str(resp.json())


class TestExistingWorkflowUnaffected:
    def test_orm_created_customers_stay_active(self, db):
        c = Customer.objects.create(code="C100", name="Legacy Co")
        assert c.approval_status == CustomerApprovalStatus.APPROVED
        assert CustomerService.require_approved(c) is c
