"""Tests for the job scheduler (ADR-045)."""

import pytest
from apscheduler.triggers.cron import CronTrigger

from apps.core import scheduler


def test_registered_default_jobs():
    oids = {job.oid for job in scheduler.jobs()}
    assert "depreciation_monthly" in oids
    job = next(j for j in scheduler.jobs() if j.oid == "depreciation_monthly")
    # First of the month, 02:00.
    assert job.crontab == "0 2 1 * *"
    assert CronTrigger.from_crontab(job.crontab)  # valid cron


def test_register_validates_cron():
    def handler():
        return {"ok": True}

    scheduler.register_job("test_cron_validation", crontab="0 2 1 * *")(handler)
    with pytest.raises(ValueError):
        scheduler.register_job("test_bad_cron", crontab="not-a-cron")(handler)


def test_run_job_result_and_orphan(db):
    calls = []

    @scheduler.register_job("test_run_job", crontab="0 3 1 * *", label="run once")
    def handler():
        calls.append(1)
        return {"posted": ["FA-0001"]}

    result = scheduler.run_job("test_run_job")
    assert result["oid"] == "test_run_job"
    assert result["status"] == "ok"
    assert result["posted"] == ["FA-0001"]
    assert "started_at" in result and "finished_at" in result
    assert calls == [1]


def test_run_unknown_job():
    with pytest.raises(KeyError):
        scheduler.run_job("no_such_job")


def test_previous_month_start():
    import datetime as dt

    today = dt.date.today()
    assert scheduler._previous_month_start() == today.replace(day=1) - dt.timedelta(days=1)