"""Download / remove endpoints for generic DocumentAttachment rows."""

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages

from apps.core.attachments import (
    can_edit_attachments,
    can_view_attachment,
    doc_status,
    is_locked_status,
)
from apps.core.models import DocumentAttachment


@login_required
def attachment_download(request, pk: int):
    att = get_object_or_404(
        DocumentAttachment.objects.select_related("content_type", "uploaded_by"), pk=pk
    )
    if att.is_deleted:
        raise Http404("File was removed.")
    if not can_view_attachment(request.user, att):
        raise Http404("File not found.")
    try:
        handle = att.file.open("rb")
    except (OSError, ValueError):
        raise Http404("File not found on disk.")
    resp = FileResponse(handle, as_attachment=True, filename=att.original_name or "file")
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


@login_required
def attachment_upload(request, app_label: str, model: str, object_id: int):
    """Attach 1+ files to any registered parent doc (until posted)."""
    from django.contrib.contenttypes.models import ContentType

    from apps.core.attachments import can_edit_attachments, doc_status, is_locked_status
    from apps.core.exceptions import ValidationError

    if request.method != "POST":
        messages.error(request, "Upload must be a file post.")
        return redirect("/")
    try:
        ctype = ContentType.objects.get(app_label=app_label, model=model)
        parent = ctype.get_object_for_this_type(pk=object_id)
    except Exception:  # noqa: BLE001 - unknown doc
        raise Http404("Document not found.")
    if is_locked_status(doc_status(parent)):
        messages.error(request, "Attachments are locked once posted.")
        return _back_to_parent(request, parent)
    if not can_edit_attachments(request.user, parent):
        messages.error(request, "You cannot change attachments on this document.")
        return _back_to_parent(request, parent)
    try:
        from apps.core.attachments import save_uploaded_files

        added = save_uploaded_files(request, parent, user=request.user)
        if added:
            messages.success(request, f"Attached {len(added)} file(s).")
        else:
            messages.error(request, "Choose at least one file to attach.")
    except ValidationError as exc:
        messages.error(request, str(exc))
    except Exception as exc:  # noqa: BLE001 - storage backends differ
        messages.error(request, f"Upload failed: {exc}")
    return _back_to_parent(request, parent)


@login_required
def attachment_delete(request, pk: int):
    from django.contrib.contenttypes.models import ContentType

    att = get_object_or_404(DocumentAttachment, pk=pk)
    try:
        parent = att.content_object
    except Exception:  # noqa: BLE001 - stale content type
        parent = None
    if att.is_deleted:
        raise Http404("File was removed.")
    if parent is None or not can_view_attachment(request.user, att):
        raise Http404("File not found.")
    if not can_edit_attachments(request.user, parent) or is_locked_status(doc_status(parent)):
        messages.error(request, "Attachments are locked once posted.")
        return _back_to_parent(request, parent)
    if request.method == "POST":
        att.soft_remove(user=request.user)
        messages.success(request, f"Removed '{att.original_name}'. Retained for audit.")
        return _back_to_parent(request, parent)
    # GET: confirm via parent detail (no separate page to keep flow simple).
    messages.error(request, "Removal must be confirmed from the document page.")
    return _back_to_parent(request, parent)


def _back_to_parent(request, parent):
    """Best-effort redirect to the parent document detail page."""
    from django.urls import reverse, NoReverseMatch

    model = type(parent).__name__
    pk = getattr(parent, "pk", None)
    candidates = {
        "RFPDocument": "ui:rfp_detail",
        "PurchaseOrder": "ui:po_detail",
        "CheckVoucher": "ui:cv_detail",
        "PCFReplenishment": "ui:pcf_replenishment_detail",
        "JournalEntry": "ui:je_detail",
        "InterAccountTransfer": "ui:transfer_detail",
        "ARInvoice": "ui:si_detail",
        "SpecialSalesInvoice": "ui:ssi_detail",
        "AcknowledgmentReceipt": "ui:receipt_detail",
        "Deposit": "ui:receipt_detail",
        "BillingDocument": "ui:billing_detail",
        "Asset": "ui:asset_detail",
    }
    url_name = candidates.get(model)
    if url_name and pk:
        try:
            # Deposit has no standalone detail; fall back to receipts register.
            if model == "Deposit":
                return redirect("ui:receipt_list")
            return redirect(url_name, pk=pk)
        except NoReverseMatch:  # noqa: BLE001 - fall through to dashboard
            pass
    next_url = request.POST.get("next") or request.GET.get("next") or "/"
    return redirect(next_url)
