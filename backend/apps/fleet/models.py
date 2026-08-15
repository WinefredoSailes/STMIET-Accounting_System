"""Fleet bounded context (BUILD-PLAN Phase 5/7).

Phase 7 needs the Asset↔Vehicle link (vehicles ARE assets — 17000-18650), so
a minimal Vehicle register is introduced here. Trip, fuel consumption and
maintenance records arrive with the Phase 5 fleet build-out.
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
