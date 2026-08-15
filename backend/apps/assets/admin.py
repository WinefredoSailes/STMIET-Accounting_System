from django.contrib import admin

from .models import Asset, AssetCategory, AssetDisposal, DepreciationSchedule


@admin.register(AssetCategory)
class AssetCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "useful_life_years", "segment", "is_active")
    list_filter = ("segment", "is_active")
    search_fields = ("code", "name")


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("asset_no", "name", "category", "segment", "acquisition_date",
                    "cost", "net_book_value", "status")
    list_filter = ("status", "segment", "category")
    search_fields = ("asset_no", "name")


@admin.register(DepreciationSchedule)
class DepreciationScheduleAdmin(admin.ModelAdmin):
    list_display = ("asset", "period_start", "period_end", "amount", "status", "is_still_in_use")
    list_filter = ("status", "is_still_in_use")
    ordering = ("asset", "period_start")


@admin.register(AssetDisposal)
class AssetDisposalAdmin(admin.ModelAdmin):
    list_display = ("asset", "disposal_date", "proceeds", "gain", "status")
    list_filter = ("status",)
