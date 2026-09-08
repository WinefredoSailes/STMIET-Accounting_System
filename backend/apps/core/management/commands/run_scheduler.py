"""Run registered scheduled jobs (ADR-045).

Per-job Windows Task Scheduler setup (the recommended mode): create one
scheduled task per job, each with its own repetition trigger, calling::

    \\path\\to\\.venv\\Scripts\\python.exe manage.py run_scheduler <oid>

List the registry with ``--list``, run a job once immediately with
``--run <oid>``, or keep a single always-on loop with ``--loop`` (a
supervisor starts it once; jobs fire on their own crontabs).
"""

from django.core.management.base import BaseCommand

from apps.core import scheduler


class Command(BaseCommand):
    help = "Run scheduled background jobs (depreciation, ...)."

    def add_arguments(self, parser):
        parser.add_argument("--list", action="store_true", help="List registered jobs and exit.")
        parser.add_argument("--run", metavar="OID", help="Run one job by oid and print its result.")
        parser.add_argument("--loop", action="store_true", help="Run the always-on cron loop (all jobs).")
        parser.add_argument(
            "--interval", type=int, default=60, help="Loop poll interval in seconds (default 60)."
        )

    def handle(self, *args, **options):
        if options["list"]:
            for job in scheduler.jobs():
                self.stdout.write(job.description, style_func=self.style.SUCCESS)
            return

        if options["run"]:
            oid = options["run"]
            try:
                result = scheduler.run_job(oid)
            except KeyError as exc:
                self.stderr.write(str(exc))
                raise SystemExit(2) from exc
            self.stdout.write(str(result))
            return

        if options["loop"]:
            scheduler.cron_loop(interval=options["interval"])
            return

        self.stderr.write(
            "Nothing to do. Use --list, --run OID, or --loop. "
            "e.g. manage.py run_scheduler --run depreciation_monthly"
        )
        raise SystemExit(1)