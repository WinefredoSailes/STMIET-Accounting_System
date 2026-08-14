from rest_framework import serializers

from .models import ApprovalAction, ApprovalRequest


class ApprovalActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalAction
        fields = ("id", "request", "approved", "approver", "comments", "created_at")
        read_only_fields = ("created_at",)


class ApprovalRequestSerializer(serializers.ModelSerializer):
    actions = ApprovalActionSerializer(many=True, read_only=True)

    class Meta:
        model = ApprovalRequest
        fields = ("id", "content_type", "object_id", "status", "submitted_by", "required_approvals", "notes", "actions")
        read_only_fields = ("status",)