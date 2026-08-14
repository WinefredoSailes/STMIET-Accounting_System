from rest_framework import serializers

from apps.posting.models import JournalEntry, JournalEntryLine, PostingRule, PostingRuleLine
from apps.posting.services import PostingService


class JournalEntryLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = JournalEntryLine
        fields = ("id", "line_no", "account", "description", "debit", "credit", "reference")


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalEntryLineSerializer(many=True, read_only=True)

    class Meta:
        model = JournalEntry
        fields = (
            "id", "entry_no", "company", "segment", "fiscal_period", "transaction_date",
            "status", "description", "source_doc_type", "source_doc_no", "source_file",
            "reversal_token", "total_debit", "total_credit", "lines",
        )
        read_only_fields = ("entry_no", "status", "total_debit", "total_credit", "reversal_token")


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
    """POST /posting/entries/{id}/post — posts a draft/submitted entry."""

    entry = serializers.PrimaryKeyRelatedField(queryset=JournalEntry.objects.all())
    approve = serializers.BooleanField(default=False, help_text="Mark as approved before posting.")

    def create(self, validated_data):
        entry = validated_data["entry"]
        if validated_data["approve"]:
            entry.status = "approved"
            entry.save(update_fields=["status", "updated_at"])
        return PostingService.post(entry, approver=self.context["request"].user)