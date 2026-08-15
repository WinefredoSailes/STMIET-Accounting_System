from rest_framework import serializers

from .models import (
    BankAccount,
    BankReconciliation,
    CashCycleActivity,
    CashFlowStatement,
    CashShortExcessWorksheet,
    CheckDisbursement,
    CollectiblesWorksheet,
    InterAccountTransfer,
    PCFReplenishment,
    PettyCashFund,
    WeeklyCashCycle,
)


class CashCycleActivitySerializer(serializers.ModelSerializer):
    activity_type_label = serializers.CharField(source="get_activity_type_display", read_only=True)

    class Meta:
        model = CashCycleActivity
        fields = ("id", "cycle", "activity_type", "activity_type_label", "bank_account", "amount")


class BankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = ("id", "code", "name", "account_type", "bank_name", "bank_code", "gl_account", "segment", "adb_required", "custodian", "is_active")


class WeeklyCashCycleSerializer(serializers.ModelSerializer):
    activities = CashCycleActivitySerializer(many=True, read_only=True)

    class Meta:
        model = WeeklyCashCycle
        fields = ("id", "cycle_start", "cycle_end", "segment", "closing_balance", "status", "notes", "activities")


class BankReconciliationSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankReconciliation
        fields = ("id", "cycle", "bank_account", "book_balance", "bank_statement_balance", "difference", "typo_adjustment", "pop_adjustment", "cashier_adjustment", "unresolved", "status")


class PettyCashFundSerializer(serializers.ModelSerializer):
    class Meta:
        model = PettyCashFund
        fields = ("id", "fund_code", "name", "custodian", "imprest_amount", "replenish_trigger_pct", "gl_account", "segment", "is_active")


class PCFReplenishmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PCFReplenishment
        fields = ("id", "fund", "request_date", "amount", "expenses", "journal_entry", "status")


class InterAccountTransferSerializer(serializers.ModelSerializer):
    class Meta:
        model = InterAccountTransfer
        fields = ("id", "transfer_date", "from_account", "to_account", "amount", "purpose", "reference", "journal_entry")


class CashFlowStatementSerializer(serializers.ModelSerializer):
    identity_holds = serializers.BooleanField(read_only=True)

    class Meta:
        model = CashFlowStatement
        fields = ("id", "period_start", "period_end", "collections", "payments_to_depot", "operating_expenses", "gross_markup", "asset_acquisitions", "asset_disposals", "loan_proceeds", "loan_repayments", "net_change", "beginning_cash", "ending_cash", "adb_adjustments", "identity_holds")


class CheckDisbursementSerializer(serializers.ModelSerializer):
    class Meta:
        model = CheckDisbursement
        fields = ("id", "cv", "status", "signed_by_cnr", "signed_at", "released_by_quibs", "released_at", "cleared_at", "clearing_bank_account")


class CollectiblesWorksheetSerializer(serializers.ModelSerializer):
    class Meta:
        model = CollectiblesWorksheet
        fields = ("id", "cycle", "department", "client_paid", "depot_paid", "gross_markup")


class CashShortExcessWorksheetSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashShortExcessWorksheet
        fields = ("id", "cycle", "segment", "expected_cash", "actual_cash", "variance", "cause", "cause_category", "status")