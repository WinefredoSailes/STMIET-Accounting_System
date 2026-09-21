from django.contrib import admin

from .models import BillingDocument, BillingLine


class BillingLineInline(admin.TabularInline):
    model = BillingLine
    extra = 1


@admin.register(BillingDocument)
class BillingDocumentAdmin(admin.ModelAdmin):
    list_display = ("billing_no", "billing_date", "billing_type", "party_name", "amount", "status", "rfp")
    list_filter = ("billing_type", "status", "segment")
    search_fields = ("billing_no", "party_name", "particulars")
    inlines = [BillingLineInline]