"""Fiscal calendar helpers (ADR-013: Tuesday-to-Monday accounting cycles).

Weekly cycles default to the global DOMAIN settings (CYCLE_START_DAY=Tuesday,
CYCLE_END_DAY=Monday). A Company may override the cycle type (weekly/monthly)
and the weekdays via its own `cash_cycle` / `cycle_start_weekday` /
`cycle_end_weekday` fields; callers that have a company in scope should pass it.
"""

from datetime import date, timedelta

from django.conf import settings

CYCLE_START_WEEKDAY = settings.DOMAIN["CYCLE_START_DAY"]  # 1 = Tuesday
CYCLE_END_WEEKDAY = settings.DOMAIN["CYCLE_END_DAY"]  # 0 = Monday

WEEKLY = "weekly"
MONTHLY = "monthly"


def _weekday(company, field: str, setting_name: str) -> int:
    if company is not None:
        value = getattr(company, field, None)
        if value is not None:
            return value
    return settings.DOMAIN[setting_name]


def cycle_range_for(d: date, *, company=None) -> tuple[date, date]:
    """Return (start, end) of the cycle containing *d*.

    The company's cash-cycle type drives the bucket: monthly companies get a
    calendar-month window, weekly companies a start->end weekday window. With
    no company, the global settings default (Tue->Mon weekly) is used.
    """
    if company is not None and getattr(company, "cash_cycle", WEEKLY) == MONTHLY:
        return month_bounds(d)
    # Python weekday(): Mon=0 ... Sun=6.
    start_wd = _weekday(company, "cycle_start_weekday", "CYCLE_START_DAY")
    end_wd = _weekday(company, "cycle_end_weekday", "CYCLE_END_DAY")
    days_since_start = (d.weekday() - start_wd) % 7
    start = d - timedelta(days=days_since_start)
    end = start + timedelta(days=(end_wd - start_wd) % 7)
    return start, end


def month_bounds(d: date) -> tuple[date, date]:
    """First and last day of the month containing *d*."""
    first = d.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1)
    else:
        nxt = first.replace(month=first.month + 1)
    return first, nxt - timedelta(days=1)