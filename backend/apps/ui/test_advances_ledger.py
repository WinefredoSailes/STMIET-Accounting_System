"""Derived "Advances to Employees" subsidiary ledger (COA 12070) — tests.

The register is derived from the posted GL projection (ADR-005): every row is
a posted line touching account 12070 within the window; the Net Amount is the
per-employee running balance, Dr positive, so reversal/liquidation pairs net
to zero. Status follows the net: Dr = Advances to Employees, Cr = Payable to
Employees, zero = Liquidated / Fully Paid.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.foundation.models import Account, Segment
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService
from apps.ui.services import ADVANCE_ACCOUNT_MATCH, advances_subsidiary_ledger

FORMATS = {
    "pdf": ("application/pdf", b"%PDF-"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"PK\x03\x04"),
    "csv": ("text/csv", None),
}


def _post(company, segment, date_, lines, entry_no, desc, *, supplier_name=""):
    """Post a balanced JE from (account_code, amount) with sign: Dr(+)/Cr(-)."""
    je = JournalEntry.objects.create(
        entry_no=entry_no,
        company=company,
        segment=segment,
        transaction_date=date_,
        status=PostingStatus.DRAFT,
        description=desc,
        source_doc_type="TEST",
        supplier_name=supplier_name,
    )
    line_no = 1
    for code, raw in lines:
        amount = Decimal(raw)
        JournalEntryLine.objects.create(
            entry=je,
            line_no=line_no,
            account=Account.objects.get(code=code),
            debit=amount if amount >= 0 else Decimal("0.00"),
            credit=-amount if amount < 0 else Decimal("0.00"),
        )
        line_no += 1
    je.recalc_totals()
    if je.total_debit > Decimal("100000.00"):
        je.status = PostingStatus.APPROVED
        je.save(update_fields=["status", "updated_at"])
    return PostingService.post(je, user=None)


@pytest.fixture
def advance_activity(company, segment, accounts):
    """Three employees: net Dr (advance), net zero (liquidated) and net Cr
    (payable back), plus one unidentified row."""
    _post(
        company, segment, date(2026, 1, 6),
        [("12070", "30000.00"), ("21010", "-30000.00")], "JE-1001", "Cash advance - Anna",
        supplier_name="Anna Cruz",
    )
    _post(
        company, segment, date(2026, 1, 8),
        [("12070", "20000.00"), ("21010", "-20000.00")], "JE-1002", "Cash advance - Ben",
        supplier_name="Ben Dy",
    )
    _post(
        company, segment, date(2026, 1, 10),
        [("12070", "5000.00"), ("21010", "-5000.00")], "JE-1003", "Cash advance",
    )
    _post(
        company, segment, date(2026, 2, 6),
        [("21010", "20000.00"), ("12070", "-20000.00")], "JE-1004", "Liquidation - Ben",
        supplier_name="Ben Dy",
    )
    _post(
        company, segment, date(2026, 2, 9),
        [("21010", "35000.00"), ("12070", "-35000.00")], "JE-1005", "Liquidation - Anna",
        supplier_name="Anna Cruz",
    )
    return segment


def _section(data, party):
    return next(s for s in data["sections"] if s["party"] == party)


class TestAccountMatch:
    def test_advance_account_tree_covered(self, accounts):
        Account.objects.create(
            code="12070-01", name="Advances to Employees - Baguio", account_type="asset"
        )
        codes = set(Account.objects.filter(ADVANCE_ACCOUNT_MATCH).values_list("code", flat=True))
        assert "12070" in codes
        assert "12070-01" in codes
        assert "10010" not in codes
        assert "20000" not in codes


class TestAdvancesSubsidiaryLedger:
    def test_january_window_runs_balances(self, company, advance_activity):
        data = advances_subsidiary_ledger(
            company=company, start=date(2026, 1, 1), end=date(2026, 1, 31)
        )
        assert len(data["rows"]) == 3

        anna = _section(data, "Anna Cruz")
        assert anna["opening"] == Decimal("0.00")
        assert anna["period_debit"] == Decimal("30000.00")
        assert anna["period_credit"] == Decimal("0.00")
        assert anna["closing"] == Decimal("30000.00")
        assert anna["closing_dr"] == Decimal("30000.00")
        assert anna["closing_cr"] is None
        assert anna["status"] == "advances"

        row = next(r for r in data["rows"] if r["ref"] == "JE-1001")
        assert row["party"] == "Anna Cruz"
        assert row["debit"] == Decimal("30000.00")
        assert row["net"] == Decimal("30000.00")
        assert row["net_dr"] == Decimal("30000.00")
        assert row["net_cr"] is None
        assert row["status"] == "advances"

        assert data["period_debit"] == Decimal("55000.00")
        assert data["period_credit"] == Decimal("0.00")
        assert data["total_net"] == Decimal("55000.00")
        assert data["status_counts"] == {"advances": 3, "payable": 0, "liquidated": 0}

    def test_liquidated_and_payable_and_opening_carryover(self, company, advance_activity):
        """February shows per-employee opening, a zeroed (liquidated) net and a
        reversed-sign (payable) net; the unidentified opening carries over."""
        data = advances_subsidiary_ledger(
            company=company, start=date(2026, 2, 1), end=date(2026, 2, 28)
        )

        ben = _section(data, "Ben Dy")
        assert ben["opening"] == Decimal("20000.00")
        assert ben["period_credit"] == Decimal("20000.00")
        assert ben["closing"] == Decimal("0.00")
        assert ben["closing_dr"] is None and ben["closing_cr"] is None
        assert ben["status"] == "liquidated"

        anna = _section(data, "Anna Cruz")
        assert anna["opening"] == Decimal("30000.00")
        assert anna["period_credit"] == Decimal("35000.00")
        assert anna["closing"] == Decimal("-5000.00")
        assert anna["closing_dr"] is None
        assert anna["closing_cr"] == Decimal("5000.00")
        assert anna["status"] == "payable"

        unseen = _section(data, "(Unidentified)")
        assert unseen["opening"] == Decimal("5000.00")
        assert unseen["row_count"] == 0
        assert unseen["closing"] == Decimal("5000.00")
        assert unseen["status"] == "advances"

        liquidated_row = next(r for r in data["rows"] if r["ref"] == "JE-1004")
        assert liquidated_row["net"] == Decimal("0.00")
        assert liquidated_row["net_dr"] is None and liquidated_row["net_cr"] is None
        assert liquidated_row["status"] == "liquidated"

        payable_row = next(r for r in data["rows"] if r["ref"] == "JE-1005")
        assert payable_row["net"] == Decimal("-5000.00")
        assert payable_row["net_dr"] is None
        assert payable_row["net_cr"] == Decimal("5000.00")
        assert payable_row["status"] == "payable"

        assert data["period_debit"] == Decimal("0.00")
        assert data["period_credit"] == Decimal("55000.00")
        assert data["total_net"] == Decimal("-55000.00")
        assert data["status_counts"] == {"advances": 1, "payable": 1, "liquidated": 1}

    def test_unidentified_rows_grouped(self, company, advance_activity):
        data = advances_subsidiary_ledger(
            company=company, start=date(2026, 1, 1), end=date(2026, 1, 31)
        )
        assert any(s["party"] == "(Unidentified)" for s in data["sections"])
        row = next(r for r in data["rows"] if r["ref"] == "JE-1003")
        assert row["party"] == "(Unidentified)"
        assert data["unidentified_count"] == 1

    def test_segment_filter_narrows(self, company, segment, accounts):
        dmie = Segment.objects.create(code="DMIE", name="DMIE", company=company)
        _post(
            company, segment, date(2026, 1, 6),
            [("12070", "10000.00"), ("21010", "-10000.00")], "JE-2001",
            "DHPP advance", supplier_name="DHPP Guy",
        )
        _post(
            company, dmie, date(2026, 1, 7),
            [("12070", "4000.00"), ("21010", "-4000.00")], "JE-2002",
            "DMIE advance", supplier_name="DMIE Guy",
        )
        data = advances_subsidiary_ledger(
            company=company, start=date(2026, 1, 1), end=date(2026, 1, 31), segment="DHPP"
        )
        parties = [s["party"] for s in data["sections"]]
        assert parties == ["DHPP Guy"]
        assert all(r["party"] == "DHPP Guy" for r in data["rows"])


class TestAdvancesLedgerViews:
    def test_screen_renders(self, client, user, advance_activity):
        client.force_login(user)
        resp = client.get("/ap/advances/ledger/?start=2026-01-01&end=2026-01-31")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "ADVANCES SUBSIDIARY LEDGER" in body
        for label in ("Excel", "PDF", "CSV"):
            assert f">{label}<" in body
        assert ">Print<" in body
        assert "Anna Cruz" in body
        assert "JE-1001" in body
        assert "30,000.00" in body
        assert "-5,000.00" not in body
        assert "{{" not in body and "{%" not in body

    def test_screen_never_shows_negatives_for_payable(self, client, user, advance_activity):
        client.force_login(user)
        resp = client.get("/ap/advances/ledger/?start=2026-02-01&end=2026-02-28")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "5,000.00" in body  # payable magnitude rendered via Cr chip
        assert "-5,000.00" not in body

    @pytest.mark.parametrize("fmt", ["xlsx", "csv", "pdf"])
    def test_export_formats(self, client, user, advance_activity, fmt):
        client.force_login(user)
        resp = client.get(f"/ap/advances/ledger/export/?format={fmt}&start=2026-01-01&end=2026-01-31")
        assert resp.status_code == 200
        ctype, magic = FORMATS[fmt]
        assert resp["Content-Type"].startswith(ctype)
        if magic:
            assert resp.content.startswith(magic)

    def test_export_csv_header_and_rows(self, client, user, advance_activity):
        client.force_login(user)
        resp = client.get("/ap/advances/ledger/export/?format=csv&start=2026-01-01&end=2026-01-31")
        text = resp.content.decode("utf-8", "replace")
        assert "Reference" in text.splitlines()[0]
        assert "Anna Cruz" in text
        assert "JE-1001" in text
        assert "30,000.00" not in text
        assert "30000.00" in text  # raw CSV values, never formatted display strings

    def test_print_renders(self, client, user, advance_activity):
        client.force_login(user)
        resp = client.get("/ap/advances/ledger/print/?start=2026-01-01&end=2026-01-31")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "ADVANCES SUBSIDIARY LEDGER" in body
        assert "stmiet-trans-logo.png" in body
        assert "Anna Cruz" in body

    def test_empty_state(self, client, user):
        client.force_login(user)
        resp = client.get("/ap/advances/ledger/")
        assert resp.status_code == 200

    def test_login_required(self, client, db):
        for url in ("/ap/advances/ledger/", "/ap/advances/ledger/export/", "/ap/advances/ledger/print/"):
            assert client.get(url).status_code == 302, url

    @pytest.mark.parametrize(
        "path",
        [
            "/ap/advances/ledger/?month=zzz",
            "/ap/advances/ledger/?start=notadate&end=9999-99-99",
            "/ap/advances/ledger/?segment=zzz&start=2026-1-1",
            "/ap/advances/ledger/export/?format=csv&start=notadate&segment=zzz",
            "/ap/advances/ledger/export/?format=pdf&end=9999-99-99",
            "/ap/advances/ledger/print/?month=2026-99",
        ],
    )
    def test_malformed_params_never_500(self, client, user, path):
        client.force_login(user)
        assert client.get(path).status_code == 200, path