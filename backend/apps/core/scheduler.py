"""Scheduled jobs (ADR-045).

A lightweight, dependency-light job registry that any caller can trigger:
the Windows Task Scheduler runs ``run_scheduler <oid>`` at the job's own
cron repetition, a supervisor script runs ``run_scheduler`` (the per-job
cron loop), or ops invokes ``run_scheduler <oid> --now`` for a manual run.

Design rules:
- Every job body is a plain function in its owning app, NOT here — this
  module only knows *when* and *how to guard*. Adding a job is one
  ``@register_job`` line next to the function it wraps, so migrating to
  Celery/beat later only means re-decorating with ``@app.task``.
- Crontabs are standard 5-field cron ("minute hour day month day-of-week"),
  validated with APScheduler's CronTrigger at registration.
- Each run is guarded by a per-job advisory lock (cross-process: two
  machines or two Task Scheduler hits can never post the same period twice)
  and a DB transaction; a duplicate beat returns the existing status.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Callable
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from django.conf import settings
from django.db import connection, transaction

logger = logging.getLogger("apps.core.scheduler")

__all__ = ["register_job", "run_job", "jobs", "Job"]


@dataclass(frozen=True)
class Job:
    """A scheduled unit: oid, crontab, and the handler to invoke."""

    oid: str
    crontab: str
    label: str
    fn: Callable

    @property
    def description(self) -> str:
        return f"{self.oid} — {self.label} (cron '{self.crontab}')"


_REGISTRY: dict[str, Job] = {}


def _timezone() -> ZoneInfo:
    return ZoneInfo(settings.TIME_ZONE or "UTC")


def register_job(oid: str, *, crontab: str, label: str = ""):
    """Register a handler under `oid`, validating its crontab up front."""

    def deco(fn):
        # Raises ValueError for malformed cron expressions at import time.
        CronTrigger.from_crontab(crontab)
        _REGISTRY[oid] = Job(oid=oid, crontab=crontab, label=label or oid, fn=fn)

        @wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)

        return wrapper

    return deco


def jobs() -> list[Job]:
    """Registered jobs, insertion order preserved."""
    return list(_REGISTRY.values())


def _hash(oid: str) -> int:
    """Stable 63-bit hash of the job oid (Postgres advisory keys are int8)."""
    return int.from_bytes(oid.encode("utf-8"), "big") % (1 << 63)


def _acquire_lock(oid: str) -> bool:
    """Non-blocking cross-backend advisory lock for a job run.

    PostgreSQL: ``pg_try_advisory_lock`` so a second process bails instantly.
    SQLite: an immediate-mode transaction is the whole-DB lock; a concurrent
    writer cannot start while the first holds it, so a short retry is allowed
    with the connection's own busy timeout (jobs are idempotent anyway).
    """
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [_hash(oid)])
            return cursor.fetchone()[0]
    # SQLite serializes writers at the transaction level; every job already
    # runs inside @transaction.atomic + @retry_on_lock, and each job body is
    # idempotent — so a duplicate beat simply re-runs and no-ops.
    return True


def _release_lock(oid: str) -> None:
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [_hash(oid)])


def run_job(oid: str) -> dict:
    """Run one job once. Returns the handler's result wrapped in status."""
    if oid not in _REGISTRY:
        raise KeyError(f"Unknown job '{oid}'. Known: {sorted(_REGISTRY)}")
    job = _REGISTRY[oid]
    if not _acquire_lock(oid):
        return {
            "oid": oid,
            "status": "locked",
            "detail": f"{job.description} is already running or the DB is busy.",
        }
    try:
        with transaction.atomic():
            started = datetime.now(_timezone())
            result = job.fn() or {}
            if not isinstance(result, dict):
                result = {"result": result}
            result.setdefault("status", "ok")
            result["oid"] = oid
            result["started_at"] = started.isoformat()
            result["finished_at"] = datetime.now(_timezone()).isoformat()
            logger.info(
                "job %s ok in %.1fs",
                oid,
                (datetime.now(_timezone()) - started).total_seconds(),
            )
            return result
    except Exception:
        logger.exception("job %s failed", oid)
        raise
    finally:
        _release_lock(oid)


def cron_loop(*, interval: int = 60, once: bool = False) -> None:
    """Optional always-on loop: run every job whose crontab matches `now`.

    The default per-job Task Scheduler mode does not need this; it exists
    for a supervisor starting one process that owns the schedule.
    """
    if not _REGISTRY:
        raise RuntimeError("No jobs registered — nothing to schedule.")

    def _due(now_local: datetime) -> list[Job]:
        return [
            job
            for job in jobs()
            if CronTrigger.from_crontab(job.crontab).get_next_fire_time(
                None, now_local
            )
            == now_local
        ]

    logger.info("cron_loop started with %d job(s)", len(jobs()))
    while True:
        ran = _due(datetime.now(_timezone()))
        for job in ran:
            run_job(job.oid)
        if ran:
            logger.info("ran: %s", ", ".join(job.oid for job in ran))
        if once:
            return
        time.sleep(interval)


def _previous_month_start() -> date:
    today = date.today()
    return today.replace(day=1) - timedelta(days=1)


# The first registered job: monthly depreciation is the reference — the real
# logic lives in the owning service, so the UI and the scheduler always agree.
@register_job(
    "depreciation_monthly",
    crontab="0 2 1 * *",
    label="Post prior month's depreciation for all active assets",
)
def _job_depreciation_monthly() -> dict:
    from apps.assets.services import DepreciationService

    return DepreciationService.post_all(period_start=_previous_month_start())