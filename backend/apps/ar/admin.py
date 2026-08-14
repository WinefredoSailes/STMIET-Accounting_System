from django.contrib import admin

from .models import (
    AcknowledgmentReceipt,
    ARInvoice,
    ARInvoiceLine,
    CashShortExcess,
    Customer,
    Deposit,
    PriceSnapshot,
)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "group", "segment", "pricing_tier")
    list_filter = ("group", "segment", "pricing_tier")
    search_fields = ("code", "name")


@admin.register(PriceSnapshot)
class PriceSnapshotAdmin(admin.ModelAdmin):
    list_display = ("customer", "product_code", "cycle_start", "unit_price", "tier")
    list_filter = ("tier",)


class ARInvoiceLineInline(admin.TabularInline):
    model = ARInvoiceLine
    extra = 1


@admin.register(ARInvoice)
class ARInvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_no", "customer", "transaction_date", "total", "status", "is_paid_on_delivery")
    list_filter = ("status", "is_paid_on_delivery", "segment")
    search_fields = ("invoice_no", "customer__name")
    inlines = [ARInvoiceLineInline]


@admin.register(AcknowledgmentReceipt)
class AcknowledgmentReceiptAdmin(admin.ModelAdmin):
    list_display = ("receipt_no", "customer", "transaction_date", "amount", "payment_method", "applied_to")
    list_filter = ("payment_method", "segment")
    search_fields = ("receipt_no", "customer__name")


@admin.register(Deposit)
class DepositAdmin(admin.ModelAdmin):
    list_display = ("transaction_date", "bank_account", "amount", "reference")
    search_fields = ("reference",)


@admin.register(CashShortExcess)
class CashShortExcessAdmin(admin.ModelAdmin):
    list_display = ("cycle_start", "segment", "expected_cash", "actual_cash", "variance", "status")
    list_filter = ("segment", "status")