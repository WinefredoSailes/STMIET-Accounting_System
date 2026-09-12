from django.db import transaction
from django.utils import timezone

from rest_framework import serializers

from apps.core.approvals import require_approval_role
from apps.core.exceptions import ValidationError as AccountingValidationError
from apps.sequences.models import DocumentSequence

from apps.posting.models import JournalEntry, JournalEntryLine, PostingRule, PostingRuleLine, PostingStatus
from apps.posting.services import PostingService


class JournalEntryLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = JournalEntryLine
        fields = ("id", "line_no", "account", "segment", "description", "debit", "credit", "reference")
        read_only_fields = ("id", "line_no")


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalEntryLineSerializer(many=True, required=False)

    class Meta:
        model = JournalEntry
        fields = (
            "id", "entry_no", "company", "segment", "fiscal_period", "transaction_date",
            "status", "description", "source_doc_type", "source_doc_no", "source_file",
            "reversal_token", "total_debit", "total_credit", "lines",
        )
        read_only_fields = ("entry_no", "status", "total_debit", "total_credit", "reversal_token")

    def create(self, validated_data):
        """Create a draft JE with its nested distribution lines."""
        lines_data = validated_data.pop("lines", [])
        if not lines_data:
            raise AccountingValidationError("Add at least one line with an amount.")
        company = validated_data["company"]
        transaction_date = validated_data["transaction_date"]
        request = self.context.get("request")
        with transaction.atomic():
            entry = JournalEntry.objects.create(
                entry_no=DocumentSequence.next_number(
                    company=company, form_code="JE", year=transaction_date.year
                ),
                status=PostingStatus.DRAFT,
                created_by=getattr(request, "user", None),
                **validated_data,
            )
            for i, line_data in enumerate(lines_data, start=1):
                JournalEntryLine.objects.create(entry=entry, line_no=i, **line_data)
            entry.recalc_totals()
        return entry


class PostingRuleLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostingRuleLine
        fields = ("id", "line_no", "side", "account_code", "fixed_amount", "share", "use_balance", "description")


class PostingRuleSerializer(serializers.ModelSerializer):
    lines = PostingRuleLineSerializer(many=True, read_only=True)

    class Meta:
        model = PostingRule
        fields = ("id", "code", "name", "event", "description", "is_active", "lines")


class PostEntrySerializer(serializers.Serializer):
    """POST /posting/entries/{id}/post — head approves (optional) then posts.

    ``approve=True`` combines submit + approve + post in one call and is
    restricted to the Accounting & Finance Head.
    """

    entry = serializers.PrimaryKeyRelatedField(queryset=JournalEntry.objects.all())
    approve = serializers.BooleanField(default=False, help_text="Head-only: approve the entry before posting.")

    def create(self, validated_data):
        entry = validated_data["entry"]
        user = self.context["request"].user
        if validated_data["approve"]:
            require_approval_role(user, "head")
            if entry.status not in (PostingStatus.DRAFT, PostingStatus.SUBMITTED):
                raise AccountingValidationError("Only draft or submitted entries can be approved.")
            entry.status = PostingStatus.APPROVED
            entry.approved_by = user
            entry.approved_at = timezone.now()
            entry.rejected_by = None
            entry.rejected_at = None
            entry.rejection_note = ""
            entry.save(
                update_fields=[
                    "status", "approved_by", "approved_at",
                    "rejected_by", "rejected_at", "rejection_note", "updated_at",
                ]
            )
        elif entry.status != PostingStatus.APPROVED:
            raise AccountingValidationError("Only approved entries can be posted.")
        return PostingService.post(entry, approver=user, user=user)