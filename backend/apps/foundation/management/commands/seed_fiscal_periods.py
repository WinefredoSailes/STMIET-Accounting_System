"""Seed the monthly FiscalPeriod rows for a company's FiscalYear.

STMIET runs a calendar FY (Jan-Dec); periods 1..12 map to each month, with an
optional 13th period reserved for year-end adjustments (BUILD-PLAN Phase 8 close).

Idempotent: existing (fiscal_year, period_no) rows are left untouched.

Usage:
    py manage.py seed_fiscal_periods --company STMIET --year 2026
    py manage.py seed_fiscal_periods --company STMIET --year 2026 --periods 13
"""

import calendar
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.foundation.models import Company, FiscalPeriod, FiscalYear


class Command(BaseCommand):
    help = "Seed monthly fiscal periods for a fiscal year (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--company", dest="company", default="STMIET")
        parser.add_argument("--year", dest="year", type=int, default=2026)
        parser.add_argument("--periods", dest="periods", type=int, default=12,
                            help="Number of monthly periods (12, or 13 incl. adjustments).")

    def handle(self, *args, **options):
        company = Company.objects.filter(code=options["company"]).first()
        if company is None:
            raise CommandError(f"Company '{options['company']}' not found. Run import_coa first.")

        fy = FiscalYear.objects.filter(company=company, start_date__year=options["year"]).first()
        if fy is None:
            raise CommandError(
                f"No FiscalYear for {options['year']} found for {company.code}. "
                f"Create one first (e.g. via admin)."
            )

        periods = options["periods"]
        if periods not in (12, 13):
            raise CommandError("--periods must be 12 (or 13 with the adjustment period).")

        created = 0
        existing = 0
        for period_no in range(1, periods + 1):
            if period_no == 13:
                # Year-end adjustment period runs to the last day of the year.
                start_date = date(fy.start_date.year, 12, 31)
                end_date = fy.end_date
            else:
                start_date = date(fy.start_date.year, period_no, 1)
                end_date = date(fy.start_date.year, period_no, calendar.monthrange(
                    fy.start_date.year, period_no
                )[1])

            if FiscalPeriod.objects.filter(fiscal_year=fy, period_no=period_no).exists():
                existing += 1
                continue
            FiscalPeriod.objects.create(
                fiscal_year=fy,
                period_no=period_no,
                start_date=start_date,
                end_date=end_date,
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f"seed_fiscal_periods: {created} created, {existing} already present for "
            f"{company.code} FY{fy.start_date.year}."
        ))
