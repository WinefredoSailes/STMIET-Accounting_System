from __future__ import annotations

from django.db.models import Count, Sum

from .base_executor import BaseExecutor, Group


class ARExecutor(BaseExecutor):
    module_name = "ar"
    screen_key = "customer_list"

    def _query(self) -> list[Group]:
        from apps.ar.models import Customer, ARInvoice, AcknowledgmentReceipt

        h_cust = self._has("customer", "client", "buyer")
        h_inv = self._has("invoice", "billing", "si", "unpaid")
        h_rec = self._has("receipt", "collection", "deposit")
        any_doc = h_inv or h_rec
        fan_out = self.is_text_search and not any_doc

        want_customers = h_cust or not any_doc
        want_invoices = h_inv or fan_out
        want_receipts = h_rec or fan_out

        groups: list[Group] = []

        if want_customers:
            qs = Customer.objects.annotate(
                total_amount=Sum("invoices__total", default=0),
                total_invoices=Count("invoices", distinct=True),
                total_receipts=Count("receipts", distinct=True),
            )
            groups.append(self._make_group(
                "Customers", qs,
                lambda c: {
                    "type": "customer", "id": c.id, "name": c.name, "code": c.code,
                    "total_invoices": c.total_invoices, "total_receipts": c.total_receipts,
                    "amount": str(c.total_amount or 0),
                    "link": f"/ar/customers/{c.id}/",
                },
                search_fields=["name", "code", "owner_name"],
                amount_field="total_amount", order=("name",),
            ))

        if want_invoices:
            qs = ARInvoice.objects.select_related("customer")
            groups.append(self._make_group(
                "Invoices", qs,
                lambda v: {
                    "type": "invoice", "id": v.id, "name": v.invoice_no,
                    "code": v.invoice_no, "customer": v.customer.name if v.customer_id else "",
                    "amount": str(v.total), "status": v.status,
                    "date": v.transaction_date.isoformat() if v.transaction_date else None,
                    "link": f"/ar/invoices/{v.id}/",
                },
                search_fields=["invoice_no", "customer__name"],
                date_field="transaction_date", status_field="status",
                status_map={"unpaid": ["open", "partially_paid"], "paid": ["paid"],
                            "posted": ["posted", "open"]},
                amount_field="total",
            ))

        if want_receipts:
            qs = AcknowledgmentReceipt.objects.select_related("customer")
            groups.append(self._make_group(
                "Receipts", qs,
                lambda r: {
                    "type": "receipt", "id": r.id, "name": r.receipt_no,
                    "code": r.receipt_no, "customer": r.customer.name if r.customer_id else "",
                    "amount": str(r.amount), "status": r.status,
                    "date": r.transaction_date.isoformat() if r.transaction_date else None,
                    "link": f"/ar/receipts/{r.id}/",
                },
                search_fields=["receipt_no", "customer__name", "check_no"],
                date_field="transaction_date", status_field="status",
                status_map={"pending": ["draft", "submitted"], "posted": ["posted"]},
                amount_field="amount",
            ))

        return groups
