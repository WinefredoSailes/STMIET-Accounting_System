from rest_framework import serializers

from .models import FinancialStatement, MonthEndClose, StatementLineDef, StatementTemplate


class StatementLineDefSerializer(serializers.ModelSerializer):
    class Meta:
        model = StatementLineDef
        fields = ("id", "line_no", "key", "title", "mode", "balance_basis",
                  "account_codes", "account_prefixes", "sign", "parent",
                  "is_subtotal", "is_section", "is_hidden", "left_ref",
                  "right_ref", "weight")


class StatementTemplateSerializer(serializers.ModelSerializer):
    lines = StatementLineDefSerializer(many=True, read_only=True)

    class Meta:
        model = StatementTemplate
        fields = ("id", "statement_type", "name", "description", "lines")


class FinancialStatementSerializer(serializers.ModelSerializer):
    statement_type_display = serializers.CharField(source="get_statement_type_display", read_only=True)

    class Meta:
        model = FinancialStatement
        fields = ("id", "statement_type", "statement_type_display", "company", "segment",
                  "period_start", "period_end", "data", "identity_ok", "identity_note",
                  "status", "generated_at")


class MonthEndCloseSerializer(serializers.ModelSerializer):
    fiscal_period = serializers.StringRelatedField()

    class Meta:
        model = MonthEndClose
        fields = ("id", "fiscal_period", "company", "steps", "status", "notes",
                  "closed_by", "closed_at", "is_ready")


class MonthEndCloseWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = MonthEndClose
        fields = ("id", "fiscal_period", "company", "steps", "status", "notes")
        read_only_fields = ("steps", "status")
