"""Calendar invariants (ADR-013): accounting cycles run Tue -> Mon.

Also: `import_opening_balances` (BUILD-PLAN Phase 10) posts balanced
per-segment opening JEs, idempotently, with an auto-plug to the segment's
opening-equity account when Dr and Cr do not tie out.
"""

import csv
from datetime import date

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from io import StringIO

from apps.foundation.calendar import cycle_range_for, month_bounds
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus


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


def _write_csv(tmp_path, header, rows):
    path = tmp_path / "opening.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path


@pytest.fixture
def ob_accounts(db, segment, company):
    """COA slice used by the opening-balance importer tests."""
    from apps.foundation.models import Account, Segment

    dmi = Segment.objects.create(code="DMIE", name="DMIE", company=company)
    rows = [
        ("40000", "Sales - Fuel Hauling", "revenue", "DHPP"),
        ("50000", "COGS - Fuel Purchase_DHPP", "expense", "DHPP"),
        ("41003", "Sales - DMIE", "revenue", "DMIE"),
        ("51003", "COGS - Calibration Bucket-DMIE", "expense", "DMIE"),
        ("30000", "E.Bagatua Capital", "equity", "ALL"),
    ]
    out = {}
    for code, name, atype, seg in rows:
        out[code] = Account.objects.create(
            code=code, name=name, account_type=atype, segment=seg,
        )
    return out


class TestImportOpeningBalances:
    def test_balanced_posts_one_je_per_segment(
        self, tmp_path, fiscal_period, ob_accounts, segment
    ):
        csv_path = _write_csv(
            tmp_path,
            ["COA", "SEGMENT", "OPENING DR", "OPENING CR"],
            [
                ["40000", "DHPP", "", "1000.00"],
                ["50000", "DHPP", "1000.00", ""],
                ["41003", "DMIE", "", "500.00"],
                ["51003", "DMIE", "500.00", ""],
            ],
        )
        out = StringIO()
        call_command(
            "import_opening_balances", file=str(csv_path),
            as_of="2026-01-01", entry_prefix="OB-TEST",
            company="STMIET", stdout=out,
        )
        boost = out.getvalue()

        dhpp = JournalEntry.objects.get(entry_no="OB-TEST-DHPP")
        dmi = JournalEntry.objects.get(entry_no="OB-TEST-DMIE")
        assert dhpp.status == PostingStatus.POSTED
        assert dhpp.segment.code == "DHPP"
        assert float(dhpp.total_debit) == 1000.00
        assert float(dhpp.total_credit) == 1000.00
        assert dmi.segment.code == "DMIE"
        assert float(dmi.total_debit) == float(dmi.total_credit) == 500.00

    def test_idempotent_on_rerun(
        self, tmp_path, fiscal_period, ob_accounts, segment
    ):
        csv_path = _write_csv(
            tmp_path,
            ["COA", "SEGMENT", "OPENING DR", "OPENING CR"],
            [
                ["40000", "DHPP", "", "1000.00"],
                ["50000", "DHPP", "1000.00", ""],
            ],
        )
        call_command(
            "import_opening_balances", file=str(csv_path),
            as_of="2026-01-01", entry_prefix="OB-TEST", stdout=StringIO(),
        )
        out = StringIO()
        call_command(
            "import_opening_balances", file=str(csv_path),
            as_of="2026-01-01", entry_prefix="OB-TEST", stdout=out,
        )
        assert JournalEntry.objects.filter(
            entry_no__startswith="OB-TEST"
        ).count() == 1
        assert "already exists" in out.getvalue()

    def test_auto_plug_balances_imbalance(
        self, tmp_path, fiscal_period, ob_accounts, segment
    ):
        from apps.foundation.models import SegmentAccountMap

        SegmentAccountMap.objects.create(
            segment=segment, role=SegmentAccountMap.ROLE_OPENING_EQUITY,
            account=ob_accounts["30000"],
        )
        csv_path = _write_csv(
            tmp_path,
            ["COA", "SEGMENT", "OPENING DR", "OPENING CR"],
            [
                ["40000", "DHPP", "", "1000.00"],
                ["50000", "DHPP", "800.00", ""],
            ],
        )
        call_command(
            "import_opening_balances", file=str(csv_path),
            as_of="2026-01-01", entry_prefix="OB-PLUG", stdout=StringIO(),
        )
        entry = JournalEntry.objects.get(entry_no="OB-PLUG-DHPP")
        assert float(entry.total_debit) == float(entry.total_credit) == 1000.00
        lines = list(entry.lines.all())
        assert entry.lines.filter(account=ob_accounts["30000"]).exists()

    def test_no_plug_fails_on_imbalance(
        self, tmp_path, fiscal_period, ob_accounts, segment
    ):
        csv_path = _write_csv(
            tmp_path,
            ["COA", "SEGMENT", "OPENING DR", "OPENING CR"],
            [
                ["40000", "DHPP", "", "1000.00"],
                ["50000", "DHPP", "800.00", ""],
            ],
        )
        with pytest.raises(CommandError):
            call_command(
                "import_opening_balances", file=str(csv_path),
                as_of="2026-01-01", entry_prefix="OB-NOPLUG",
                no_plug=True, stdout=StringIO(),
            )
        assert not JournalEntry.objects.filter(entry_no="OB-NOPLUG-DHPP").exists()