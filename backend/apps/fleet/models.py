"""Fleet bounded context (BUILD-PLAN Phase 5/7).

Phase 7 needs the Asset↔Vehicle link (vehicles ARE assets — 17000-18650), so
a minimal Vehicle register is introduced here. The Phase 5 build-out adds trip
and fuel-consumption records that drive the fleet fuel management report.
"""

from django.db import models

from apps.core.models import AuditableModel


class VehicleType(models.TextChoices):
    FUEL_TANKER = "fuel_tanker", "Fuel Tanker"
    BOOM_TRUCK = "boom_truck", "Boom Truck"
    OFFICE_VEHICLE = "office_vehicle", "Office Vehicle"
    OTHER = "other", "Other"


class Vehicle(AuditableModel):
    """Vehicle register (Phase 7 minimal; expanded in Phase 5)."""

    plate_no = models.CharField(max_length=32, unique=True)
    make_model = models.CharField(max_length=128, blank=True)
    vehicle_type = models.CharField(max_length=24, choices=VehicleType.choices, default=VehicleType.OTHER)
    segment = models.ForeignKey(
        "foundation.Segment", null=True, blank=True, on_delete=models.SET_NULL, related_name="vehicles"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["plate_no"]

    def __str__(self):
        return f"{self.plate_no} {self.make_model}"


class FuelLog(AuditableModel):
    """Fuel consumption log per vehicle (Phase 5 fleet build-out).

    An operational management record that drives the fleet fuel report. Fuel
    spend is booked to the GL through RFPs / loan clearances (POSTING_RULES
    11), so a log entry itself has no JE.
    """

    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="fuel_logs")
    logged_at = models.DateField(db_index=True)
    liters = models.DecimalField(max_digits=12, decimal_places=2)
    cost_amount = models.DecimalField(max_digits=18, decimal_places=2)
    segment = models.ForeignKey(
        "foundation.Segment", null=True, blank=True, on_delete=models.SET_NULL, related_name="fuel_logs"
    )
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-logged_at", "-id"]

    def __str__(self):
        return f"{self.vehicle.plate_no} {self.logged_at:%Y-%m-%d} {self.liters} L"
