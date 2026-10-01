"""Backfill ``account_name`` into stored PCF replenishment expense dicts.

Deployment wiring for this repair is the cash 0022 data migration, which
runs automatically via the entrypoint's ``migrate --run-sync`` (ADR-040).
This command is the manual equivalent for the same job: idempotent, it can
be re-run any time (e.g. after out-of-band data imports) to persist titles
that the stored JSON is still missing. The voucher detail screen also
resolves missing names live from the COA, so unbackfilled rows display
correctly regardless.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.cash.models import PCFReplenishment
from apps.foundation.models import Account


class Command(BaseCommand):
    help = "Backfill account_name into PCF replenishment expense dicts"

    def handle(self, *args, **options):
        count = 0
        lines = 0
        with transaction.atomic():
            for replen in PCFReplenishment.objects.all():
                expenses = list(replen.expenses or [])
                missing = {
                    e.get("account_code", "")
                    for e in expenses
                    if e.get("account_code") and not e.get("account_name")
                }
                if not missing:
                    continue
                name_by_code = dict(
                    Account.objects.filter(code__in=missing).values_list("code", "name")
                )
                updated = False
                for exp in expenses:
                    code = exp.get("account_code", "")
                    if code and not exp.get("account_name") and name_by_code.get(code):
                        exp["account_name"] = name_by_code[code]
                        updated = True
                        lines += 1
                if updated:
                    replen.expenses = expenses
                    replen.save(update_fields=["expenses", "updated_at"])
                    count += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Backfilled account_name on {lines} expense line(s) across {count} PCF replenishment(s)."
            )
        )
