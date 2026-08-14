"""Workflow: approval state machine shared by all documents (ADR-033 gate).

Documents move Draft -> Submitted -> Approved -> Posted. The JE approval
threshold (apps.core.money.approve_threshold) decides whether one approver is
enough or a second reviewer is required.
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models import AuditableModel


class ApprovalStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


class ApprovalRequest(AuditableModel):
    """Generic approval request against any domain object."""

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    status = models.CharField(max_length=16, choices=ApprovalStatus.choices, default=ApprovalStatus.SUBMITTED)
    submitted_by = models.ForeignKey("auth.User", null=True, on_delete=models.SET_NULL, related_name="+")
    required_approvals = models.PositiveSmallIntegerField(default=1)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["content_type", "object_id"])]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.content_type} #{self.object_id} ({self.status})"


class ApprovalAction(AuditableModel):
    """One approver's decision on an ApprovalRequest."""

    request = models.ForeignKey(ApprovalRequest, on_delete=models.PROTECT, related_name="actions")
    approved = models.BooleanField()
    approver = models.ForeignKey("auth.User", on_delete=models.PROTECT, related_name="approval_actions")
    comments = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.request} by {self.approver}: {'OK' if self.approved else 'NO'}"