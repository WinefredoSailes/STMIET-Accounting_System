from __future__ import annotations

from .base_executor import BaseExecutor, Group


class BillingExecutor(BaseExecutor):
    module_name = "billing"
    screen_key = "billing_list"

    def _query(self) -> list[Group]:
        from apps.billing.models import BillingDocument

        qs = BillingDocument.objects.select_related("customer", "supplier")
        return [self._make_group(
            "Billing Documents", qs,
            lambda b: {
                "type": "billing", "id": b.id, "name": b.billing_no,
                "code": b.billing_no, "party": b.party_name,
                "amount": str(b.amount), "status": b.status,
                "date": b.billing_date.isoformat() if b.billing_date else None,
                "link": f"/billing/{b.id}/",
            },
            search_fields=["billing_no", "party_name", "particulars", "reference"],
            date_field="billing_date", status_field="status",
            status_map={"pending": ["draft", "submitted"],
                        "approved": ["approved", "posted"], "posted": ["posted"]},
            amount_field="amount",
        )]
