from django.contrib import admin

from .models import InventoryEvent, InventoryEventLine


class InventoryEventLineInline(admin.TabularInline):
    model = InventoryEventLine
    extra = 0


@admin.register(InventoryEvent)
class InventoryEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_key", "event_type", "segment", "occurred_on", "status",
        "retry_count", "processed_at",
    )
    list_filter = ("status", "event_type", "segment")
    search_fields = ("event_key", "payload")
    readonly_fields = ("id", "created_at", "updated_at", "processed_at")
    inlines = [InventoryEventLineInline]