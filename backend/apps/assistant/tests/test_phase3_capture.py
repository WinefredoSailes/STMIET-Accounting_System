"""Phase 3 capture tests — RR/DR on POs, supplier invoice on RFPs.

Covers: model round-trip, view capture helpers (full + partial POSTs), the
B18/B19 handlers in recorded and unrecorded states, REST payload stability
(the API surface must NOT change), and a guard that every link the answer
layer generates actually resolves to a URL (the /ui/ prefix 404 bug class).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from urllib.parse import urlparse

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory
from django.urls import resolve

from apps.ap.models import POLine, PurchaseOrder, RFPDocument, RFPLine, Supplier
from apps.ap.serializers import PurchaseOrderSerializer, RFPDocumentSerializer
from apps.assistant.answers.context import Entities, QContext
from apps.assistant.catalog import CATALOG_BY_ID
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
    u = User.objects.create_user(username="cap", password="x")
    UserProfile.objects.create(user=u, approval_role="staff")
    return u


@pytest.fixture
def doc_set(company, segment, accounts, staff):
    """PO + posted RFP for capture tests."""
    limdon = Supplier.objects.create(
        code="S001", name="Limdon Sales Corporation", default_segment=segment, approval_status="approved"
    )
    po = PurchaseOrder.objects.create(
        po_number="PO-2026-0500", po_date=date(2026, 9, 1), supplier=limdon,
        segment=segment, amount=Decimal("10000.00"), status="approved",
    )
    POLine.objects.create(po=po, line_no=1, pr_number="2026-55", qty=Decimal("1"), unit="PC",
                          description="Gasket", unit_price=Decimal("10000.00"), amount=Decimal("10000.00"))
    je = _post(company, segment, date(2026, 9, 3), [("61100", "10000.00"), ("20000", "-10000.00")], "JE-2026-0500", "RFP gasket")
    rfp = RFPDocument.objects.create(
        ap_number="A2026-0500", rfp_date=date(2026, 9, 3), payee=limdon, segment=segment,
        particulars="Gasket", amount=Decimal("10000.00"), status="posted", journal_entry=je, po=po,
    )
    RFPLine.objects.create(rfp=rfp, line_no=1, side="dr", segment=segment, account=accounts["61100"], amount=Decimal("10000.00"))
    RFPLine.objects.create(rfp=rfp, line_no=2, side="cr", segment=segment, account=accounts["20000"], amount=Decimal("10000.00"))
    return {"limdon": limdon, "po": po, "rfp": rfp, "segment": segment, "company": company}


def _ctx(user, ents, lower="", companies=()):
    return QContext(user=user, raw=lower, lower=lower, terms=[], companies=list(companies), entities=ents)


def assert_links_resolve(*answers):
    for ans in answers:
        for link in ans.links or []:
            path = urlparse(link["url"]).path
            try:
                resolve(path)
            except Exception as exc:  # noqa: BLE001
                raise AssertionError(f"dead link {link['url']!r} in {ans.qid}") from exc


class TestModelRoundTrip:
    def test_po_capture_fields(self, doc_set):
        po = doc_set["po"]
        po.receiving_report_no = "RR-2026-01"
        po.delivery_receipt_no = "DR-2026-02"
        po.receipt_date = date(2026, 9, 2)
        po.save(update_fields=["receiving_report_no", "delivery_receipt_no", "receipt_date", "updated_at"])
        po.refresh_from_db()
        assert po.receiving_report_no == "RR-2026-01"
        assert po.delivery_receipt_no == "DR-2026-02"
        assert po.receipt_date == date(2026, 9, 2)

    def test_rfp_capture_fields(self, doc_set):
        rfp = doc_set["rfp"]
        rfp.supplier_invoice_no = "SI-777"
        rfp.supplier_invoice_date = date(2026, 8, 30)
        rfp.save(update_fields=["supplier_invoice_no", "supplier_invoice_date", "updated_at"])
        rfp.refresh_from_db()
        assert rfp.supplier_invoice_no == "SI-777"
        assert rfp.supplier_invoice_date == date(2026, 8, 30)


class TestViewCaptureHelpers:
    def test_po_capture_full_post(self, doc_set, staff):
        from apps.ui.views import _capture_po_receipt_fields

        req = RequestFactory().post("/x/", {
            "receiving_report_no": " RR-9 ",
            "delivery_receipt_no": "DR-9",
            "receipt_date": "2026-09-02",
        })
        _capture_po_receipt_fields(req, doc_set["po"])
        doc_set["po"].refresh_from_db()
        assert doc_set["po"].receiving_report_no == "RR-9"
        assert doc_set["po"].receipt_date == date(2026, 9, 2)

    def test_po_capture_partial_post_preserves(self, doc_set):
        from apps.ui.views import _capture_po_receipt_fields

        po = doc_set["po"]
        po.receiving_report_no = "RR-keep"
        po.receipt_date = date(2026, 9, 2)
        po.save(update_fields=["receiving_report_no", "receipt_date", "updated_at"])
        # HTMX-style post without the keys must not wipe stored values
        _capture_po_receipt_fields(RequestFactory().post("/x/", {}), po)
        po.refresh_from_db()
        assert po.receiving_report_no == "RR-keep"
        assert po.receipt_date == date(2026, 9, 2)

    def test_po_capture_bad_date_raises(self, doc_set):
        from apps.ui.views import _capture_po_receipt_fields
        from apps.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            _capture_po_receipt_fields(RequestFactory().post("/x/", {"receipt_date": "not-a-date"}), doc_set["po"])

    def test_rfp_capture_and_clear(self, doc_set):
        from apps.ui.views import _capture_rfp_invoice_fields

        rfp = doc_set["rfp"]
        _capture_rfp_invoice_fields(RequestFactory().post("/x/", {"supplier_invoice_no": "SI-1", "supplier_invoice_date": "2026-08-01"}), rfp)
        rfp.refresh_from_db()
        assert rfp.supplier_invoice_no == "SI-1"
        # explicit empty values clear the field (full form submit)
        _capture_rfp_invoice_fields(RequestFactory().post("/x/", {"supplier_invoice_no": "", "supplier_invoice_date": ""}), rfp)
        rfp.refresh_from_db()
        assert rfp.supplier_invoice_no == ""
        assert rfp.supplier_invoice_date is None


class TestPoFormEndToEnd:
    def test_po_create_with_capture_fields(self, client, staff, segment, accounts, company):
        client.force_login(staff)
        supplier = Supplier.objects.create(code="S009", name="CapCo", default_segment=segment, approval_status="approved")
        resp = client.post("/ap/pos/new/", {
            "supplier": supplier.id,
            "segment": segment.id,
            "po_date": "2026-09-10",
            "particulars": "filters",
            "line_pr_no": ["2026-99"],
            "line_qty": ["4"],
            "line_unit": ["PC"],
            "line_description": ["Oil Filter"],
            "line_unit_price": ["1000.00"],
            "line_account": ["61100"],
            "discount": "0.00",
            "vat_amount": "0.00",
            "other_charges": "0.00",
            "payment_terms": "30 days",
            "receiving_report_no": "RR-2026-100",
            "delivery_receipt_no": "DR-2026-100",
            "receipt_date": "2026-09-12",
        })
        assert resp.status_code == 302
        po = PurchaseOrder.objects.get(po_number__startswith="PO-")
        assert po.receiving_report_no == "RR-2026-100"
        assert po.receipt_date == date(2026, 9, 12)

    def test_po_create_without_capture_fields_still_works(self, client, staff, segment, accounts, company):
        """Legacy payloads (no new keys) must behave exactly as before."""
        client.force_login(staff)
        supplier = Supplier.objects.create(code="S010", name="OldWayCo", default_segment=segment, approval_status="approved")
        resp = client.post("/ap/pos/new/", {
            "supplier": supplier.id,
            "segment": segment.id,
            "po_date": "2026-09-10",
            "particulars": "gaskets",
            "line_pr_no": [""],
            "line_qty": ["1"],
            "line_unit": ["PC"],
            "line_description": ["Gasket"],
            "line_unit_price": ["500.00"],
            "line_account": ["61100"],
            "discount": "0.00",
            "vat_amount": "0.00",
            "other_charges": "0.00",
        })
        assert resp.status_code == 302
        po = PurchaseOrder.objects.get(supplier=supplier)
        assert po.receiving_report_no == ""
        assert po.receipt_date is None


class TestCaptureHandlers:
    def test_rr_of_recorded(self, staff, doc_set):
        from apps.assistant.answers.handlers.purchase import rr_of

        po = doc_set["po"]
        po.receiving_report_no = "RR-11"
        po.delivery_receipt_no = "DR-22"
        po.receipt_date = date(2026, 9, 2)
        po.save(update_fields=["receiving_report_no", "delivery_receipt_no", "receipt_date", "updated_at"])
        e = Entities(po=po)
        ans = rr_of(_ctx(staff, e, "receiving report", [doc_set["company"]]), e)
        assert ans.qid == "B18"
        assert "RR-11" in ans.summary and "DR-22" in ans.summary
        assert_links_resolve(ans)

    def test_rr_of_unrecorded(self, staff, doc_set):
        from apps.assistant.answers.handlers.purchase import rr_of

        e = Entities(po=doc_set["po"])
        ans = rr_of(_ctx(staff, e, "receiving report", [doc_set["company"]]), e)
        assert "No receiving report or delivery receipt has been recorded" in ans.summary
        assert "Goods Receipt section" in ans.note
        assert_links_resolve(ans)

    def test_supplier_invoice_recorded_and_empty(self, staff, doc_set):
        from apps.assistant.answers.handlers.purchase import supplier_invoice_of

        e = Entities(rfp=doc_set["rfp"])
        empty = supplier_invoice_of(_ctx(staff, e, "supplier invoice", [doc_set["company"]]), e)
        assert "No supplier invoice reference" in empty.summary

        rfp = doc_set["rfp"]
        rfp.supplier_invoice_no = "INV-X1"
        rfp.supplier_invoice_date = date(2026, 8, 28)
        rfp.save(update_fields=["supplier_invoice_no", "supplier_invoice_date", "updated_at"])
        ans = supplier_invoice_of(_ctx(staff, e, "supplier invoice", [doc_set["company"]]), e)
        assert ans.qid == "B19"
        assert "INV-X1" in ans.summary
        assert_links_resolve(ans)

    def test_catalog_status_flipped(self):
        assert CATALOG_BY_ID["B18"].status == "ready"
        assert CATALOG_BY_ID["B18"].handler == "purchase.rr_of"
        assert CATALOG_BY_ID["B19"].status == "ready"
        assert CATALOG_BY_ID["B19"].handler == "purchase.supplier_invoice_of"


class TestRestApiStability:
    """The capture fields must NOT leak into the public API payloads."""

    def test_po_serializer_shape_unchanged(self, doc_set):
        data = PurchaseOrderSerializer(doc_set["po"]).data
        assert "receiving_report_no" not in data
        assert "delivery_receipt_no" not in data
        assert "receipt_date" not in data

    def test_rfp_serializer_shape_unchanged(self, doc_set):
        data = RFPDocumentSerializer(doc_set["rfp"]).data
        assert "supplier_invoice_no" not in data
        assert "supplier_invoice_date" not in data


class TestAnswerLinksResolve:
    """Regression guard for the /ui/-prefix 404 bug on every linking handler."""

    @pytest.mark.parametrize("message,qid", [
        ("how much do we owe limdon", "C25"),
        ("what is our net income", "K90"),
        ("unpaid rfps", "C26"),
    ])
    def test_links_from_service(self, staff, doc_set, message, qid):
        resp = AssistantService().process_query(staff, message)
        block = resp.get("answer_block")
        assert block is not None, resp["text"]
        assert block["qid"] == qid
        for link in block.get("links", []):
            resolve(urlparse(link["url"]).path)


class TestAttachments:
    """Phase 3b: supporting file capture on PO/RFP + B24/G62 answers."""

    def test_catalog_flipped_to_ready(self):
        assert CATALOG_BY_ID["B24"].status == "ready"
        assert CATALOG_BY_ID["B24"].handler == "purchase.supporting_docs"
        assert CATALOG_BY_ID["G62"].status == "ready"
        assert CATALOG_BY_ID["G62"].handler == "purchase.supporting_docs"
        assert CATALOG_BY_ID["H71"].status == "ready"

    def test_po_upload_roundtrip(self, client, staff, segment, company, accounts, settings, tmp_path):
        from django.core.files.uploadedfile import SimpleUploadedFile

        settings.MEDIA_ROOT = str(tmp_path)
        client.force_login(staff)
        supplier = Supplier.objects.create(code="S011", name="ScanCo", default_segment=segment, approval_status="approved")
        resp = client.post("/ap/pos/new/", {
            "supplier": supplier.id,
            "segment": segment.id,
            "po_date": "2026-09-10",
            "particulars": "filters",
            "line_pr_no": ["2026-11"],
            "line_qty": ["1"],
            "line_unit": ["PC"],
            "line_description": ["Filter"],
            "line_unit_price": ["900.00"],
            "line_account": ["61100"],
            "discount": "0.00",
            "vat_amount": "0.00",
            "other_charges": "0.00",
            "receiving_report_no": "RR-77",
            "attachment": SimpleUploadedFile("scan.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
        })
        assert resp.status_code == 302
        po = PurchaseOrder.objects.get(supplier=supplier)
        assert po.receiving_report_no == "RR-77"
        assert po.attachment.name and po.attachment.name.startswith("po_supporting/")

    def test_po_repost_without_file_keeps_attachment(self, doc_set, settings, tmp_path):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.ui.views import _capture_po_receipt_fields

        settings.MEDIA_ROOT = str(tmp_path)
        req = RequestFactory().post("/x/", {"attachment": SimpleUploadedFile("a.pdf", b"x", "application/pdf")})
        _capture_po_receipt_fields(req, doc_set["po"])
        assert doc_set["po"].attachment.name

        # a later post without a file must NOT wipe the stored attachment
        _capture_po_receipt_fields(RequestFactory().post("/x/", {"receiving_report_no": "RR-2"}), doc_set["po"])
        doc_set["po"].refresh_from_db()
        assert doc_set["po"].attachment.name
        assert doc_set["po"].receiving_report_no == "RR-2"

    def test_rfp_upload_roundtrip(self, doc_set, settings, tmp_path):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.ui.views import _capture_rfp_invoice_fields

        settings.MEDIA_ROOT = str(tmp_path)
        req = RequestFactory().post("/x/", {
            "supplier_invoice_no": "SI-5",
            "attachment": SimpleUploadedFile("inv.pdf", b"x", "application/pdf"),
        })
        _capture_rfp_invoice_fields(req, doc_set["rfp"])
        doc_set["rfp"].refresh_from_db()
        assert doc_set["rfp"].supplier_invoice_no == "SI-5"
        assert doc_set["rfp"].attachment.name.startswith("rfp_supporting/")

    def test_supporting_docs_none_attached(self, staff, doc_set):
        from apps.assistant.answers.handlers.purchase import supporting_docs

        e = Entities(po=doc_set["po"])
        ans = supporting_docs(_ctx(staff, e, "supporting documents", [doc_set["company"]]), e)
        assert "No supporting file is attached" in ans.summary
        assert "Supporting file field" in ans.note

    def test_supporting_docs_with_file(self, staff, doc_set):
        from apps.assistant.answers.handlers.purchase import supporting_docs

        po = doc_set["po"]
        po.attachment = "po_supporting/scan.pdf"
        po.save(update_fields=["attachment", "updated_at"])
        e = Entities(po=po)
        ans = supporting_docs(_ctx(staff, e, "supporting documents", [doc_set["company"]]), e)
        assert ans.qid == "B24"
        assert "1 supporting file" in ans.summary
        # non-media links must resolve; the file link points under MEDIA_URL
        from django.conf import settings

        for link in ans.links:
            if link["url"].startswith(settings.MEDIA_URL):
                continue
            resolve(urlparse(link["url"]).path)

    def test_supporting_docs_via_cv_resolves_rfp(self, staff, doc_set):
        from apps.assistant.answers.handlers.purchase import supporting_docs

        rfp = doc_set["rfp"]
        rfp.attachment = "rfp_supporting/invoice.pdf"
        rfp.save(update_fields=["attachment", "updated_at"])
        e = Entities(rfp=rfp)
        ans = supporting_docs(_ctx(staff, e, "attached documents", [doc_set["company"]]), e)
        assert "RFP" in ans.summary or "1 supporting file" in ans.summary

    def test_attachment_not_in_api_payloads(self, doc_set):
        po_data = PurchaseOrderSerializer(doc_set["po"]).data
        rfp_data = RFPDocumentSerializer(doc_set["rfp"]).data
        assert "attachment" not in po_data
        assert "attachment" not in rfp_data

    def test_service_routes_b24_to_handler(self, staff, doc_set):
        resp = AssistantService().process_query(staff, "can I view the supporting documents of PO-2026-0500")
        block = resp.get("answer_block")
        assert block is not None, resp["text"]
        assert block["qid"] == "B24"
        assert "No supporting file" in resp["text"]