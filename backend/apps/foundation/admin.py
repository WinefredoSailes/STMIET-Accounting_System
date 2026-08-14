from django.contrib import admin

from apps.foundation.models import Account, Company, FiscalPeriod, FiscalYear, Segment


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "tin", "rdo_code")
    search_fields = ("code", "name")


@admin.register(Segment)
class SegmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "coa_key_digit", "company")
    list_filter = ("company",)


@admin.register(FiscalYear)
class FiscalYearAdmin(admin.ModelAdmin):
    list_display = ("company", "code", "start_date", "end_date", "is_closed")
    list_filter = ("company", "is_closed")


@admin.register(FiscalPeriod)
class FiscalPeriodAdmin(admin.ModelAdmin):
    list_display = ("fiscal_year", "period_no", "start_date", "end_date", "is_closed")
    list_filter = ("fiscal_year__company", "is_closed")


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "account_type", "normal_balance", "segment", "is_control", "is_postable")
    list_filter = ("account_type", "segment", "is_control", "is_postable")
    search_fields = ("code", "name")