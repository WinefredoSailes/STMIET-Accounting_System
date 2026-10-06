"""Advances to Employees — manual reconcile, drill-down, and source linkage.

Covers the full feature set:
  - Supplier.is_employee flag + employee pickers
  - Journal Entry supplier FK (12070 requires a named party)
  - PCF Replenishment employee FK
  - Party resolution: JE/RFP/PCF all group under one employee name
  - Employee drill-down detail + export + print
  - Manual reconciliation: record → review → lock, adjusting JE linkage
  - Lock immutability and variance math
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.ap.models import AdvanceReconciliation, Supplier
from apps.cash.models import PCFReplenishment, PettyCashFund
from apps.foundation.models import Account, Segment
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService
from apps.ui.services import ADVANCE_ACCOUNT_MATCH, advances_subsidiary_ledger

FORMATS = {
    "pdf": ("application/pdf", b"%PDF-"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"PK\x03\x04"),
    "csv": ("text/csv", None),
}


def _post(company, segment, date_, lines, entry_no, desc, *, supplier_name="", supplier=None):
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
        supplier=supplier,
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
def employee(db, company, segment):
    return Supplier.objects.create(
        code="E001",
        name="Juan Dela Cruz",
        supplier_type="other",
        is_employee=True,
        default_segment=segment,
    )


@pytest.fixture
def employee2(db, company, segment):
    return Supplier.objects.create(
        code="E002",
        name="Maria Santos",
        supplier_type="other",
        is_employee=True,
        default_segment=segment,
    )


@pytest.fixture
def non_employee_supplier(db, company, segment):
    return Supplier.objects.create(
        code="S001",
        name="Shell Fuel Depot",
        supplier_type="depot",
        is_employee=False,
        default_segment=segment,
    )


@pytest.fixture
def advance_activity(company, segment, accounts, employee, employee2):
    """Two employees with advances via JE (supplier FK), plus one via RFP."""
    _post(
        company, segment, date(2026, 1, 6),
        [("12070", "30000.00"), ("21010", "-30000.00")], "JE-1001",
        "Cash advance - Juan", supplier=employee,
    )
    _post(
        company, segment, date(2026, 1, 8),
        [("12070", "20000.00"), ("21010", "-20000.00")], "JE-1002",
        "Cash advance - Maria", supplier=employee2,
    )
    _post(
        company, segment, date(2026, 2, 6),
        [("21010", "15000.00"), ("12070", "-15000.00")], "JE-1003",
        "Liquidation - Juan", supplier=employee,
    )
    return segment


class TestSupplierEmployeeFlag:
    def test_is_employee_defaults_false(self, db, company, segment):
        s = Supplier.objects.create(code="X001", name="Test Co", default_segment=segment)
        assert s.is_employee is False

    def test_is_employee_can_be_set(self, db, company, segment):
        s = Supplier.objects.create(code="X002", name="Emp Co", is_employee=True, default_segment=segment)
        assert s.is_employee is True

    def test_employee_picker_filters(self, client, user, employee, non_employee_supplier):
        client.force_login(user)
        resp = client.get("/foundation/supplier-options/?employees=1")
        assert resp.status_code == 200
        data = resp.json()
        names = [r["text"] for r in data]
        assert any("Juan Dela Cruz" in n for n in names)
        assert not any("Shell Fuel Depot" in n for n in names)

    def test_employee_picker_without_flag_returns_all(self, client, user, employee, non_employee_supplier):
        client.force_login(user)
        resp = client.get("/foundation/supplier-options/")
        assert resp.status_code == 200
        data = resp.json()
        names = [r["text"] for r in data]
        assert any("Juan Dela Cruz" in n for n in names)
        assert any("Shell Fuel Depot" in n for n in names)


class TestJournalEntrySupplierLinkage:
    def test_je_with_supplier_fk_resolves_party(self, company, segment, employee, advance_activity):
        data = advances_subsidiary_ledger(
            company=company, start=date(2026, 1, 1), end=date(2026, 1, 31)
        )
        juan = next(s for s in data["sections"] if s["party"] == "Juan Dela Cruz")
        assert juan["closing"] == Decimal("30000.00")
        assert juan["supplier_id"] == employee.id

    def test_je_without_supplier_falls_back_to_name(self, company, segment, advance_activity):
        _post(
            company, segment, date(2026, 1, 10),
            [("12070", "5000.00"), ("21010", "-5000.00")], "JE-1004",
            "Cash advance - Ghost", supplier_name="Ghost Employee",
        )
        data = advances_subsidiary_ledger(
            company=company, start=date(2026, 1, 1), end=date(2026, 1, 31)
        )
        ghost = next(s for s in data["sections"] if s["party"] == "Ghost Employee")
        assert ghost["closing"] == Decimal("5000.00")
        assert ghost["supplier_id"] is None

    def test_je_form_requires_party_for_12070(self, client, user, company, segment, accounts, fiscal_period):
        client.force_login(user)
        resp = client.post("/journal/new/", {
            "transaction_date": "2026-01-15",
            "account": [accounts["12070"].id, accounts["21010"].id],
            "line_segment": [segment.id, segment.id],
            "debit": ["10000.00", ""],
            "credit": ["", "10000.00"],
            "line_description": ["Advance", "AP"],
        })
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "pick the employee" in body.lower() or "12070" in body

    def test_je_form_with_supplier_id_saves_fk(self, client, user, company, segment, accounts, fiscal_period, employee):
        client.force_login(user)
        resp = client.post("/journal/new/", {
            "transaction_date": "2026-01-15",
            "supplier_id": str(employee.id),
            "supplier_kind": "supplier",
            "account": [accounts["12070"].id, accounts["21010"].id],
            "line_segment": [segment.id, segment.id],
            "debit": ["10000.00", ""],
            "credit": ["", "10000.00"],
            "line_description": ["Advance", "AP"],
        })
        assert resp.status_code == 302
        je = JournalEntry.objects.order_by("-id").first()
        assert je.supplier_id == employee.id
        assert je.supplier_name == "Juan Dela Cruz"

    def test_je_form_without_12070_does_not_require_party(self, client, user, company, segment, accounts, fiscal_period):
        client.force_login(user)
        resp = client.post("/journal/new/", {
            "transaction_date": "2026-01-15",
            "account": [accounts["61100"].id, accounts["21010"].id],
            "line_segment": [segment.id, segment.id],
            "debit": ["5000.00", ""],
            "credit": ["", "5000.00"],
            "line_description": ["Expense", "AP"],
        })
        assert resp.status_code == 302


class TestPCFEmployeeLinkage:
    def test_pcf_post_je_resolves_employee(self, company, segment, employee, accounts):
        from apps.cash.services import PCFService

        fund = PettyCashFund.objects.create(
            fund_code="GEN", name="General Fund", custodian=None,
            imprest_amount=Decimal("20000.00"),
            gl_account=accounts["10110"], company=company,
        )
        replen = PCFService.request_replenishment(
            fund,
            [{"account_code": "12070", "amount": "5000.00", "description": "Advance to Juan"}],
            user=None,
        )
        replen.employee = employee
        replen.payee_name = employee.name
        replen.save(update_fields=["employee", "payee_name"])

        PCFService._post_je(replen, user=None, segment=segment)

        data = advances_subsidiary_ledger(
            company=company, start=date(2026, 1, 1), end=date(2026, 12, 31)
        )
        juan = next((s for s in data["sections"] if s["party"] == "Juan Dela Cruz"), None)
        assert juan is not None
        assert juan["closing"] == Decimal("5000.00")

    def test_pcf_form_requires_employee_for_12070(self, client, user, company, segment, accounts, fiscal_period):
        from apps.cash.models import PettyCashFund

        client.force_login(user)
        fund = PettyCashFund.objects.create(
            fund_code="GEN2", name="Fund 2", custodian=user,
            imprest_amount=Decimal("20000.00"),
            gl_account=accounts["10110"], company=company,
        )
        resp = client.post("/cash/pcf/replenish/", {
            "fund": fund.id,
            "exp_account": [accounts["12070"].code],
            "exp_segment": [segment.code],
            "exp_debit": ["5000.00"],
            "exp_credit": [""],
            "exp_description": ["Advance"],
            "exp_supplier": [""],
        })
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "12070" in body.lower() or "employee" in body.lower()

    def test_pcf_form_with_employee_saves_fk(self, client, user, company, segment, accounts, fiscal_period, employee, non_employee_supplier):
        from apps.cash.models import PettyCashFund

        client.force_login(user)
        fund = PettyCashFund.objects.create(
            fund_code="GEN3", name="Fund 3", custodian=user,
            imprest_amount=Decimal("20000.00"),
            gl_account=accounts["10110"], company=company,
        )
        resp = client.post("/cash/pcf/replenish/", {
            "fund": fund.id,
            "employee": str(employee.id),
            "exp_account": [accounts["12070"].code],
            "exp_segment": [segment.code],
            "exp_debit": ["5000.00"],
            "exp_credit": [""],
            "exp_description": ["Advance"],
            "exp_supplier": [str(non_employee_supplier.id)],
        })
        assert resp.status_code == 302
        replen = PCFReplenishment.objects.order_by("-id").first()
        assert replen.employee_id == employee.id
        assert replen.payee_name == "Juan Dela Cruz"


class TestEmployeeDrilldown:
    def test_employee_detail_page_renders(self, client, user, advance_activity, employee):
        client.force_login(user)
        resp = client.get(f"/ap/advances/ledger/employee/{employee.id}/?start=2026-01-01&end=2026-01-31")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Juan Dela Cruz" in body
        assert "30,000.00" in body
        assert "JE-1001" in body
        assert "Manual reconciliation" in body

    def test_employee_detail_filters_by_date_range(self, client, user, advance_activity, employee):
        client.force_login(user)
        resp = client.get(f"/ap/advances/ledger/employee/{employee.id}/?start=2026-02-01&end=2026-02-28")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Juan Dela Cruz" in body
        assert "15,000.00" in body
        assert "JE-1003" in body
        assert "JE-1001" not in body

    def test_employee_detail_by_name(self, client, user, advance_activity):
        client.force_login(user)
        resp = client.get("/ap/advances/ledger/employee/Juan%20Dela%20Cruz/?start=2026-01-01&end=2026-01-31")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Juan Dela Cruz" in body

    def test_employee_detail_empty_state(self, client, user, advance_activity, employee2):
        client.force_login(user)
        resp = client.get(f"/ap/advances/ledger/employee/{employee2.id}/?start=2026-03-01&end=2026-03-31")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "No posted GL activity" in body

    def test_employee_detail_export_csv(self, client, user, advance_activity, employee):
        client.force_login(user)
        resp = client.get(f"/ap/advances/ledger/employee/{employee.id}/export/?format=csv&start=2026-01-01&end=2026-01-31")
        assert resp.status_code == 200
        text = resp.content.decode("utf-8", "replace")
        assert "Juan Dela Cruz" in text
        assert "JE-1001" in text

    def test_employee_detail_export_xlsx(self, client, user, advance_activity, employee):
        client.force_login(user)
        resp = client.get(f"/ap/advances/ledger/employee/{employee.id}/export/?format=xlsx&start=2026-01-01&end=2026-01-31")
        assert resp.status_code == 200
        ctype, magic = FORMATS["xlsx"]
        assert resp["Content-Type"].startswith(ctype)
        assert resp.content.startswith(magic)

    def test_employee_detail_print(self, client, user, advance_activity, employee):
        client.force_login(user)
        resp = client.get(f"/ap/advances/ledger/employee/{employee.id}/print/?start=2026-01-01&end=2026-01-31")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Juan Dela Cruz" in body
        assert "stmiet-trans-logo.png" in body

    def test_employee_detail_login_required(self, client, db, employee):
        resp = client.get(f"/ap/advances/ledger/employee/{employee.id}/")
        assert resp.status_code == 302

    def test_employee_detail_unknown_key_redirects(self, client, user):
        client.force_login(user)
        resp = client.get("/ap/advances/ledger/employee/99999/")
        assert resp.status_code == 302


class TestLedgerEmployeeLinks:
    def test_ledger_section_has_clickable_name(self, client, user, advance_activity, employee):
        client.force_login(user)
        resp = client.get("/ap/advances/ledger/?start=2026-01-01&end=2026-01-31")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert f"/ap/advances/ledger/employee/{employee.id}/" in body

    def test_ledger_row_has_clickable_party(self, client, user, advance_activity, employee):
        client.force_login(user)
        resp = client.get("/ap/advances/ledger/?start=2026-01-01&end=2026-01-31")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Juan Dela Cruz" in body

    def test_ledger_employee_filter_narrows(self, company, segment, employee, employee2, advance_activity):
        data = advances_subsidiary_ledger(
            company=company, start=date(2026, 1, 1), end=date(2026, 1, 31),
            employee="Juan Dela Cruz",
        )
        assert len(data["sections"]) == 1
        assert data["sections"][0]["party"] == "Juan Dela Cruz"
        assert data["sections"][0]["closing"] == Decimal("30000.00")

    def test_ledger_employee_filter_by_supplier_id(self, company, segment, employee, advance_activity):
        data = advances_subsidiary_ledger(
            company=company, start=date(2026, 1, 1), end=date(2026, 1, 31),
            employee=str(employee.id),
        )
        assert len(data["sections"]) == 1
        assert data["sections"][0]["party"] == "Juan Dela Cruz"


class TestManualReconciliation:
    def test_recon_record_creates_draft(self, client, user, advance_activity, employee):
        client.force_login(user)
        resp = client.post(f"/ap/advances/ledger/employee/{employee.id}/reconcile/", {
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gl_balance": "30000.00",
            "reviewed_balance": "25000.00",
            "memo": "Payroll deduction not yet posted",
        })
        assert resp.status_code == 302
        recon = AdvanceReconciliation.objects.get()
        assert recon.employee_name == "Juan Dela Cruz"
        assert recon.gl_balance == Decimal("30000.00")
        assert recon.reviewed_balance == Decimal("25000.00")
        assert recon.variance == Decimal("-5000.00")
        assert recon.status == "draft"
        assert recon.memo == "Payroll deduction not yet posted"

    def test_recon_variance_zero_when_matching(self, client, user, advance_activity, employee):
        client.force_login(user)
        client.post(f"/ap/advances/ledger/employee/{employee.id}/reconcile/", {
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gl_balance": "30000.00",
            "reviewed_balance": "30000.00",
            "memo": "All clear",
        })
        recon = AdvanceReconciliation.objects.get()
        assert recon.variance == Decimal("0.00")

    def test_recon_review_transitions_status(self, client, user, advance_activity, employee):
        client.force_login(user)
        client.post(f"/ap/advances/ledger/employee/{employee.id}/reconcile/", {
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gl_balance": "30000.00",
            "reviewed_balance": "30000.00",
            "memo": "OK",
        })
        recon = AdvanceReconciliation.objects.get()
        resp = client.post(f"/ap/advances/recon/{recon.id}/review/")
        assert resp.status_code == 302
        recon.refresh_from_db()
        assert recon.status == "reviewed"
        assert recon.reviewed_by == user

    def test_recon_lock_requires_head(self, client, user, advance_activity, employee):
        client.force_login(user)
        client.post(f"/ap/advances/ledger/employee/{employee.id}/reconcile/", {
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gl_balance": "30000.00",
            "reviewed_balance": "30000.00",
            "memo": "OK",
        })
        recon = AdvanceReconciliation.objects.get()
        client.post(f"/ap/advances/recon/{recon.id}/review/")
        resp = client.post(f"/ap/advances/recon/{recon.id}/lock/")
        assert resp.status_code == 302
        recon.refresh_from_db()
        assert recon.status == "reviewed"

    def test_recon_lock_succeeds_as_head(self, client, role_users, advance_activity, employee):
        head = role_users["head"]
        client.force_login(head)
        client.post(f"/ap/advances/ledger/employee/{employee.id}/reconcile/", {
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gl_balance": "30000.00",
            "reviewed_balance": "30000.00",
            "memo": "OK",
        })
        recon = AdvanceReconciliation.objects.get()
        client.post(f"/ap/advances/recon/{recon.id}/review/")
        resp = client.post(f"/ap/advances/recon/{recon.id}/lock/")
        assert resp.status_code == 302
        recon.refresh_from_db()
        assert recon.status == "locked"
        assert recon.locked_by == head

    def test_recon_lock_requires_zero_variance_or_adjustment(self, client, role_users, advance_activity, employee):
        head = role_users["head"]
        client.force_login(head)
        client.post(f"/ap/advances/ledger/employee/{employee.id}/reconcile/", {
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gl_balance": "30000.00",
            "reviewed_balance": "25000.00",
            "memo": "Variance exists",
        })
        recon = AdvanceReconciliation.objects.get()
        client.post(f"/ap/advances/recon/{recon.id}/review/")
        resp = client.post(f"/ap/advances/recon/{recon.id}/lock/")
        assert resp.status_code == 302
        recon.refresh_from_db()
        assert recon.status == "reviewed"

    def test_recon_locked_is_immutable(self, client, role_users, advance_activity, employee):
        head = role_users["head"]
        client.force_login(head)
        client.post(f"/ap/advances/ledger/employee/{employee.id}/reconcile/", {
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gl_balance": "30000.00",
            "reviewed_balance": "30000.00",
            "memo": "OK",
        })
        recon = AdvanceReconciliation.objects.get()
        client.post(f"/ap/advances/recon/{recon.id}/review/")
        client.post(f"/ap/advances/recon/{recon.id}/lock/")
        resp = client.post(f"/ap/advances/ledger/employee/{employee.id}/reconcile/", {
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gl_balance": "30000.00",
            "reviewed_balance": "30000.00",
            "memo": "Try to overwrite",
        })
        assert resp.status_code == 302
        recon.refresh_from_db()
        assert recon.memo == "OK"

    def test_recon_link_adjustment_je(self, client, user, company, segment, advance_activity, employee):
        client.force_login(user)
        client.post(f"/ap/advances/ledger/employee/{employee.id}/reconcile/", {
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gl_balance": "30000.00",
            "reviewed_balance": "25000.00",
            "memo": "Payroll deduction",
        })
        recon = AdvanceReconciliation.objects.get()

        adj_je = _post(
            company, segment, date(2026, 1, 31),
            [("61100", "5000.00"), ("12070", "-5000.00")], "JE-ADJ-001",
            "Payroll deduction - Juan", supplier=employee,
        )

        resp = client.post(f"/ap/advances/recon/{recon.id}/link/", {
            "entry_no": adj_je.entry_no,
        })
        assert resp.status_code == 302
        recon.refresh_from_db()
        assert recon.adjustment_je == adj_je

    def test_recon_link_requires_posted_je(self, client, user, company, segment, advance_activity, employee):
        client.force_login(user)
        client.post(f"/ap/advances/ledger/employee/{employee.id}/reconcile/", {
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gl_balance": "30000.00",
            "reviewed_balance": "25000.00",
            "memo": "Payroll deduction",
        })
        recon = AdvanceReconciliation.objects.get()

        je = JournalEntry.objects.create(
            entry_no="JE-DRAFT-001",
            company=company,
            segment=segment,
            transaction_date=date(2026, 1, 31),
            status=PostingStatus.DRAFT,
            description="Draft adjustment",
        )

        resp = client.post(f"/ap/advances/recon/{recon.id}/link/", {
            "entry_no": je.entry_no,
        })
        assert resp.status_code == 302
        recon.refresh_from_db()
        assert recon.adjustment_je is None

    def test_recon_link_with_adjustment_allows_lock(self, client, role_users, company, segment, advance_activity, employee):
        head = role_users["head"]
        client.force_login(head)
        client.post(f"/ap/advances/ledger/employee/{employee.id}/reconcile/", {
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gl_balance": "30000.00",
            "reviewed_balance": "25000.00",
            "memo": "Payroll deduction",
        })
        recon = AdvanceReconciliation.objects.get()

        adj_je = _post(
            company, segment, date(2026, 1, 31),
            [("61100", "5000.00"), ("12070", "-5000.00")], "JE-ADJ-002",
            "Payroll deduction - Juan", supplier=employee,
        )

        client.post(f"/ap/advances/recon/{recon.id}/link/", {"entry_no": adj_je.entry_no})
        client.post(f"/ap/advances/recon/{recon.id}/review/")
        resp = client.post(f"/ap/advances/recon/{recon.id}/lock/")
        assert resp.status_code == 302
        recon.refresh_from_db()
        assert recon.status == "locked"


class TestReconService:
    def test_record_validates_period(self, employee):
        from apps.ap.services import AdvanceReconService

        with pytest.raises(Exception):
            AdvanceReconService.record(
                employee_name="Juan Dela Cruz",
                period_start=date(2026, 1, 31),
                period_end=date(2026, 1, 1),
                gl_balance="0",
                reviewed_balance="0",
            )

    def test_record_resolves_supplier_by_name(self, employee):
        from apps.ap.services import AdvanceReconService

        recon = AdvanceReconService.record(
            employee_name="Juan Dela Cruz",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            gl_balance="10000",
            reviewed_balance="10000",
        )
        assert recon.supplier == employee

    def test_record_duplicate_period_reuses_draft(self, employee):
        from apps.ap.services import AdvanceReconService

        r1 = AdvanceReconService.record(
            employee_name="Juan Dela Cruz",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            gl_balance="10000",
            reviewed_balance="10000",
        )
        r2 = AdvanceReconService.record(
            employee_name="Juan Dela Cruz",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            gl_balance="12000",
            reviewed_balance="10000",
        )
        assert r1.id == r2.id
        assert r2.gl_balance == Decimal("12000.00")

    def test_record_rejects_edit_of_reviewed(self, employee):
        from apps.ap.services import AdvanceReconService

        recon = AdvanceReconService.record(
            employee_name="Juan Dela Cruz",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            gl_balance="10000",
            reviewed_balance="10000",
        )
        AdvanceReconService.review(recon, user=None)
        with pytest.raises(Exception):
            AdvanceReconService.record(
                employee_name="Juan Dela Cruz",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                gl_balance="99999",
                reviewed_balance="10000",
            )


class TestReconLedgerIntegration:
    def test_ledger_shows_recon_status(self, client, user, advance_activity, employee):
        client.force_login(user)
        client.post(f"/ap/advances/ledger/employee/{employee.id}/reconcile/", {
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gl_balance": "30000.00",
            "reviewed_balance": "30000.00",
            "memo": "OK",
        })
        resp = client.get("/ap/advances/ledger/?start=2026-01-01&end=2026-01-31")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Recon draft" in body

    def test_employee_detail_shows_recon_history(self, client, user, advance_activity, employee):
        client.force_login(user)
        client.post(f"/ap/advances/ledger/employee/{employee.id}/reconcile/", {
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "gl_balance": "30000.00",
            "reviewed_balance": "30000.00",
            "memo": "All clear",
        })
        resp = client.get(f"/ap/advances/ledger/employee/{employee.id}/?start=2026-01-01&end=2026-01-31")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "All clear" in body
        assert "2026-01-01" in body

    def test_ledger_recon_open_count(self, company, segment, employee, advance_activity):
        data = advances_subsidiary_ledger(
            company=company, start=date(2026, 1, 1), end=date(2026, 1, 31)
        )
        assert data["recon_open_count"] >= 1


class TestPartyResolution:
    def test_je_supplier_fk_wins_over_name(self, company, segment, accounts, employee):
        _post(
            company, segment, date(2026, 1, 6),
            [("12070", "10000.00"), ("21010", "-10000.00")], "JE-2001",
            "Advance", supplier_name="Wrong Name", supplier=employee,
        )
        data = advances_subsidiary_ledger(
            company=company, start=date(2026, 1, 1), end=date(2026, 1, 31)
        )
        juan = next(s for s in data["sections"] if s["party"] == "Juan Dela Cruz")
        assert juan["closing"] == Decimal("10000.00")

    def test_pcf_party_resolves_via_source_parties(self, company, segment, employee, accounts):
        from apps.cash.services import PCFService

        fund = PettyCashFund.objects.create(
            fund_code="GEN", name="General Fund", custodian=None,
            imprest_amount=Decimal("20000.00"),
            gl_account=accounts["10110"], company=company,
        )
        replen = PCFService.request_replenishment(
            fund,
            [{"account_code": "12070", "amount": "3000.00", "description": "Advance"}],
            user=None,
        )
        replen.employee = employee
        replen.payee_name = employee.name
        replen.save(update_fields=["employee", "payee_name"])
        PCFService._post_je(replen, user=None, segment=segment)

        data = advances_subsidiary_ledger(
            company=company, start=date(2026, 1, 1), end=date(2026, 12, 31)
        )
        juan = next((s for s in data["sections"] if s["party"] == "Juan Dela Cruz"), None)
        assert juan is not None
        assert juan["closing"] == Decimal("3000.00")

    def test_rfp_party_resolves_via_payee(self, company, segment, employee, accounts):
        from apps.ap.models import RFPDocument, RFPLine
        from apps.ap.services import RFPService

        rfp = RFPService.create_rfp(
            ap_number="A0001",
            rfp_date=date(2026, 1, 15),
            payee=employee,
            segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "12070", "amount": "8000.00", "description": "Advance"},
                {"side": "cr", "segment": segment, "account_code": "21010", "amount": "8000.00", "description": "AP"},
            ],
            user=None,
        )
        rfp.status = "posted"
        rfp.save(update_fields=["status"])
        from apps.ap.services import CONSOService
        CONSOService._post_one(rfp, user=None)

        data = advances_subsidiary_ledger(
            company=company, start=date(2026, 1, 1), end=date(2026, 1, 31)
        )
        juan = next((s for s in data["sections"] if s["party"] == "Juan Dela Cruz"), None)
        assert juan is not None
        assert juan["closing"] == Decimal("8000.00")
