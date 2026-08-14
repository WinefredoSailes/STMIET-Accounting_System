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