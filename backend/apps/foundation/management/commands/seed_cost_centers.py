"""Seed the organizational cost centers (ADR-038 §8).

AG-Accounting, OS-Operations, TL-Technical Services,
HRAC-HR/Audit/Compliance (ADR-038 §8e); DHPP-Distribution and Hauling of
Petroleum Products and DMIE-Distribution of Machineries and Industrial
Equipment (ADR-038 §8a-b); and OPS-Other Products and Services (ADR-038 §8c).

Idempotent: existing codes are updated in place, missing ones created.

Usage:
    py manage.py seed_cost_centers
"""

from django.core.management.base import BaseCommand

from apps.foundation.models import CostCenter

DEFAULT_COST_CENTERS = [
    ("AG", "Accounting"),
    ("OS", "Operations"),
    ("TL", "Technical Services"),
    ("HRAC", "HR / Audit / Compliance"),
    ("DHPP", "Distribution and Hauling of Petroleum Products"),
    ("DMIE", "Distribution of Machineries and Industrial Equipment"),
    ("OPS", "Other Products and Services"),
]


class Command(BaseCommand):
    help = "Seed cost centers (idempotent)."

    def handle(self, *args, **options):
        created, updated = 0, 0
        for code, name in DEFAULT_COST_CENTERS:
            cc, was_created = CostCenter.objects.get_or_create(
                code=code, defaults={"name": name, "is_active": True}
            )
            if was_created:
                created += 1
            elif cc.name != name:
                cc.name = name
                cc.save(update_fields=["name", "updated_at"])
                updated += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Cost centers ready: {created} created, {updated} updated, "
                f"{CostCenter.objects.count()} total."
            )
        )