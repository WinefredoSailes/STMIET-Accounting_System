"""General Ledger service tests (BUILD-PLAN ledger deliverable).

- ledger_window : month / date-range / latest-posted-period resolution.
- ledger_index  : COA-grouped index, opening / period Dr-Cr / closing in
                  classic presentation order; segment narrowing.
- ledger_account: classic running-balance register (opening carried forward,
                  period totals, reversals reflected), ADR-005 signed.

All balances are derived from the posted GL projection at query time — the
tests assert the projection math, not stored figures.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client

from apps.foundation.models import Account, Company, FiscalPeriod, FiscalYear, Segment
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService
from apps.ui.services import ledger_account, ledger_index, ledger_window


@pytest.fixture
def company(db):
    return Company.objects.create(code="STMIET", name="STMIET Testing")


@pytest.fixture
def segments(db, company):
    return {
        "DHPP": Segment.objects.create(code="DHPP", name="DHPP", company=company),
        "DMIE": Segment.objects.create(code="DMIE", name="DMIE", company=company),
    }


@pytest.fixture
def coa(db):
    rows = [
        ("10010", "Cash on Hand", "asset", "DHPP", "debit", ""),
        ("10013", "Cash on Hand-DMIE", "asset", "DMIE", "debit", "Cash and Cash Equivalents"),
        ("12030", "A/Receivables - Fuel Clients", "asset", "DHPP", "debit", "Receivables"),
        ("20000", "A/Payables - Current", "liability", "DHPP", "credit", ""),
        ("30000", "Capital", "equity", "DHPP", "credit", "Capital and Reserves"),
        ("40000", "Sales - Fuel Hauling", "revenue", "DHPP", "credit", "Sales"),
        ("41003", "Sales - DMIE", "revenue", "DMIE", "credit", "Sales"),
        ("61000", "Operating Expenses", "expense", "DHPP", "debit", "Operating Expenses"),
    ]
    out = {}
    for code, name, atype, seg, nb, classification in rows:
        out[code] = Account.objects.create(
            code=code, name=name, account_type=atype, segment=seg,
            normal_balance=nb, classification=classification,
        )
    return out


@pytest.fixture
def fy(db, company):
    return FiscalYear.objects.create(
        company=company, code="2026", start_date="2026-01-01", end_date="2026-12-31"
    )


@pytest.fixture
def periods(db, fy):
    p1 = FiscalPeriod.objects.create(
        fiscal_year=fy, period_no=1, start_date="2026-01-01", end_date="2026-01-31"
    )
    p2 = FiscalPeriod.objects.create(
        fiscal_year=fy, period_no=2, start_date="2026-02-01", end_date="2026-02-28"
    )
    return {"jan": p1, "feb": p2}


def _post(company, segment, date_, lines, entry_no, desc, *, cost_centers=None, user=None):
    """Post a balanced JE from (account_code, amount) with sign: Dr(+)/Cr(-)."""
    je = JournalEntry.objects.create(
        entry_no=entry_no,
        company=company,
        segment=segment,
        transaction_date=date_,
        status=PostingStatus.DRAFT,
        description=desc,
        source_doc_type="TEST",
        created_by=user,
    )
    line_no = 1
    for i, (code, raw) in enumerate(lines):
        amount = Decimal(raw)
        JournalEntryLine.objects.create(
            entry=je,
            line_no=line_no,
            account=Account.objects.get(code=code),
            debit=amount if amount >= 0 else Decimal("0.00"),
            credit=-amount if amount < 0 else Decimal("0.00"),
            cost_center=(cost_centers or {}).get(code, ""),
        )
        line_no += 1
    je.recalc_totals()
    if je.total_debit > Decimal("100000.00"):
        je.status = PostingStatus.APPROVED
        je.save(update_fields=["status", "updated_at"])
    return PostingService.post(je, user=user)


@pytest.fixture
def january_activity(company, segments, coa, periods):
    """Opening capital + sales + expense in January (all under 100k)."""
    _post(
        company, segments["DHPP"], date(2026, 1, 2),
        [("10010", "400000.00"), ("30000", "-400000.00")], "JE-0001", "Opening capital",
    )
    _post(
        company, segments["DHPP"], date(2026, 1, 5),
        [("12030", "250000.00"), ("40000", "-250000.00")], "JE-0002", "Fuel sales",
    )
    _post(
        company, segments["DHPP"], date(2026, 1, 6),
        [("61000", "8000.00"), ("10010", "-8000.00")], "JE-0003", "Opex",
    )
    return periods["jan"]


class TestLedgerWindow:
    def test_defaults_to_latest_posted_period(self, january_activity, periods):
        win = ledger_window({})
        assert win["mode"] == "month"
        assert win["start"] == date(2026, 1, 1)
        assert win["end"] == date(2026, 1, 31)

    def test_month_param_overrides_default(self, january_activity, periods):
        win = ledger_window({"month": "2026-01"})
        assert win["mode"] == "month"
        assert win["start"] == date(2026, 1, 1)
        assert win["end"] == date(2026, 1, 31)
        assert win["month"] == "2026-01"

    def test_date_range_takes_over_when_no_month(self, january_activity, periods):
        win = ledger_window({"start": "2026-01-10", "end": "2026-02-15"})
        assert win["mode"] == "range"
        assert win["start"] == date(2026, 1, 10)
        assert win["end"] == date(2026, 2, 15)

    def test_segment_carried_through(self, january_activity, segments):
        win = ledger_window({"segment": "DHPP"})
        assert win["segment"] == "DHPP"


class TestLedgerIndex:
    def test_groups_presented_in_classic_order(self, january_activity, company):
        idx = ledger_index(company=company, start=date(2026, 1, 1), end=date(2026, 1, 31))
        types = [g["account_type"] for g in idx["groups"]]
        assert types == ["asset", "equity", "revenue", "expense"]

    def test_opening_period_and_closing_math(self, january_activity, company):
        idx = ledger_index(company=company, start=date(2026, 1, 1), end=date(2026, 1, 31))
        rows = {r["code"]: r for g in idx["groups"] for s in g["sections"] for r in s["rows"]}

        assert rows["10010"]["opening"] == Decimal("0.00")
        assert rows["10010"]["debit"] == Decimal("400000.00")
        assert rows["10010"]["credit"] == Decimal("8000.00")
        assert rows["10010"]["closing"] == Decimal("392000.00")

        assert rows["40000"]["closing"] == Decimal("250000.00")
        assert rows["30000"]["closing"] == Decimal("400000.00")
        assert rows["61000"]["closing"] == Decimal("8000.00")

        assert idx["total_debit"] == Decimal("658000.00")
        assert idx["total_credit"] == Decimal("658000.00")

    def test_opening_carries_into_february(self, january_activity, company):
        idx = ledger_index(company=company, start=date(2026, 2, 1), end=date(2026, 2, 28))
        rows = {r["code"]: r for g in idx["groups"] for s in g["sections"] for r in s["rows"]}

        assert rows["10010"]["opening"] == Decimal("392000.00")
        assert rows["10010"]["debit"] == Decimal("0.00")
        assert rows["10010"]["closing"] == Decimal("392000.00")
        assert rows["40000"]["opening"] == Decimal("250000.00")

    def test_sections_split_by_classification(self, january_activity, company):
        idx = ledger_index(company=company, start=date(2026, 1, 1), end=date(2026, 1, 31))
        asset_group = idx["groups"][0]
        classnames = [s["classification"] for s in asset_group["sections"]]
        assert classnames == ["", "Receivables"] or classnames == ["Receivables", ""]

    def test_segment_filter_narrows_index(self, company, segments, coa, periods):
        _post(
            company, segments["DMIE"], date(2026, 1, 3),
            [("10013", "50000.00"), ("41003", "-50000.00")], "JE-0100", "DMIE inflow",
        )
        all_idx = ledger_index(company=company, start=date(2026, 1, 1), end=date(2026, 1, 31))
        all_codes = {r["code"] for g in all_idx["groups"] for s in g["sections"] for r in s["rows"]}
        assert "10013" in all_codes and "41003" in all_codes

        dmie_idx = ledger_index(
            company=company, start=date(2026, 1, 1), end=date(2026, 1, 31), segment="DMIE"
        )
        # GL rows carry the posting segment; only DMIE-posted accounts survive.
        dmie_codes = {r["code"] for g in dmie_idx["groups"] for s in g["sections"] for r in s["rows"]}
        assert dmie_codes == {"10013", "41003"}


class TestLedgerAccount:
    def test_running_balance_multiple_rows(self, january_activity, company, coa):
        cash = coa["10010"]
        reg = ledger_account(account=cash, company=company, start=date(2026, 1, 1), end=date(2026, 1, 31))

        assert reg["opening"] == Decimal("0.00")
        assert [r["balance"] for r in reg["rows"]] == [
            Decimal("400000.00"),
            Decimal("392000.00"),
        ]
        assert reg["period_debit"] == Decimal("400000.00")
        assert reg["period_credit"] == Decimal("8000.00")
        assert reg["closing"] == Decimal("392000.00")
        assert reg["normal_balance"] == "debit"

    def test_opening_brought_forward_into_next_period(self, january_activity, company, coa):
        ar = coa["12030"]
        _post(
            company, company.segments.first(), date(2026, 2, 10),
            [("10010", "100000.00"), ("12030", "-100000.00")], "JE-0004", "Collection",
        )
        reg = ledger_account(account=ar, company=company, start=date(2026, 2, 1), end=date(2026, 2, 28))

        assert reg["opening"] == Decimal("250000.00")
        assert len(reg["rows"]) == 1
        assert reg["rows"][0]["credit"] == Decimal("100000.00")
        assert reg["rows"][0]["balance"] == Decimal("150000.00")
        assert reg["closing"] == Decimal("150000.00")

    def test_credit_normal_balance_positive_direction(self, january_activity, company, coa):
        capital = coa["30000"]
        reg = ledger_account(account=capital, company=company, start=date(2026, 1, 1), end=date(2026, 1, 31))

        assert reg["normal_balance"] == "credit"
        assert reg["opening"] == Decimal("0.00")
        assert reg["rows"][0]["credit"] == Decimal("400000.00")
        assert reg["rows"][0]["balance"] == Decimal("400000.00")
        assert reg["closing"] == Decimal("400000.00")

    def test_reversal_reflected_in_running_balance(self, company, segments, coa, periods):
        _post(
            company, segments["DHPP"], date(2026, 1, 2),
            [("10010", "100.00"), ("40000", "-100.00")], "JE-0001", "Sale",
        )
        _post(
            company, segments["DHPP"], date(2026, 2, 3),
            [("40000", "100.00"), ("10010", "-100.00")], "JE-0002", "Reversal",
        )
        sales = coa["40000"]
        reg = ledger_account(account=sales, company=company, start=date(2026, 2, 1), end=date(2026, 2, 28))

        assert reg["opening"] == Decimal("100.00")
        assert len(reg["rows"]) == 1
        assert reg["rows"][0]["debit"] == Decimal("100.00")
        assert reg["closing"] == Decimal("0.00")

    def test_cost_center_and_party_surface_on_rows(self, january_activity, company, coa):
        opex = coa["61000"]
        reg = ledger_account(account=opex, company=company, start=date(2026, 1, 1), end=date(2026, 1, 31))
        assert reg["rows"][0]["cost_center"] == ""
        assert reg["rows"][0]["entry_no"] == "JE-0003"


class TestLedgerViews:
    def test_index_renders(self, january_activity, user):
        c = Client()
        c.force_login(user)
        resp = c.get("/reports/ledger/")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "GENERAL LEDGER" in body
        assert "Opening capital" not in body  # no register rows on the index
        assert "JE-0001" not in body

    def test_index_filters_carried_into_links(self, january_activity, user):
        c = Client()
        c.force_login(user)
        resp = c.get("/reports/ledger/?month=2026-01&segment=DHPP")
        body = resp.content.decode()
        assert "month=2026-01" in body
        assert "segment=DHPP" in body

    def test_account_register_renders(self, january_activity, user, coa):
        c = Client()
        c.force_login(user)
        cash = coa["10010"]
        resp = c.get(f"/reports/ledger/{cash.id}/")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Balance Brought Forward" in body
        assert "JE-0001" in body
        assert "400,000.00" in body
        assert "392,000.00" in body

    def test_print_pages_render(self, january_activity, user, coa):
        c = Client()
        c.force_login(user)
        assert c.get("/reports/ledger/print/").status_code == 200
        cash = coa["10010"]
        assert c.get(f"/reports/ledger/{cash.id}/print/").status_code == 200

    def test_exports_respond(self, january_activity, user, coa):
        c = Client()
        c.force_login(user)
        for fmt in ("xlsx", "csv", "pdf"):
            assert c.get(f"/reports/ledger/export/?format={fmt}").status_code == 200
        cash = coa["10010"]
        for fmt in ("xlsx", "csv", "pdf"):
            resp = c.get(f"/reports/ledger/{cash.id}/export/?format={fmt}")
            assert resp.status_code == 200, fmt

    def test_login_required(self, january_activity, coa):
        c = Client()
        assert c.get("/reports/ledger/").status_code == 302
        assert c.get(f"/reports/ledger/{coa['10010'].id}/").status_code == 302


class TestLedgerErrorResilience:
    """Malformed or hostile querystrings must never produce a 500."""

    BAD_PATHS = [
        "/reports/ledger/?month=zzz",
        "/reports/ledger/?month=2026-99",
        "/reports/ledger/?month=123",
        "/reports/ledger/?start=notadate",
        "/reports/ledger/?end=9999-99-99",
        "/reports/ledger/?start=2026-1-1",
        "/reports/ledger/?segment=zzz",
        "/reports/ledger/?month=2026-01&start=junk&end=alsojunk",
        "/reports/ledger/?month=2026-02",  # exists on calendar, no activity
        "/reports/ledger/?start=2026-02-28",  # end-only-ish malformed combo
        "/reports/ledger/print/?month=zzz",
        "/reports/ledger/export/?format=csv&month=zzz",
        "/reports/ledger/export/?format=pdf&end=9999-99-99",
        "/reports/ledger/export/?format=xlsx&start=notadate&segment=zzz",
    ]

    @pytest.mark.parametrize("path", BAD_PATHS)
    def test_index_family_never_500(self, january_activity, user, path):
        c = Client()
        c.force_login(user)
        resp = c.get(path)
        assert resp.status_code == 200, path

    @pytest.mark.parametrize(
        "qs",
        [
            "month=zzz",
            "start=notadate&end=2026-02-28",
            "end=9999-99-99",
            "segment=zzz",
            "month=2026-01",
        ],
    )
    def test_register_never_500(self, january_activity, user, coa, qs):
        c = Client()
        c.force_login(user)
        cash = coa["10010"]
        resp = c.get(f"/reports/ledger/{cash.id}/?{qs}")
        assert resp.status_code == 200, qs

    def test_unknown_account_is_404_not_500(self, user):
        c = Client()
        c.force_login(user)
        assert c.get("/reports/ledger/999999/").status_code == 404

    def test_register_empty_for_segment_with_no_rows(self, january_activity, user, coa):
        c = Client()
        c.force_login(user)
        cash = coa["10010"]  # DHPP account; DMIE filter excludes all activity
        resp = c.get(f"/reports/ledger/{cash.id}/?segment=DMIE&month=2026-01")
        body = resp.content.decode()
        assert resp.status_code == 200
        assert "Balance Brought Forward" in body

    def test_register_export_never_500(self, january_activity, user, coa):
        c = Client()
        c.force_login(user)
        cash = coa["10010"]
        resp = c.get(f"/reports/ledger/{cash.id}/export/?format=csv&start=notadate")
        assert resp.status_code == 200

    def test_ledger_index_with_no_posting_is_200(self, user):
        c = Client()
        c.force_login(user)
        assert c.get("/reports/ledger/").status_code == 200
        assert c.get("/reports/ledger/export/?format=csv").status_code == 200


class TestReportingErrorResilience:
    """Neighboring reporting screens (Trial Balance / General Journal) must
    not 500 on malformed query params — the ledger links into them."""

    @pytest.mark.parametrize(
        "path",
        [
            "/reports/trial-balance/?as_of=notadate",
            "/reports/trial-balance/print/?as_of=9999-99-99",
            "/reports/trial-balance/export/?format=csv&year=zzz",
            "/reports/trial-balance/export/?format=pdf&year=19xx",
            "/journal/general/?start=notadate&end=9999-99-99&segment=zzz",
            "/journal/general/export/?format=csv&start=notadate&segment=zzz",
            "/journal/general/export/?format=pdf&end=notadate",
        ],
    )
    def test_reporting_screens_never_500(self, january_activity, user, path):
        c = Client()
        c.force_login(user)
        resp = c.get(path)
        assert resp.status_code == 200, path


class TestTrialBalanceDrilldown:
    def test_account_name_links_to_ledger(self, january_activity, user, coa):
        c = Client()
        c.force_login(user)
        resp = c.get("/reports/trial-balance/")
        assert resp.status_code == 200
        cash = coa["10010"]
        href = f"/reports/ledger/{cash.id}/?start=2026-01-01&amp;end="
        assert href in resp.content.decode()

    def test_link_carries_segment(self, january_activity, user, coa):
        c = Client()
        c.force_login(user)
        resp = c.get("/reports/trial-balance/?segment=DHPP")
        cash = coa["10010"]
        assert f"/reports/ledger/{cash.id}/?start=2026-01-01&amp;end=" in resp.content.decode()
        assert "&amp;segment=DHPP" in resp.content.decode()