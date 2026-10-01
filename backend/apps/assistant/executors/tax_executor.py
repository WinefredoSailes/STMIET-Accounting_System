from __future__ import annotations

from .base_executor import BaseExecutor, Group


class TaxExecutor(BaseExecutor):
    module_name = "tax"
    screen_key = "tax_dashboard"

    def _query(self) -> list[Group]:
        from apps.tax.models import VATComputation, WithholdingCertificate, TaxCalendar

        groups: list[Group] = []

        qs = VATComputation.objects.select_related("invoice")
        groups.append(self._make_group(
            "VAT (per invoice)", qs,
            lambda v: {
                "type": "vat", "id": v.id,
                "name": v.invoice.invoice_no if v.invoice_id else f"VAT #{v.id}",
                "code": "", "amount": str(v.output_vat), "link": "/reports/tax/vat/",
            },
            search_fields=["invoice__invoice_no"],
        ))

        qs = WithholdingCertificate.objects.select_related("segment")
        groups.append(self._make_group(
            "WHT Certificates", qs,
            lambda w: {
                "type": "wht", "id": w.id, "name": w.cert_type,
                "code": w.cv_number or w.tin, "amount": str(w.tax_amount),
                "link": "/reports/tax/wht/",
            },
            search_fields=["cv_number", "tin"],
        ))

        qs = TaxCalendar.objects.all()
        groups.append(self._make_group(
            "Tax Calendar", qs,
            lambda t: {
                "type": "tax_item", "id": t.id, "name": f"{t.form} · {t.filing_period}",
                "code": t.form, "status": t.status,
                "amount": str(t.amount_due),
                "date": t.due_date.isoformat() if t.due_date else None,
                "link": "/reports/tax/calendar/",
            },
            search_fields=["form", "filing_period"],
            date_field="due_date",
        ))
        return groups
