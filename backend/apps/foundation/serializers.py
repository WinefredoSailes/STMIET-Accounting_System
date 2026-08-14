from rest_framework import serializers

from .models import Account, Company, FiscalPeriod, FiscalYear, Segment


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = (
            "id", "code", "name", "account_type", "normal_balance", "segment",
            "parent", "is_control", "is_postable", "description",
        )


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ("id", "code", "name", "tin", "address", "rdo_code")


class SegmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Segment
        fields = ("id", "code", "name", "coa_key_digit", "company")


class FiscalYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = FiscalYear
        fields = ("id", "company", "code", "start_date", "end_date", "is_closed")


class FiscalPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = FiscalPeriod
        fields = ("id", "fiscal_year", "period_no", "start_date", "end_date", "is_closed")