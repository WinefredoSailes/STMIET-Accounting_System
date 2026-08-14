"""Fiscal calendar helpers (ADR-013: Tuesday-to-Monday accounting cycles)."""

from datetime import date, timedelta

from django.conf import settings

CYCLE_START_WEEKDAY = settings.DOMAIN["CYCLE_START_DAY"]  # 1 = Tuesday
CYCLE_END_WEEKDAY = settings.DOMAIN["CYCLE_END_DAY"]  # 0 = Monday


def cycle_range_for(d: date) -> tuple[date, date]:
    """Return (start, end) of the Tue->Mon cycle containing *d*."""
    # Python weekday(): Mon=0 ... Sun=6.
    days_since_start = (d.weekday() - CYCLE_START_WEEKDAY) % 7
    start = d - timedelta(days=days_since_start)
    end = start + timedelta(days=6)
    return start, end


def month_bounds(d: date) -> tuple[date, date]:
    """First and last day of the month containing *d*."""
    first = d.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1)
    else:
        nxt = first.replace(month=first.month + 1)
    return first, nxt - timedelta(days=1)