from rest_framework import serializers

from .models import (
    BankAccount,
    BankReconciliation,
    BankReconLine,
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
        fields = ("id", "code", "name", "account_type", "bank_name", "bank_code", "gl_account", "company", "adb_required", "reconciliation_frequency", "custodian", "is_active")


class BankReconLineSerializer(serializers.ModelSerializer):
    category_label = serializers.CharField(source="get_category_display", read_only=True)

    class Meta:
        model = BankReconLine
        fields = ("id", "recon", "side", "category", "category_label", "amount", "reference", "description", "match_status", "adjustment_je")
        read_only_fields = ("recon",)


class BankReconciliationSerializer(serializers.ModelSerializer):
    lines = BankReconLineSerializer(many=True, read_only=True)
    variance = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    is_locked = serializers.BooleanField(read_only=True)

    class Meta:
        model = BankReconciliation
        fields = ("id", "cycle", "bank_account", "period_start", "period_end", "frequency",
                  "book_balance", "bank_statement_balance", "difference",
                  "typo_adjustment", "pop_adjustment", "cashier_adjustment", "unresolved",
                  "unadjusted_book_balance", "unadjusted_bank_balance", "is_balances_captured",
                  "adjusted_bank_balance", "adjusted_book_balance", "variance", "is_locked",
                  "status", "prepared_by", "prepared_at",
                  "pre_approved_by", "pre_approved_at", "approved_by", "approved_at",
                  "rejection_note", "lines")


class WeeklyCashCycleSerializer(serializers.ModelSerializer):
    activities = CashCycleActivitySerializer(many=True, read_only=True)

    class Meta:
        model = WeeklyCashCycle
        fields = ("id", "cycle_start", "cycle_end", "segment", "closing_balance", "status", "notes", "activities")


class PettyCashFundSerializer(serializers.ModelSerializer):
    class Meta:
        model = PettyCashFund
        fields = ("id", "fund_code", "name", "custodian_name", "custodian", "imprest_amount", "replenish_trigger_pct", "gl_account", "company", "is_active")


class PCFReplenishmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PCFReplenishment
        fields = ("id", "voucher_no", "fund", "request_date", "amount", "payee_name", "reference", "cost_center", "expenses", "journal_entry", "status", "requested_by", "approved_by", "approved_at", "rejected_by", "rejected_at", "rejection_note", "conso", "cv")
        read_only_fields = ("status", "approved_by", "approved_at", "rejected_by", "rejected_at", "rejection_note")


class InterAccountTransferSerializer(serializers.ModelSerializer):
    class Meta:
        model = InterAccountTransfer
        fields = ("id", "transfer_date", "voucher_no", "from_account", "to_account", "amount", "purpose", "reference", "journal_entry", "status", "initiated_by", "approved_by", "approved_at", "rejected_by", "rejected_at", "rejection_note", "check_no", "cost_center")


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