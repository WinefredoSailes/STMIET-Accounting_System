"""Calendar invariants (ADR-013): accounting cycles run Tue -> Mon."""

from datetime import date

from apps.foundation.calendar import cycle_range_for, month_bounds


def test_cycle_start_tuesday():
    # 2026-01-15 is a Thursday -> cycle Tue 2026-01-13 .. Mon 2026-01-19.
    start, end = cycle_range_for(date(2026, 1, 15))
    assert start == date(2026, 1, 13)
    assert end == date(2026, 1, 19)


def test_monday_belongs_to_previous_cycle():
    # Monday 2026-01-19 is the LAST day of the cycle, not the start.
    start, end = cycle_range_for(date(2026, 1, 19))
    assert start == date(2026, 1, 13)
    assert end == date(2026, 1, 19)


def test_tuesday_starts_new_cycle():
    start, end = cycle_range_for(date(2026, 1, 20))
    assert start == date(2026, 1, 20)
    assert end == date(2026, 1, 26)


def test_month_bounds():
    first, last = month_bounds(date(2026, 2, 14))
    assert first == date(2026, 2, 1)
    assert last == date(2026, 2, 28)