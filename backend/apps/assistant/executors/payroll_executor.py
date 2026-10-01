from __future__ import annotations

from .base_executor import BaseExecutor, Group


class PayrollExecutor(BaseExecutor):
    module_name = "payroll"
    screen_key = ""

    def _query(self) -> list[Group]:
        from apps.payroll.models import PayrollFeed

        qs = PayrollFeed.objects.all()
        return [self._make_group(
            "Payroll Feeds", qs,
            lambda p: {
                "type": "payroll", "id": p.id, "name": p.batch_reference,
                "code": p.batch_reference, "amount": str(p.net_pay_total),
                "status": p.status,
                "date": p.period_start.isoformat() if p.period_start else None,
                "link": "/",
            },
            search_fields=["batch_reference", "entity", "cost_center"],
            date_field="period_start", amount_field="net_pay_total",
        )]
