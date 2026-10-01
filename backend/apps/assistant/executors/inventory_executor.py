from __future__ import annotations

from .base_executor import BaseExecutor, Group


class InventoryExecutor(BaseExecutor):
    module_name = "inventory"
    screen_key = ""

    def _query(self) -> list[Group]:
        from apps.inventory.models import InventoryEvent

        qs = InventoryEvent.objects.all()
        return [self._make_group(
            "Inventory Events", qs,
            lambda e: {
                "type": "inventory_event", "id": e.id, "name": e.event_key,
                "code": e.event_type, "status": e.status,
                "date": e.occurred_on.isoformat() if e.occurred_on else None,
                "link": "/",
            },
            search_fields=["event_key", "event_type"],
            date_field="occurred_on",
        )]
