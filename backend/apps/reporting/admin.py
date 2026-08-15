from django.contrib import admin

from .models import FinancialStatement, MonthEndClose, StatementLineDef, StatementTemplate


class StatementLineDefInline(admin.TabularInline):
    model = StatementLineDef
    extra = 0


@admin.register(StatementTemplate)
class StatementTemplateAdmin(admin.ModelAdmin):
    list_display = ("statement_type", "name")
    inlines = [StatementLineDefInline]


@admin.register(FinancialStatement)
class FinancialStatementAdmin(admin.ModelAdmin):
    list_display = ("statement_type", "company", "segment", "period_start", "period_end",
                    "identity_ok", "status", "generated_at")
    list_filter = ("statement_type", "status", "identity_ok")
    readonly_fields = ("data", "identity_ok", "identity_note", "generated_at")


@admin.register(MonthEndClose)
class MonthEndCloseAdmin(admin.ModelAdmin):
    list_display = ("fiscal_period", "status", "closed_at")
    list_filter = ("status",)
    readonly_fields = ("steps",)
