"""Thin UI-layer glue for generic DocumentAttachment rows.

Views stay thin (ADR-009): after the service creates/updates the document,
call ``save_doc_attachments(request, obj)``; for GET/detail rendering, merge
``attachment_context(obj, user)`` into the template context.
"""

from __future__ import annotations

from apps.core.attachments import (
    can_edit_attachments,
    can_view_parent,
    doc_status,
    is_locked_status,
    live_attachments_for,
    sync_attachments,
)
from apps.core.exceptions import ValidationError


def attachment_context(obj, user) -> dict:
    """Template context: live files + whether the user may change them."""
    try:
        attachments = list(live_attachments_for(obj)) if getattr(obj, "pk", None) else []
    except Exception:  # noqa: BLE001 - unsaved/test objects
        attachments = []
    editable = False
    try:
        editable = bool(can_edit_attachments(user, obj) and not is_locked_status(doc_status(obj)))
    except Exception:  # noqa: BLE001 - never break page render
        editable = False
    ctx = {"attachments": attachments, "attachments_editable": editable}
    try:
        from django.contrib.contenttypes.models import ContentType

        ctype = ContentType.objects.get_for_model(obj, for_concrete_model=False)
        ctx["attachment_parent"] = {
            "app_label": ctype.app_label,
            "model": ctype.model,
            "object_id": obj.pk,
        }
    except Exception:  # noqa: BLE001 - tests/unsaved objects
        ctx["attachment_parent"] = None
    return ctx


def save_doc_attachments(request, obj) -> tuple[list, int]:
    """Persist multi-file uploads + removals for a just-saved document.

    Raises ValidationError when locked, unreadable, or over limits.
    No-op when the POST carries no attachment keys (HTMX partials safe).
    """
    has_files = bool(getattr(request, "FILES", None) and request.FILES)
    has_remove = bool(
        (hasattr(request.POST, "getlist") and request.POST.getlist("remove_attachments"))
        or request.POST.get("attachment_remove") == "1"
    )
    if not has_files and not has_remove:
        return [], 0
    if is_locked_status(doc_status(obj)):
        raise ValidationError("Attachments are locked once posted.")
    if not can_edit_attachments(request.user, obj):
        raise ValidationError("You cannot change attachments on this document.")
    return sync_attachments(request, obj, user=request.user)
