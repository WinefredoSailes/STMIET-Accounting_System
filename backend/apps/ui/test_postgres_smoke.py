"""Postgres smoke tests: prove the JE write path survives a real Postgres
backend (the varchar-truncation 500 and the approval flow).

Opt-in via PG_SMOKE=1 so the default SQLite suite stays untouched. Run:

    $env:DJANGO_SETTINGS_MODULE="config.settings.pg_smoke"
    $env:DATABASE_URL="postgres://USER:PASS@HOST:5432/DBNAME"
    $env:PG_SMOKE="1"
    pytest apps/ui/test_postgres_smoke.py -o addopts="" --migrations --create-db

The -o addopts="" override drops pytest.ini's --nomigrations so migration
0003 is also exercised on Postgres, matching the deploy path.
"""

import os

import pytest
from django.db import connection
from django.test import Client

from apps.posting.models import JournalEntry, PostingStatus

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        os.environ.get("PG_SMOKE") != "1",
        reason="Postgres smoke test is opt-in: set PG_SMOKE=1",
    ),
]


@pytest.fixture
def _postgres_only():
    if connection.vendor != "postgresql":
        pytest.skip("requires a Postgres backend (config.settings.pg_smoke)")


def test_long_je_fields_survive_postgres_insert(
    _postgres_only, client, company, segment, accounts, fiscal_period
):
    """Regression for the production 500:
    psycopg.errors.StringDataRightTruncation -- value too long for type
    character varying(32)."""
    long_no = "X" * 80
    long_desc = "Y" * 600
    resp = client.post(
        "/journal/new/",
        {
            "transaction_date": "2026-01-15",
            "source_doc_type": "X" * 40,
            "source_doc_no": long_no,
            "description": long_desc,
            "account": [accounts["10010"].id, accounts["20000"].id],
            "line_segment": [segment.id, segment.id],
            "debit": ["1000.00", ""],
            "credit": ["", "1000.00"],
            "line_description": [long_desc, "AP"],
        },
    )
    assert resp.status_code == 302, resp.content[:500]
    je = JournalEntry.objects.first()
    assert len(je.source_doc_type) == 16
    assert len(je.source_doc_no) == 32
    assert len(je.description) == 500
    assert all(len(line.description) <= 500 for line in je.lines.all())


def test_je_approval_flow_on_postgres(
    _postgres_only, company, segment, accounts, fiscal_period, role_users
):
    """Full submit -> approve -> post cycle against a real Postgres."""
    staff_client = Client()
    staff_client.force_login(role_users["staff"])
    head_client = Client()
    head_client.force_login(role_users["head"])

    resp = staff_client.post(
        "/journal/new/",
        {
            "transaction_date": "2026-01-15",
            "source_doc_type": "JE",
            "account": [accounts["10010"].id, accounts["20000"].id],
            "line_segment": [segment.id, segment.id],
            "debit": ["1000.00", ""],
            "credit": ["", "1000.00"],
            "line_description": ["Cash in", "AP"],
        },
    )
    assert resp.status_code == 302, resp.content[:500]
    je = JournalEntry.objects.first()
    assert je.status == PostingStatus.DRAFT

    assert staff_client.post(f"/journal/{je.id}/submit/").status_code == 302
    je.refresh_from_db()
    assert je.status == PostingStatus.SUBMITTED

    assert head_client.post(f"/journal/{je.id}/approve/").status_code == 302
    je.refresh_from_db()
    assert je.status == PostingStatus.APPROVED
    assert je.approved_by == role_users["head"]

    assert staff_client.post(f"/journal/{je.id}/post/").status_code == 302
    je.refresh_from_db()
    assert je.is_posted