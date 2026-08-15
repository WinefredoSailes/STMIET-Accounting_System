from django.contrib import admin

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


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "bank_name", "account_type", "segment", "adb_required", "is_active")
    list_filter = ("account_type", "segment", "is_active")
    search_fields = ("code", "name", "bank_name")


@admin.register(WeeklyCashCycle)
class WeeklyCashCycleAdmin(admin.ModelAdmin):
    list_display = ("segment", "cycle_start", "cycle_end", "closing_balance", "status")
    list_filter = ("status", "segment")
    ordering = ("-cycle_start",)


@admin.register(CashCycleActivity)
class CashCycleActivityAdmin(admin.ModelAdmin):
    list_display = ("cycle", "activity_type", "amount", "bank_account")
    list_filter = ("activity_type", "cycle__segment")
    ordering = ("cycle", "activity_type")


@admin.register(BankReconciliation)
class BankReconciliationAdmin(admin.ModelAdmin):
    list_display = ("cycle", "bank_account", "book_balance", "bank_statement_balance", "difference", "status")
    list_filter = ("status", "cycle__segment")
    search_fields = ("bank_account__code",)


@admin.register(PettyCashFund)
class PettyCashFundAdmin(admin.ModelAdmin):
    list_display = ("fund_code", "name", "custodian", "imprest_amount", "replenish_trigger_pct", "is_active")
    list_filter = ("is_active",)


@admin.register(PCFReplenishment)
class PCFReplenishmentAdmin(admin.ModelAdmin):
    list_display = ("fund", "request_date", "amount", "status")
    list_filter = ("status", "fund")


@admin.register(InterAccountTransfer)
class InterAccountTransferAdmin(admin.ModelAdmin):
    list_display = ("transfer_date", "from_account", "to_account", "amount", "purpose")
    search_fields = ("purpose", "reference")


@admin.register(CashFlowStatement)
class CashFlowStatementAdmin(admin.ModelAdmin):
    list_display = ("period_start", "period_end", "collections", "payments_to_depot", "net_change")
    ordering = ("-period_end",)


@admin.register(CheckDisbursement)
class CheckDisbursementAdmin(admin.ModelAdmin):
    list_display = ("cv", "status", "signed_at", "released_at", "cleared_at")
    list_filter = ("status",)


@admin.register(CollectiblesWorksheet)
class CollectiblesWorksheetAdmin(admin.ModelAdmin):
    list_display = ("cycle", "department", "client_paid", "depot_paid", "gross_markup")
    list_filter = ("department", "cycle__segment")


@admin.register(CashShortExcessWorksheet)
class CashShortExcessWorksheetAdmin(admin.ModelAdmin):
    list_display = ("cycle", "segment", "expected_cash", "actual_cash", "variance", "cause_category", "status")
    list_filter = ("status", "segment")