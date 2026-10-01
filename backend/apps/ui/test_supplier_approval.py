"""Supplier master approval flow (staff adds -> Head approves).

Mirrors the customer master rule: every supplier created by accounting staff
lands ``pending`` and is invisible to transaction pickers until the Accounting
& Finance Head approves it; the Head's own creations are approved immediately.
A rejected supplier goes back to its creator, who edits and resubmits.
"""

import pytest
from rest_framework.test import APIClient

from apps.ap.models import Supplier, SupplierApprovalStatus
from apps.ap.services import SupplierService
from apps.core.approvals import pending_approval_queue
from apps.core.exceptions import ValidationError

pytestmark = pytest.mark.django_db

FORM = {
    "code": "S900",
    "name": "Hopedale Fuel Corp",
    "supplier_type": "service",
    "tin": "251-442-0081",
    "address": "Hopedale",
    "contact_no": "0917-000-0000",
    "owner_name": "Dale Hopedale",
    "email": "dale@hopedale.test",
    "contact_person": "Dale",
    "position": "Owner",
}


def _items(user):
    return [i for i in pending_approval_queue(user) if i["kind"] == "supplier"]


class TestCreateApprovalRule:
    def test_staff_creation_lands_pending(self, client, role_users, segment):
        client.force_login(role_users["staff"])
        client.post("/ap/suppliers/new/", dict(FORM, default_segment=segment.id))
        s = Supplier.objects.get(code="S900")
        assert s.approval_status == SupplierApprovalStatus.PENDING
        assert s.approved_by_id is None
        assert s.created_by_id == role_users["staff"].id

    def test_head_creation_is_auto_approved(self, client, role_users, segment):
        client.force_login(role_users["head"])
        client.post("/ap/suppliers/new/", dict(FORM, default_segment=segment.id))
        s = Supplier.objects.get(code="S900")
        assert s.approval_status == SupplierApprovalStatus.APPROVED
        assert s.approved_by_id == role_users["head"].id
        assert _items(role_users["head"]) == []

    def test_pending_supplier_enters_head_inbox_only(self, client, role_users, segment):
        client.force_login(role_users["staff"])
        client.post("/ap/suppliers/new/", dict(FORM, default_segment=segment.id))
        assert [i["doc"].code for i in _items(role_users["head"])] == ["S900"]
        assert _items(role_users["staff"]) == []
        body = client.get("/approvals/").content.decode()  # staff inbox: none
        assert "Hopedale Fuel Corp" not in body
        client.force_login(role_users["head"])
        body = client.get("/approvals/").content.decode()
        assert f"/ap/suppliers/{Supplier.objects.get(code='S900').pk}/approve/" in body
        assert f"/ap/suppliers/{Supplier.objects.get(code='S900').pk}/reject/" in body


class TestPendingIsInactive:
    def test_hidden_from_supplier_picker(self, client, role_users, segment):
        client.force_login(role_users["staff"])
        client.post("/ap/suppliers/new/", dict(FORM, default_segment=segment.id))
        resp = client.get("/foundation/supplier-options/", {"q": "Hopedale"})
        assert "Hopedale Fuel Corp" not in resp.content.decode()

    def test_approved_supplier_shows_in_picker(self, client, role_users, segment):
        client.force_login(role_users["staff"])
        client.post("/ap/suppliers/new/", dict(FORM, default_segment=segment.id))
        s = Supplier.objects.get(code="S900")
        client.force_login(role_users["head"])
        client.post(f"/ap/suppliers/{s.pk}/approve/")
        resp = client.get("/foundation/supplier-options/", {"q": "Hopedale"})
        assert "Hopedale Fuel Corp" in resp.content.decode()

    def test_service_blocks_transacting_on_pending(self, role_users, segment):
        clientless = SupplierService.create_supplier(
            created_by=role_users["staff"], default_segment=segment, **FORM
        )
        assert clientless.approval_status == SupplierApprovalStatus.PENDING
        with pytest.raises(ValidationError, match="not approved"):
            SupplierService.require_approved(clientless)


class TestRejectAndResubmit:
    def test_reject_requires_note(self, client, role_users, segment):
        client.force_login(role_users["staff"])
        client.post("/ap/suppliers/new/", dict(FORM, default_segment=segment.id))
        s = Supplier.objects.get(code="S900")
        client.force_login(role_users["head"])
        client.post(f"/ap/suppliers/{s.pk}/reject/", {"note": ""})
        s.refresh_from_db()
        assert s.approval_status == SupplierApprovalStatus.PENDING

    def test_head_rejects_and_creator_resubmits(self, client, role_users, segment):
        client.force_login(role_users["staff"])
        client.post("/ap/suppliers/new/", dict(FORM, default_segment=segment.id))
        s = Supplier.objects.get(code="S900")
        client.force_login(role_users["head"])
        client.post(f"/ap/suppliers/{s.pk}/reject/", {"note": "Duplicate of S100"})
        s.refresh_from_db()
        assert s.approval_status == SupplierApprovalStatus.REJECTED
        assert s.rejected_by_id == role_users["head"].id
        assert _items(role_users["head"]) == []
        # rejected stays hidden from the picker too
        resp = client.get("/foundation/supplier-options/", {"q": "Hopedale"})
        assert "Hopedale Fuel Corp" not in resp.content.decode()
        # the creator edits & resubmits
        client.force_login(role_users["staff"])
        form = dict(FORM, name="Hopedale Fuel Corporation", default_segment=segment.id)
        client.post(f"/ap/suppliers/{s.pk}/update/", form)
        s.refresh_from_db()
        assert s.approval_status == SupplierApprovalStatus.PENDING
        assert s.name == "Hopedale Fuel Corporation"
        assert s.rejection_note == ""
        assert s.rejected_by_id is None
        assert [i["doc"].id for i in _items(role_users["head"])] == [s.id]

    def test_stranger_cannot_edit(self, client, role_users, company):
        other = SupplierService.create_supplier(created_by=role_users["staff"], **FORM)
        client.force_login(role_users["staff"])
        resp = client.post(f"/ap/suppliers/{other.pk}/update/", dict(FORM, code="S901"))
        assert resp.status_code == 403
        other.refresh_from_db()
        assert other.code == "S900"

    def test_approve_is_head_only(self, client, role_users, segment):
        s = SupplierService.create_supplier(
            created_by=role_users["staff"], default_segment=segment, **FORM
        )
        client.force_login(role_users["staff"])
        client.post(f"/ap/suppliers/{s.pk}/approve/")
        s.refresh_from_db()
        assert s.approval_status == SupplierApprovalStatus.PENDING


class TestApiRule:
    def test_api_staff_create_pending_head_create_approved(self, role_users, segment):
        staff_api = APIClient()
        staff_api.force_authenticate(user=role_users["staff"])
        resp = staff_api.post(
            "/api/v1/ap/suppliers/",
            dict(FORM, default_segment=segment.id),
            format="json",
        )
        assert resp.status_code == 201
        assert resp.json()["approval_status"] == "pending"

        head_api = APIClient()
        head_api.force_authenticate(user=role_users["head"])
        resp = head_api.post(
            "/api/v1/ap/suppliers/",
            dict(FORM, code="S902", default_segment=segment.id),
            format="json",
        )
        assert resp.status_code == 201
        assert resp.json()["approval_status"] == "approved"

    def test_api_status_not_client_writable(self, role_users, segment):
        staff_api = APIClient()
        staff_api.force_authenticate(user=role_users["staff"])
        resp = staff_api.post(
            "/api/v1/ap/suppliers/",
            dict(FORM, approval_status="approved", default_segment=segment.id),
            format="json",
        )
        assert resp.json()["approval_status"] == "pending"

    def test_api_approve_reject_gated(self, role_users, segment):
        s = SupplierService.create_supplier(
            created_by=role_users["staff"], default_segment=segment, **FORM
        )
        staff_api = APIClient()
        staff_api.force_authenticate(user=role_users["staff"])
        resp = staff_api.post(f"/api/v1/ap/suppliers/{s.pk}/approve/")
        assert resp.status_code == 422
        head_api = APIClient()
        head_api.force_authenticate(user=role_users["head"])
        resp = head_api.post(f"/api/v1/ap/suppliers/{s.pk}/reject/", {"note": "bad TIN"})
        assert resp.status_code == 200
        s.refresh_from_db()
        assert s.approval_status == SupplierApprovalStatus.REJECTED


class TestExistingWorkflowUnaffected:
    def test_orm_created_suppliers_stay_active(self, db):
        s = Supplier.objects.create(code="S100", name="Legacy Co")
        assert s.approval_status == SupplierApprovalStatus.APPROVED
        assert SupplierService.require_approved(s) is s