"""Document numbering (ADR-032): atomic, per company/year/form, zero-padded."""

import pytest

from apps.sequences.models import DocumentSequence


@pytest.fixture
def seq_company(db):
    from apps.foundation.models import Company

    return Company.objects.create(code="STMIET", name="Seven-Trent")


def test_sequential_numbering(seq_company):
    a = DocumentSequence.next_number(company=seq_company, form_code="RFP", year=2026)
    b = DocumentSequence.next_number(company=seq_company, form_code="RFP", year=2026)
    assert a == "2026-00001"
    assert b == "2026-00002"


def test_independent_per_form_and_year(seq_company):
    DocumentSequence.next_number(company=seq_company, form_code="RFP", year=2026)
    c = DocumentSequence.next_number(company=seq_company, form_code="CV", year=2026)
    assert c == "2026-00001"
    d = DocumentSequence.next_number(company=seq_company, form_code="RFP", year=2027)
    assert d == "2027-00001"


def test_custom_pattern_and_company_isolation(seq_company):
    from apps.foundation.models import Company

    stpc = Company.objects.create(code="STPC", name="STPC Trading")
    a = DocumentSequence.next_number(
        company=stpc, form_code="AR", year=2026, pattern="AR-{YYYY}-{SEQ:03d}"
    )
    assert a == "AR-2026-001"


def test_pattern_is_only_applied_when_the_row_is_created(seq_company):
    """`next_number` passes the pattern as `get_or_create(defaults=...)`, so
    it seeds a NEW row but never rewrites an existing one. This is why the PO
    prefix needs a data migration rather than a call-site change alone."""
    DocumentSequence.objects.create(
        company=seq_company, form_code="PO", year=2026, pattern="{YYYY}-{SEQ:05d}"
    )
    n = DocumentSequence.next_number(
        company=seq_company, form_code="PO", year=2026, pattern="PO-{YYYY}-{SEQ:05d}"
    )
    assert n == "2026-00001"  # stored pattern wins, call-site value ignored


def test_po_prefix_migration_repoints_stored_patterns(seq_company):
    """The migration must repair PO rows left on the old unprefixed pattern,
    otherwise the first PO issued after the upgrade loses its prefix."""
    from django.apps import apps as global_apps

    import importlib

    migration = importlib.import_module("apps.sequences.migrations.0002_po_number_prefix")

    po_old = DocumentSequence.objects.create(
        company=seq_company, form_code="PO", year=2026,
        pattern="{YYYY}-{SEQ:05d}", next_seq=7,
    )
    untouched = DocumentSequence.objects.create(
        company=seq_company, form_code="AR", year=2026,
        pattern="AR-{YYYY}-{SEQ:05d}", next_seq=3,
    )

    migration.forward(global_apps, None)

    po_old.refresh_from_db()
    untouched.refresh_from_db()
    assert po_old.pattern == "PO-{YYYY}-{SEQ:05d}"
    assert po_old.next_seq == 7  # the counter is not disturbed
    assert untouched.pattern == "AR-{YYYY}-{SEQ:05d}"  # other forms untouched

    # and the repaired row now allocates prefixed numbers
    assert (
        DocumentSequence.next_number(company=seq_company, form_code="PO", year=2026)
        == "PO-2026-00007"
    )


def test_po_prefix_migration_is_reversible(seq_company):
    from django.apps import apps as global_apps
    import importlib

    migration = importlib.import_module("apps.sequences.migrations.0002_po_number_prefix")

    seq = DocumentSequence.objects.create(
        company=seq_company, form_code="PO", year=2026, pattern="{YYYY}-{SEQ:05d}"
    )
    migration.forward(global_apps, None)
    seq.refresh_from_db()
    assert seq.pattern == "PO-{YYYY}-{SEQ:05d}"

    migration.backward(global_apps, None)
    seq.refresh_from_db()
    assert seq.pattern == "{YYYY}-{SEQ:05d}"
