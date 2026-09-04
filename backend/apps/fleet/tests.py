"""Fleet / vehicle register contract tests (BUILD-PLAN Phase 10 master data)."""

import csv
from io import StringIO

import pytest
from django.core.management import call_command

from apps.fleet.models import Vehicle, VehicleType


class TestImportVehicles:
    def test_creates_and_is_idempotent(self, tmp_path, company, segment):
        path = tmp_path / "vehicles.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["PLATE NO", "MAKE MODEL", "TYPE", "SEGMENT"])
            writer.writerow(["ABC-1234", "Hino FV", "fuel tanker", "DHPP"])
            writer.writerow(["DEF-5678", "Isuzu boom", "boom truck", ""])
        call_command("import_vehicles", file=str(path), stdout=StringIO())

        v1 = Vehicle.objects.get(plate_no="ABC-1234")
        assert v1.make_model == "Hino FV"
        assert v1.vehicle_type == VehicleType.FUEL_TANKER
        assert v1.segment.code == "DHPP"
        assert Vehicle.objects.get(plate_no="DEF-5678").vehicle_type == VehicleType.BOOM_TRUCK

        call_command("import_vehicles", file=str(path), stdout=StringIO())
        assert Vehicle.objects.filter(plate_no="ABC-1234").count() == 1
