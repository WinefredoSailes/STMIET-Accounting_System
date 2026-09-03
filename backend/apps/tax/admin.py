from django.contrib import admin

from .models import IncomeTaxProvision, TaxCalendar, VATComputation, WithholdingCertificate


@admin.register(TaxCalendar)
class TaxCalendarAdmin(admin.ModelAdmin):
    list_display = ("form", "company", "filing_period", "due_date", "status", "amount_due")
    list_filter = ("form", "status", "company")
    search_fields = ("form", "filing_period")


@admin.register(VATComputation)
class VATComputationAdmin(admin.ModelAdmin):
    list_display = ("invoice", "segment", "gross_amount", "output_vat")
    list_filter = ("segment",)


@admin.register(WithholdingCertificate)
class WithholdingCertificateAdmin(admin.ModelAdmin):
    list_display = ("cert_type", "payee", "tin", "gross_amount", "tax_amount", "cv_number")
    list_filter = ("cert_type",)


@admin.register(IncomeTaxProvision)
class IncomeTaxProvisionAdmin(admin.ModelAdmin):
    list_display = ("segment", "filing_period", "taxable_income", "tax_amount", "journal_entry")
    list_filter = ("segment",)
