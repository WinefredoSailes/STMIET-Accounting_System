from __future__ import annotations

from .base_executor import BaseExecutor, Group


class ReportingExecutor(BaseExecutor):
    module_name = "reporting"
    screen_key = "trial_balance"

    def _query(self) -> list[Group]:
        from apps.reporting.models import FinancialStatement, StatementType

        labels = dict(StatementType.choices)
        qs = FinancialStatement.objects.select_related("segment")
        return [self._make_group(
            "Financial Statements", qs,
            lambda s: {
                "type": "statement", "id": s.id,
                "name": f"{labels.get(s.statement_type, s.statement_type)} ({s.period_start} – {s.period_end})",
                "code": s.statement_type, "status": s.status,
                "date": s.period_end.isoformat() if s.period_end else None,
                "link": f"/reports/{s.statement_type}/",
            },
            search_fields=["statement_type"],
            date_field="period_end",
        )]
