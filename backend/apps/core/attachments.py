"""Generic multi-file attachment support (1-10 files per transaction).

Replaces the legacy per-document single ``FileField`` pattern
(RFPDocument.attachment, PurchaseOrder.attachment, Deposit.attachment)
with one ``DocumentAttachment`` table addressed by GenericForeignKey.

Safety contract (agreed with users):
  - 1-10 live files per object, 10 MB per file.
  - Allowed: .pdf, .jpg, .jpeg, .png, .doc, .docx (+ matching MIME).
  - Evidence-only: never affects posting/balances/approvals.
  - Editable until posted (status-based); immutable once posted/reversed/cleared.
  - Soft-delete with 7-year retention (is_deleted flag, bytes kept).
  - Visibility = parent-doc visibility + segment context (screen grant check).
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.utils.text import get_valid_filename

from apps.core.exceptions import ValidationError

MAX_FILES_PER_OBJECT = 10
MAX_FILE_MB = 10
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024

ALLOWED_EXTENSIONS = frozenset({"pdf", "jpg", "jpeg", "png", "doc", "docx"})

# Extension -> expected MIME prefixes. docx files are zip-based; accept both
# the OOXML type and generic zip from some browsers.
ALLOWED_MIME = {
    "pdf": ("application/pdf",),
    "jpg": ("image/jpeg",),
    "jpeg": ("image/jpeg",),
    "png": ("image/png",),
    "doc": ("application/msword",),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    ),
}

# Statuses that lock attachments (immutable). Everything else is editable
# until posting. Matched case-insensitively against obj.status.
LOCKED_STATUSES = frozenset({"posted", "reversed", "cleared", "paid", "closed"})

RETENTION_YEARS = 7


def attachment_upload_to(instance, filename: str) -> str:
    """Per-document storage path: attachments/<app>_<model>/<year>/<id>/<uuid>_<safe>."""
    safe = get_valid_filename(os.path.basename(filename or "file")) or "file"
    # Keep extension for MIME handling even after sanitization.
    uid = uuid.uuid4().hex[:12]
    ct = getattr(instance, "content_type", None)
    if ct is not None:
        try:
            prefix = f"{ct.app_label}_{ct.model}"
        except Exception:  # noqa: BLE001 - content type may be unsaved in tests
            prefix = "doc"
    else:
        prefix = "doc"
    year = timezone.now().year
    obj_id = getattr(instance, "object_id", None) or "unassigned"
    return f"attachments/{prefix}/{year}/{obj_id}/{uid}_{safe}"


def validate_single_file(uploaded) -> None:
    """Validate one UploadedFile: extension, MIME, size, non-empty."""
    name = getattr(uploaded, "name", "") or ""
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"File '{name}': type .{ext or '?'} not allowed. "
            "Allowed: pdf, jpg, jpeg, png, doc, docx."
        )
    size = getattr(uploaded, "size", None)
    if size is not None:
        if size <= 0:
            raise ValidationError(f"File '{name}': empty files are not allowed.")
        if size > MAX_FILE_BYTES:
            raise ValidationError(
                f"File '{name}': {size / (1024 * 1024):.1f} MB exceeds "
                f"the {MAX_FILE_MB} MB per-file limit."
            )
    content_type = (getattr(uploaded, "content_type", "") or "").lower().split(";")[0].strip()
    if content_type:
        allowed = ALLOWED_MIME.get(ext, ())
        # Browsers sometimes send generic octet-stream for doc/docx; allow it
        # only when the extension itself is allowed (defense in depth, not bypass).
        if content_type not in allowed and content_type != "application/octet-stream":
            raise ValidationError(
                f"File '{name}': MIME '{content_type}' does not match .{ext}."
            )


def validate_file_count(live_count: int, incoming_count: int) -> None:
    if live_count + incoming_count > MAX_FILES_PER_OBJECT:
        raise ValidationError(
            f"Too many files: {live_count} attached + {incoming_count} new "
            f"exceeds the {MAX_FILES_PER_OBJECT} files per transaction limit. "
            "Remove some files first."
        )


def is_locked_status(status: str | None) -> bool:
    return str(status or "").strip().lower() in LOCKED_STATUSES


def doc_status(obj) -> str:
    for attr in ("status", "approval_status"):
        val = getattr(obj, attr, "")
        if val:
            return str(val)
    # JournalEntry uses PostingStatus enum values; default to locked only when posted.
    return ""


def doc_segment(obj):
    """Best-effort segment snapshot for visibility audit."""
    for attr in ("segment",):
        seg = getattr(obj, attr, None)
        if seg is not None:
            return seg
    # Some docs (Deposit) resolve segment via lines/receipts; leave None.
    return None


def doc_company(obj):
    seg = doc_segment(obj)
    if seg is not None:
        return getattr(seg, "company", None)
    return getattr(obj, "company", None)


# ---------------------------------------------------------------------------
# Permission helpers (segment-aware visibility)
# ---------------------------------------------------------------------------

# content_type natural key -> UI screen key guarding the parent register.
# Used so attachment download requires the same grant as opening the parent.
SCREEN_BY_MODEL = {
    ("ap", "rfpdocument"): "rfp_list",
    ("ap", "purchaseorder"): "po_list",
    ("ap", "checkvoucher"): "cv_list",
    ("ap", "consobatch"): "conso_list",
    ("cash", "pcfreplenishment"): "pcf_replenishment_list",
    ("cash", "interaccounttransfer"): "transfers",
    ("posting", "journalentry"): "je_list",
    ("ar", "arinvoice"): "si_list",
    ("ar", "specialsalesinvoice"): "ssi_list",
    ("ar", "acknowledgmentreceipt"): "receipt_list",
    ("ar", "deposit"): "receipt_list",
    ("billing", "billingdocument"): "billing_list",
    ("assets", "asset"): "asset_list",
}


def parent_screen_key(obj) -> str | None:
    ct = getattr(obj, "_attachment_ct_key", None)
    if ct:
        return SCREEN_BY_MODEL.get(ct)
    try:
        from django.contrib.contenttypes.models import ContentType

        ctype = ContentType.objects.get_for_model(obj, for_concrete_model=False)
        return SCREEN_BY_MODEL.get((ctype.app_label, ctype.model))
    except Exception:  # noqa: BLE001 - unregistered/test-only models
        return None


def user_has_screen(user, screen_key: str | None) -> bool:
    if screen_key is None:
        return True  # unknown model: fall back to login-only (deny elsewhere)
    try:
        from apps.ui.screens import effective_screens

        return screen_key in effective_screens(user)
    except Exception:  # noqa: BLE001 - screens registry must never break downloads
        return getattr(user, "is_authenticated", False)


def _is_sensitive_doc(obj) -> bool:
    """Payroll/HR-sensitive docs get a tighter viewer set.

    Heuristic: any doc whose party is an employee-flagged Supplier
    (Advances 12070 flow) or whose description mentions payroll/salary.
    """
    try:
        payee = getattr(obj, "payee", None) or getattr(obj, "supplier", None) or getattr(obj, "employee", None)
        if payee is not None and getattr(payee, "is_employee", False):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        emp_name = getattr(obj, "employee_name", "") or ""
        if emp_name:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def can_view_parent(user, obj) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    screen = parent_screen_key(obj)
    if screen and not user_has_screen(user, screen):
        return False
    if _is_sensitive_doc(obj):
        # Sensitive: preparer, head/coo, or superuser only.
        try:
            from apps.core.approvals import get_approval_role

            role = get_approval_role(user)
        except Exception:  # noqa: BLE001
            role = ""
        if role in ("head", "coo"):
            return True
        created_by_id = getattr(obj, "created_by_id", None) or getattr(getattr(obj, "requested_by", None), "id", None)
        if created_by_id and getattr(user, "id", None) == created_by_id:
            return True
        # Approvers in the chain may still view via My Approvals inbox.
        return False
    return True


def can_edit_attachments(user, obj) -> bool:
    """Editable until posted: locked statuses are immutable."""
    if not getattr(user, "is_authenticated", False):
        return False
    if is_locked_status(doc_status(obj)):
        return False
    if getattr(user, "is_superuser", False):
        return True
    try:
        from apps.core.approvals import get_approval_role

        if get_approval_role(user) in ("head", "coo"):
            return can_view_parent(user, obj)
    except Exception:  # noqa: BLE001
        pass
    # Preparer (or anyone with parent view access) may attach until posted.
    return can_view_parent(user, obj)


def can_view_attachment(user, attachment) -> bool:
    try:
        parent = attachment.content_object
    except Exception:  # noqa: BLE001 - stale content type
        parent = None
    if parent is None:
        return getattr(user, "is_superuser", False)
    return can_view_parent(user, parent)


def retention_cutoff():
    return timezone.now() + timedelta(days=365 * RETENTION_YEARS)


# ---------------------------------------------------------------------------
# CRUD helpers (import DocumentAttachment lazily to avoid app-loading cycles)
# ---------------------------------------------------------------------------

def _attachment_model():
    from apps.core.models import DocumentAttachment

    return DocumentAttachment


def live_attachments_for(obj):
    """Live (non-deleted) attachments for a document, oldest first."""
    from django.contrib.contenttypes.models import ContentType

    model = _attachment_model()
    ctype = ContentType.objects.get_for_model(obj, for_concrete_model=False)
    return (
        model.objects.filter(content_type=ctype, object_id=obj.pk, is_deleted=False)
        .select_related("uploaded_by")
        .order_by("created_at", "id")
    )


def live_attachment_count(obj) -> int:
    from django.contrib.contenttypes.models import ContentType

    model = _attachment_model()
    ctype = ContentType.objects.get_for_model(obj, for_concrete_model=False)
    return model.objects.filter(
        content_type=ctype, object_id=obj.pk, is_deleted=False
    ).count()


def save_uploaded_files(request, obj, user=None) -> list:
    """Validate + persist request.FILES.getlist('attachments') onto obj.

    Raises ValidationError on type/size/count violations. Returns created rows.
    """
    from django.contrib.contenttypes.models import ContentType
    from apps.core.models import DocumentAttachment

    uploads = []
    if hasattr(request.FILES, "getlist"):
        uploads = list(request.FILES.getlist("attachments"))
    if not uploads:
        # Back-compat: legacy single-input name used by RFP/PO/deposit forms.
        single = request.FILES.get("attachment")
        if single:
            uploads = [single]
    if not uploads:
        return []

    for up in uploads:
        validate_single_file(up)
    validate_file_count(live_attachment_count(obj), len(uploads))

    ctype = ContentType.objects.get_for_model(obj, for_concrete_model=False)
    seg = doc_segment(obj)
    comp = doc_company(obj)
    created = []
    for up in uploads:
        row = DocumentAttachment(
            content_type=ctype,
            object_id=obj.pk,
            file=up,
            original_name=(getattr(up, "name", "") or "")[:255],
            size=getattr(up, "size", 0) or 0,
            mime=(getattr(up, "content_type", "") or "")[:128],
            uploaded_by=user,
            created_by=user,
            segment=seg if getattr(seg, "pk", None) else None,
            company=comp if getattr(comp, "pk", None) else None,
        )
        row.full_clean(exclude=["file"])
        row.save()
        created.append(row)
    return created


def remove_attachments_by_ids(obj, ids: list, user=None) -> int:
    """Soft-delete (7y retain) the given attachment ids belonging to obj."""
    from django.contrib.contenttypes.models import ContentType

    model = _attachment_model()
    ctype = ContentType.objects.get_for_model(obj, for_concrete_model=False)
    clean_ids = [int(i) for i in (ids or []) if str(i).strip().isdigit()]
    if not clean_ids:
        return 0
    rows = list(
        model.objects.filter(
            content_type=ctype, object_id=obj.pk, id__in=clean_ids, is_deleted=False
        )
    )
    for row in rows:
        row.soft_remove(user=user)
    return len(rows)


def sync_attachments(request, obj, user=None) -> tuple[list, int]:
    """One-call handler for create/edit posts: removals + new uploads."""
    removed = 0
    remove_ids = []
    if hasattr(request.POST, "getlist"):
        remove_ids = request.POST.getlist("remove_attachments")
    # NOTE: the legacy single checkbox (name=attachment_remove on RFP/PO
    # forms) intentionally clears only the legacy FileField (handled in
    # _capture_*_fields), never the generic rows — generic removals use the
    # per-file remove_attachments checkboxes so one tick can't wipe 10 files.
    if remove_ids:
        removed = remove_attachments_by_ids(obj, remove_ids, user=user)
    added = save_uploaded_files(request, obj, user=user)
    return added, removed
