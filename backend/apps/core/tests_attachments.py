"""Generic multi-file attachment tests (1-10 per transaction).

Covers: validators (type/size/count), save/remove round-trip, locked-once-posted,
segment-aware download permission, soft-delete retention, upload endpoint.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from apps.core.attachments import (
    MAX_FILES_PER_OBJECT,
    live_attachments_for,
    save_uploaded_files,
    validate_single_file,
)
from apps.core.exceptions import ValidationError
from apps.core.models import DocumentAttachment
from apps.foundation.models import UserProfile

User = get_user_model()


def _pdf(name="a.pdf", size=100):
    return SimpleUploadedFile(name, b"%PDF-1.4 " + b"x" * size, content_type="application/pdf")


def _req(files=None, remove_ids=()):
    data = {}
    if remove_ids:
        data["remove_attachments"] = [str(i) for i in remove_ids]
    req = RequestFactory().post("/x/", data)
    if files:
        # RequestFactory post with files: rebuild with FILES populated.
        req = RequestFactory().post("/x/", {**data, "attachments": files})
    req.user = None
    return req


@pytest.fixture
def staff_user(db):
    u = User.objects.create_user(username="att_staff", password="x")
    UserProfile.objects.create(user=u, approval_role="staff")
    return u


@pytest.fixture
def head_user(db):
    u = User.objects.create_user(username="att_head", password="x")
    UserProfile.objects.create(user=u, approval_role="head")
    return u


@pytest.fixture
def draft_rfp(db, company, segment, accounts, staff_user):
    from apps.ap.models import RFPDocument, RFPLine, Supplier

    sup = Supplier.objects.create(
        code="S900", name="AttachCo", default_segment=segment, approval_status="approved"
    )
    rfp = RFPDocument.objects.create(
        ap_number="A9001", rfp_date=date(2026, 9, 10), payee=sup, segment=segment,
        particulars="test", amount=Decimal("5000.00"), status="prepared",
        created_by=staff_user,
    )
    RFPLine.objects.create(rfp=rfp, line_no=1, side="dr", segment=segment,
                           account=accounts["61100"], amount=Decimal("5000.00"))
    RFPLine.objects.create(rfp=rfp, line_no=2, side="cr", segment=segment,
                           account=accounts["20000"], amount=Decimal("5000.00"))
    return rfp


class TestValidators:
    def test_allowed_types_pass(self):
        validate_single_file(_pdf("inv.pdf"))
        validate_single_file(SimpleUploadedFile("p.jpg", b"\xff\xd8x", content_type="image/jpeg"))
        validate_single_file(SimpleUploadedFile("p.png", b"\x89PNGx", content_type="image/png"))
        validate_single_file(SimpleUploadedFile("d.doc", b"doc", content_type="application/msword"))
        validate_single_file(SimpleUploadedFile(
            "d.docx", b"zip", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"))

    def test_blocked_extension(self):
        with pytest.raises(ValidationError):
            validate_single_file(SimpleUploadedFile("evil.exe", b"x", content_type="application/octet-stream"))

    def test_mime_mismatch_rejected(self):
        with pytest.raises(ValidationError):
            validate_single_file(SimpleUploadedFile("fake.pdf", b"x", content_type="image/jpeg"))

    def test_oversize_rejected(self):
        big = SimpleUploadedFile("big.pdf", b"x" * (10 * 1024 * 1024 + 1), content_type="application/pdf")
        with pytest.raises(ValidationError):
            validate_single_file(big)

    def test_empty_rejected(self):
        with pytest.raises(ValidationError):
            validate_single_file(SimpleUploadedFile("e.pdf", b"", content_type="application/pdf"))


class TestSaveRemove:
    def test_save_up_to_ten(self, draft_rfp, staff_user, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        req = _req(files=[_pdf(f"f{i}.pdf") for i in range(3)])
        req.user = staff_user
        created = save_uploaded_files(req, draft_rfp, user=staff_user)
        assert len(created) == 3
        assert live_attachments_for(draft_rfp).count() == 3

    def test_eleventh_rejected(self, draft_rfp, staff_user, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        req = _req(files=[_pdf(f"f{i}.pdf") for i in range(MAX_FILES_PER_OBJECT)])
        req.user = staff_user
        save_uploaded_files(req, draft_rfp, user=staff_user)
        with pytest.raises(ValidationError):
            save_uploaded_files(_req(files=[_pdf("extra.pdf")]), draft_rfp, user=staff_user)

    def test_soft_remove_retains_row(self, draft_rfp, staff_user, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        req = _req(files=[_pdf("keep.pdf")])
        req.user = staff_user
        (row,) = save_uploaded_files(req, draft_rfp, user=staff_user)
        from apps.core.attachments import remove_attachments_by_ids

        assert remove_attachments_by_ids(draft_rfp, [row.id], user=staff_user) == 1
        row.refresh_from_db()
        assert row.is_deleted and row.retain_until is not None
        assert live_attachments_for(draft_rfp).count() == 0
        # Bytes kept for audit.
        assert row.file.storage.exists(row.file.name)


class TestLockedOncePosted:
    def test_posted_blocks_edit(self, draft_rfp, staff_user):
        from apps.ui.attachment_flow import save_doc_attachments

        draft_rfp.status = "posted"
        draft_rfp.save(update_fields=["status"])
        req = _req(files=[_pdf("late.pdf")])
        req.user = staff_user
        with pytest.raises(ValidationError):
            save_doc_attachments(req, draft_rfp)


class TestDownloadPermission:
    def test_owner_can_download(self, client, draft_rfp, staff_user, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        req = _req(files=[_pdf("dl.pdf")])
        req.user = staff_user
        (row,) = save_uploaded_files(req, draft_rfp, user=staff_user)
        client.force_login(staff_user)
        resp = client.get(f"/attachments/{row.id}/download/")
        assert resp.status_code == 200

    def test_anonymous_denied(self, client, draft_rfp, staff_user, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        req = _req(files=[_pdf("dl2.pdf")])
        req.user = staff_user
        (row,) = save_uploaded_files(req, draft_rfp, user=staff_user)
        resp = client.get(f"/attachments/{row.id}/download/")
        assert resp.status_code in (302, 403, 404)

    def test_deleted_file_404(self, client, draft_rfp, staff_user, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        req = _req(files=[_pdf("gone.pdf")])
        req.user = staff_user
        (row,) = save_uploaded_files(req, draft_rfp, user=staff_user)
        row.soft_remove(user=staff_user)
        client.force_login(staff_user)
        assert client.get(f"/attachments/{row.id}/download/").status_code == 404


class TestJEEndToEnd:
    """Full HTTP round-trip on a wired doc (JE): create with 2 files,
    detail lists them, download serves them."""

    def test_je_create_with_two_files_detail_and_download(
        self, client, company, segment, accounts, fiscal_period, staff_user, settings, tmp_path
    ):
        settings.MEDIA_ROOT = str(tmp_path)
        client.force_login(staff_user)
        resp = client.post("/journal/new/", {
            "company": company.id,
            "segment": segment.id,
            "transaction_date": "2026-01-15",
            "description": "JE with evidence",
            "source_doc_type": "JE",
            "account": [accounts["10010"].id, accounts["20000"].id],
            "debit": ["1000.00", ""],
            "credit": ["", "1000.00"],
            "line_description": ["Cash in", "AP"],
            "attachments": [
                SimpleUploadedFile("je1.pdf", b"%PDF-1.4 one", content_type="application/pdf"),
                SimpleUploadedFile("je2.jpg", b"\xff\xd8two", content_type="image/jpeg"),
            ],
        })
        assert resp.status_code == 302
        from apps.posting.models import JournalEntry

        je = JournalEntry.objects.get(description="JE with evidence")
        live = list(live_attachments_for(je))
        assert len(live) == 2
        body = client.get(f"/journal/{je.id}/").content.decode()
        assert "je1.pdf" in body and "je2.jpg" in body
        for att in live:
            dl = client.get(f"/attachments/{att.id}/download/")
            assert dl.status_code == 200

    def test_je_form_has_multifile_input(self, client, company, accounts, staff_user):
        client.force_login(staff_user)
        body = client.get("/journal/new/").content.decode()
        assert 'enctype="multipart/form-data"' in body
        assert 'name="attachments"' in body


class TestUploadEndpoint:
    def test_upload_until_posted(self, client, draft_rfp, staff_user, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        client.force_login(staff_user)
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(draft_rfp, for_concrete_model=False)
        resp = client.post(
            f"/attachments/{ct.app_label}/{ct.model}/{draft_rfp.pk}/upload/",
            {"attachments": [_pdf("via_endpoint.pdf")]},
        )
        assert resp.status_code in (302, 303)
        assert live_attachments_for(draft_rfp).count() == 1

    def test_upload_locked_when_posted(self, client, draft_rfp, staff_user, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        draft_rfp.status = "posted"
        draft_rfp.save(update_fields=["status"])
        client.force_login(staff_user)
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(draft_rfp, for_concrete_model=False)
        client.post(
            f"/attachments/{ct.app_label}/{ct.model}/{draft_rfp.pk}/upload/",
            {"attachments": [_pdf("late2.pdf")]},
        )
        assert live_attachments_for(draft_rfp).count() == 0
