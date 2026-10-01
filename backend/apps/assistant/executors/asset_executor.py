from __future__ import annotations

from .base_executor import BaseExecutor, Group


class AssetExecutor(BaseExecutor):
    module_name = "assets"
    screen_key = "asset_list"

    def _query(self) -> list[Group]:
        from apps.assets.models import Asset

        qs = Asset.objects.select_related("category")
        return [self._make_group(
            "Assets", qs,
            lambda a: {
                "type": "asset", "id": a.id, "name": a.name, "code": a.asset_no,
                "category": a.category.name if a.category_id else "",
                "amount": str(a.cost), "status": a.status,
                "date": a.acquisition_date.isoformat() if a.acquisition_date else None,
                "link": f"/assets/{a.id}/",
            },
            search_fields=["asset_no", "name", "category__name", "reference"],
            date_field="acquisition_date", status_field="approval_status",
            status_map={"pending": ["draft", "submitted"], "approved": ["approved", "posted"]},
            amount_field="cost",
        )]
