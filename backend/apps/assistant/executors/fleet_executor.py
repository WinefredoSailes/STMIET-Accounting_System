from __future__ import annotations

from .base_executor import BaseExecutor, Group


class FleetExecutor(BaseExecutor):
    module_name = "fleet"
    screen_key = "fleet_fuel"

    def _query(self) -> list[Group]:
        from apps.fleet.models import Vehicle, FuelLog

        filtered = not self.browsing
        want_vehicles = filtered or self._has("vehicle", "plate", "truck", "car") or not self._has("fuel")
        want_fuel = filtered or self._has("fuel", "diesel", "gasoline", "liters")

        groups: list[Group] = []
        if want_vehicles:
            qs = Vehicle.objects.all()
            groups.append(self._make_group(
                "Vehicles", qs,
                lambda v: {
                    "type": "vehicle", "id": v.id, "name": v.plate_no,
                    "code": v.plate_no, "make_model": v.make_model,
                    "link": "/reports/fleet/fuel/",
                },
                search_fields=["plate_no", "make_model"],
            ))
        if want_fuel:
            qs = FuelLog.objects.select_related("vehicle")
            groups.append(self._make_group(
                "Fuel Logs", qs,
                lambda f: {
                    "type": "fuel_log", "id": f.id,
                    "name": f"{f.vehicle.plate_no} · {f.logged_at}",
                    "code": "", "amount": str(f.cost_amount),
                    "date": f.logged_at.date().isoformat() if f.logged_at else None,
                    "link": "/reports/fleet/fuel/",
                },
                search_fields=["vehicle__plate_no", "notes"],
                date_field="logged_at", amount_field="cost_amount",
            ))
        return groups
