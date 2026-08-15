from rest_framework import serializers

from .models import Asset, AssetCategory, AssetDisposal, DepreciationSchedule


class AssetCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetCategory
        fields = ("id", "code", "name", "useful_life_years", "asset_account",
                  "depreciation_expense_account", "accumulated_dep_account", "segment", "is_active")


class AssetSerializer(serializers.ModelSerializer):
    accumulated_depreciation = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    net_book_value = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    monthly_depreciation = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)

    class Meta:
        model = Asset
        fields = ("id", "asset_no", "name", "category", "segment", "acquisition_date",
                  "cost", "residual_value", "asset_account", "depreciation_expense_account",
                  "accumulated_dep_account", "funding_source", "financed_loan_reference",
                  "acquisition_fees", "acquisition_journal", "status", "vehicle",
                  "accumulated_depreciation", "net_book_value", "monthly_depreciation")


class DepreciationScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = DepreciationSchedule
        fields = ("id", "asset", "period_start", "period_end", "amount", "journal_entry", "status", "is_still_in_use")


class AssetDisposalSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetDisposal
        fields = ("id", "asset", "disposal_date", "proceeds", "reason", "gain", "journal_entry", "status")
