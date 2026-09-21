from rest_framework import serializers

from .models import BillingDocument, BillingLine


class BillingLineSerializer(serializers.ModelSerializer):
    account_code = serializers.SerializerMethodField()
    account_name = serializers.SerializerMethodField()

    def get_account_code(self, obj):
        return obj.account.code if obj.account else ""

    def get_account_name(self, obj):
        return obj.account.name if obj.account else ""

    class Meta:
        model = BillingLine
        fields = (
            "id", "line_no", "side", "segment", "account", "account_code",
            "account_name", "cost_center", "description", "debit", "credit",
        )


class BillingDocumentSerializer(serializers.ModelSerializer):
    lines = BillingLineSerializer(many=True, read_only=True)

    class Meta:
        model = BillingDocument
        fields = (
            "id", "billing_no", "billing_type", "billing_date", "company",
            "segment", "party_name", "customer", "supplier", "rfp", "reference",
            "particulars", "amount", "status", "journal_entry",
            "approved_by", "approved_at", "rejected_by", "rejected_at",
            "rejection_note", "revision_count", "lines",
        )
        read_only_fields = ("journal_entry", "amount", "status")