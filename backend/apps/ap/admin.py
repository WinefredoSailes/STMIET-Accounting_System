from django.contrib import admin

from .models import AdvanceToEmployee, CheckVoucher, CONSOBatch, RFPDocument, RFPLine, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "supplier_type", "tin", "last_ap")
    list_filter = ("supplier_type",)
    search_fields = ("code", "name")


class RFPLineInline(admin.TabularInline):
    model = RFPLine
    extra = 1


@admin.register(RFPDocument)
class RFPDocumentAdmin(admin.ModelAdmin):
    list_display = ("ap_number", "rfp_date", "payee", "amount", "advance_amount", "status", "conso")
    list_filter = ("status", "segment")
    search_fields = ("ap_number", "payee__name", "particulars")
    inlines = [RFPLineInline]


@admin.register(CONSOBatch)
class CONSOBatchAdmin(admin.ModelAdmin):
    list_display = ("batch_no", "conso_date", "status", "total_amount", "reviewed_by")
    list_filter = ("status",)


@admin.register(CheckVoucher)
class CheckVoucherAdmin(admin.ModelAdmin):
    list_display = ("cv_number", "cv_date", "payee", "gross_amount", "withheld_tax", "net_amount", "status")
    list_filter = ("status", "bank_account")


@admin.register(AdvanceToEmployee)
class AdvanceToEmployeeAdmin(admin.ModelAdmin):
    list_display = ("employee_name", "kind", "granted_date", "amount", "liquidated_amount", "status")
    list_filter = ("kind", "status", "segment")