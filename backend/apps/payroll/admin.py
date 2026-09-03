from django.contrib import admin

from .models import PayrollFeed, PayrollFeedLine


class PayrollFeedLineInline(admin.TabularInline):
    model = PayrollFeedLine
    extra = 0


@admin.register(PayrollFeed)
class PayrollFeedAdmin(admin.ModelAdmin):
    list_display = (
        "batch_reference", "entity", "segment", "period_start", "period_end",
        "net_pay_total", "status", "posted_at",
    )
    list_filter = ("status", "entity")
    search_fields = ("batch_reference",)
    readonly_fields = ("id", "created_at", "updated_at", "posted_at", "reviewed_at")
    inlines = [PayrollFeedLineInline]