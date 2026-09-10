"""Operator CLI for the month-end close posting step (ADR-013, §13).

Posts the closing journal entries for the current (or a given) fiscal
period — §13.1/13.2 revenue + expense close into Capital, and §13.3
appropriation reserve when the COA carries them — the same work the UI's
'close' and 'appropriations' step buttons perform. Idempotent: re-runs
skip months already posted.

    python manage.py close_month --company STMIET --period 2026-01

The 4-step gate still applies: the period only locks once all steps
(accruals -> recon -> close -> appropriations) are done, matching the UI.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Post the month-end closing JEs and lock the period when the steps allow it."

    def add_arguments(self, parser):
        parser.add_argument(
            "--company", default="STMIET",
            help="Company code (default: STMIET).",
        )
        parser.add_argument(
            "--period", default=None,
            help="Fiscal period to close, YYYY-MM (default: the current open period).",
        )

    def _resolve_period(self, company, raw):
        from datetime import date

        from apps.foundation.models import FiscalPeriod

        if raw:
            try:
                year, month = (int(part) for part in raw.split("-"))
            except (ValueError, TypeError):
                self.stderr.write(f"Invalid --period {raw!r}; expected YYYY-MM.")
                raise SystemExit(1)
            return FiscalPeriod.objects.filter(
                fiscal_year__company=company,
                start_date__year=year,
                start_date__month=month,
            ).first()
        today = date.today()
        return (
            FiscalPeriod.objects.filter(
                fiscal_year__company=company,
                start_date__lte=today,
                end_date__gte=today,
                is_closed=False,
            ).order_by("-period_no").first()
        )

    def handle(self, *args, **options):
        from apps.foundation.models import Company
        from apps.reporting.services import MonthEndCloseService

        company = Company.objects.filter(code=options["company"]).first()
        if company is None:
            self.stderr.write(f"No company with code '{options['company']}'.")
            raise SystemExit(1)

        period = self._resolve_period(company, options["period"])
        if period is None:
            self.stderr.write("No matching fiscal period — nothing to close.")
            raise SystemExit(1)

        mec = MonthEndCloseService.get_or_create(period)
        if mec.status == "closed":
            self.stdout.write(self.style.SUCCESS(
                f"{period.period_no} already closed (locked {mec.closed_at:%Y-%m-%d %H:%M})."
            ))
            return

        # Post the closing JEs exactly as the UI steps do.
        mec = MonthEndCloseService.close_period(mec, user=None)
        if mec.revenue_close_entry or mec.expense_close_entry:
            self.stdout.write(
                f"Posted closing JEs: "
                f"{mec.revenue_close_entry.entry_no if mec.revenue_close_entry else '-'}, "
                f"{mec.expense_close_entry.entry_no if mec.expense_close_entry else '-'}."
            )
        mec = MonthEndCloseService.apply_appropriations(mec, user=None)
        if mec.appropriation_entry:
            self.stdout.write(f"Posted appropriation JE: {mec.appropriation_entry.entry_no}.")

        # Mark the two posting steps done so the UI reflects reality.
        if mec.step_status("close") != "done":
            mec = MonthEndCloseService.advance(mec, "close")
        if mec.step_status("appropriations") != "done":
            mec = MonthEndCloseService.advance(mec, "appropriations")

        if mec.is_ready:
            mec = MonthEndCloseService.complete(mec, user=None)
            self.stdout.write(self.style.SUCCESS(
                f"Period {period.period_no} closed and locked."
            ))
        else:
            undone = [s for s in MonthEndCloseService.STEPS if mec.step_status(s) != "done"]
            self.stdout.write(
                f"Closing JEs posted; still pending: {', '.join(undone)}. "
                "Finish these in the UI before the period can lock."
            )