"""Month-end depreciation automation (ADR-038): post the monthly straight-line
depreciation JE for every active fixed asset in one run.

Idempotent — DepreciationService.post_all skips months already posted, so the
command is safe to re-run and to schedule (cron / Windows Task Scheduler) at
every month end.

    python manage.py post_depreciation --period 2026-01
"""

from datetime import date

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Post monthly depreciation for all active fixed assets (ADR-038)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--period",
            default=None,
            help="Month to accrue, YYYY-MM (defaults to the current calendar month).",
        )

    def handle(self, *args, **options):
        from apps.assets.services import DepreciationService

        raw = options["period"]
        if raw:
            try:
                year, month = (int(part) for part in raw.split("-"))
                period_start = date(year, month, 1)
            except (ValueError, TypeError):
                self.stderr.write(f"Invalid --period {raw!r}; expected YYYY-MM.")
                raise SystemExit(1)
        else:
            today = date.today()
            period_start = date(today.year, today.month, 1)

        summary = DepreciationService.post_all(period_start=period_start, user=None)
        self.stdout.write(
            self.style.SUCCESS(
                f"Depreciation for {summary['period_start']:%Y-%m}: "
                f"{len(summary['posted'])} posted, "
                f"{len(summary['skipped'])} skipped/already posted."
            )
        )