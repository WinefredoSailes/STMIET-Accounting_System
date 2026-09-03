from django.utils import timezone
from django.db import models


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