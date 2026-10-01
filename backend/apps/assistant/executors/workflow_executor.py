from __future__ import annotations

from .base_executor import BaseExecutor, Group


class WorkflowExecutor(BaseExecutor):
    module_name = "workflow"
    screen_key = "my_approvals"

    def _query(self) -> list[Group]:
        from apps.workflow.models import ApprovalRequest

        qs = ApprovalRequest.objects.select_related("submitted_by", "content_type")
        return [self._make_group(
            "Approvals", qs,
            lambda r: {
                "type": "approval", "id": r.id,
                "name": f"{r.content_type.model} #{r.object_id}",
                "code": r.status, "status": r.status,
                "date": r.created_at.date().isoformat() if r.created_at else None,
                "link": "/approvals/",
            },
            search_fields=["content_type__model"],
            date_field="created_at", status_field="status",
            status_map={"pending": ["submitted"], "approved": ["approved"],
                        "rejected": ["rejected"], "draft": ["draft"]},
        )]
