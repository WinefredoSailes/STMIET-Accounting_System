from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.db import models

from apps.core.attachments import attachment_upload_to


class ActiveManager(models.Manager):
    """Default manager that excludes soft-deleted rows."""

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class AuditableModel(models.Model):
    """Adds created/updated audit columns and soft-delete support.

    Every domain entity inherits this (ADR-008: full audit trail).
    Deletion is always soft; rows are never physically removed.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, related_name="+", on_delete=models.SET_NULL
    )
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, related_name="+", on_delete=models.SET_NULL
    )
    is_active = models.BooleanField(default=True, db_index=True)

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def soft_delete(self, user=None):
        self.is_active = False
        if user:
            self.updated_by = user
        self.save(update_fields=["is_active", "updated_by", "updated_at"])

    def touch(self, user=None):
        self.updated_at = timezone.now()
        if user:
            self.updated_by = user
        self.save(update_fields=["updated_at", "updated_by"])


class DocumentAttachment(AuditableModel):
    """One evidence file attached to any financial transaction (1-10 per doc).

    Generic (content_type + object_id) so RFP/PO/CV/PCV/JE/FTV/SI/SSI/
    Receipt/Deposit/Billing/Asset share one validator, one download view,
    one retention job. Evidence-only: never affects posting or balances.

    Retention: user removal sets ``is_deleted`` + ``retain_until`` (7 years);
    bytes are kept for audit. A nightly purge hard-deletes only rows past
    ``retain_until``. ``is_active`` stays True so rows survive soft-delete
    filters; liveness = ``is_deleted=False``.
    """

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveBigIntegerField(db_index=True)
    content_object = GenericForeignKey("content_type", "object_id")

    file = models.FileField(upload_to=attachment_upload_to)
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField(default=0)
    mime = models.CharField(max_length=128, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    # Segment/company snapshot for visibility audit (inherits parent access).
    segment = models.ForeignKey(
        "foundation.Segment", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    company = models.ForeignKey(
        "foundation.Company", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    retain_until = models.DateField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(
                fields=["content_type", "object_id", "is_deleted"],
                name="core_attach_ct_obj_del_idx",
            ),
        ]

    def __str__(self):
        return f"{self.content_type}#{self.object_id} {self.original_name}"

    @property
    def is_live(self) -> bool:
        return not self.is_deleted and self.is_active

    def soft_remove(self, user=None):
        """Mark deleted but keep bytes for the 7-year audit window."""
        from apps.core.attachments import retention_cutoff

        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.retain_until = retention_cutoff().date()
        if user is not None and getattr(user, "id", None):
            self.deleted_by = user
        self.save(update_fields=["is_deleted", "deleted_at", "retain_until", "deleted_by", "updated_at"])


class SoftDeleteMixin:
    """Makes `Model.delete()` a soft delete (Phase 2 master data contract).

    Applied to MASTER-DATA models (COA accounts, companies, segments, banks,
    PCF funds, suppliers, customers, assets, ...) where a mistaken remove must
    never destroy history: `.delete()` now flips `is_active` instead of
    physically removing the row. Derived/transactional rows (journal entries,
    GL projection, cycles, statements) deliberately keep hard-delete semantics
    so the posting immutability guards (PostingService) stay authoritative.
    """

    def delete(self, *args, **kwargs):
        self.soft_delete()