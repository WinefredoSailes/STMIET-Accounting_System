from rest_framework import serializers

from .models import Asset, AssetCategory, AssetDisposal, AssetLine, DepreciationSchedule


class AssetCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetCategory
        fields = ("id", "code", "name", "useful_life_years", "asset_account",
                  "depreciation_expense_account", "accumulated_dep_account", "segment", "is_active")


class AssetLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(read_only=True, source="account.code")
    account_name = serializers.CharField(read_only=True, source="account.name")

    class Meta:
        model = AssetLine
        fields = ("id", "line_no", "side", "segment", "account", "account_code",
                  "account_name", "cost_center", "description", "debit", "credit")


class AssetSerializer(serializers.ModelSerializer):
    accumulated_depreciation = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    net_book_value = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    monthly_depreciation = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    lines = AssetLineSerializer(many=True, read_only=True)
    useful_life_in_months = serializers.IntegerField(read_only=True)

    class Meta:
        model = Asset
        fields = ("id", "asset_no", "name", "category", "segment", "acquisition_date",
                  "cost", "residual_value", "asset_account", "depreciation_expense_account",
                  "accumulated_dep_account", "funding_source", "financed_loan_reference",
                  "acquisition_fees", "acquisition_journal", "status", "vehicle",
                  "supplier", "po", "reference", "useful_life_months", "useful_life_in_months",
                  "approval_status", "approved_by", "approved_at", "rejected_by", "rejected_at",
                  "rejection_note", "accumulated_depreciation", "net_book_value",
                  "monthly_depreciation", "lines")


class DepreciationScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = DepreciationSchedule
        fields = ("id", "asset", "period_start", "period_end", "amount", "journal_entry", "status", "is_still_in_use")


class AssetDisposalSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetDisposal
        fields = ("id", "asset", "disposal_date", "proceeds", "reason", "gain", "journal_entry", "status")
