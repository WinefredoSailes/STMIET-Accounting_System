"""Fleet services: fuel consumption logging + reporting (Phase 5 build-out)."""

from apps.core.exceptions import ValidationError
from apps.core.money import money


def record_fuel_log(*, vehicle, logged_at, liters, cost_amount, segment=None, notes="", user=None):
    """Record a fuel log entry (management record — no JE, POSTING_RULES 11)."""
    from .models import FuelLog

    liters = money(liters)
    cost = money(cost_amount)
    if liters < 0 or cost < 0:
        raise ValidationError("Liters and cost must not be negative.")
    return FuelLog.objects.create(
        vehicle=vehicle,
        logged_at=logged_at,
        liters=liters,
        cost_amount=cost,
        segment=segment or vehicle.segment,
        notes=notes,
    )


def fleet_fuel_summary(*, start=None, end=None, segment=None) -> dict:
    """Per-vehicle fuel totals + a dated register for the fleet fuel report."""
    from django.db.models import Sum

    from .models import FuelLog

    logs = FuelLog.objects.select_related("vehicle", "vehicle__segment", "segment")
    if start:
        logs = logs.filter(logged_at__gte=start)
    if end:
        logs = logs.filter(logged_at__lte=end)
    if segment:
        logs = logs.filter(segment__code=segment)

    rows = list(logs.order_by("vehicle__plate_no", "logged_at", "id"))

    totals = (
        logs.values("vehicle_id", "vehicle__plate_no", "vehicle__make_model")
        .annotate(liters_total=Sum("liters"), cost_total=Sum("cost_amount"))
        .order_by("vehicle__plate_no")
    )
    per_vehicle = [
        {
            "plate_no": row["vehicle__plate_no"],
            "make_model": row["vehicle__make_model"],
            "liters": money(row["liters_total"]),
            "cost": money(row["cost_total"]),
        }
        for row in totals
    ]
    return {
        "rows": rows,
        "per_vehicle": per_vehicle,
        "liters_total": money(sum(t["liters"] for t in per_vehicle)),
        "cost_total": money(sum(t["cost"] for t in per_vehicle)),
    }