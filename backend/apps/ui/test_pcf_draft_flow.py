"""Petty cash voucher DRAFT step (RFP-parity preparer flow).

The voucher form saves a draft the custodian can edit freely; only
``Submit for approval`` moves it to ``requested`` and onto the Head's queue.
Drafts must be invisible to the approval inbox and refused by every
approver-side endpoint; the API mirrors the RFP contract (draft + preparer
only for edit/delete, explicit submit).
"""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.ap.models import Supplier, CheckVoucher, CONSOBatch
from apps.ap.services import CVPaymentService, RFPService, CONSOService
from apps.cash.models import PCFReplenishment, PettyCashFund
from apps.core.approvals import pending_approval_queue
from apps.foundation.models import UserProfile
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db


@pytest.fixture
def fund(db, company, accounts, role_users):
    return PettyCashFund.objects.create(
        fund_code="PCF-DRF", name="Draft Flow Fund", custodian=role_users["staff"],
        custodian_name="Staff", imprest_amount="20000.00",
        gl_account=accounts["10010"], company=company, is_active=True,
    )


@pytest.fixture
def supplier(db, segment):
    return Supplier.objects.create(name="Draftline Supplies", tin="999-888", default_segment=segment)


@pytest.fixture
def fund_b(db, company, accounts, other_staff):
    """A fellow custodian's fund: staff A may prepare vouchers on it."""
    return PettyCashFund.objects.create(
        fund_code="PCF-B", name="Fellow Fund", custodian=other_staff,
        custodian_name="Other Custodian", imprest_amount="20000.00",
        gl_account=accounts["10010"], company=company, is_active=True,
    )


@pytest.fixture
def other_staff(db):
    u = get_user_model().objects.create_user(username="otherstaff", password="x")
    UserProfile.objects.create(user=u, approval_role="staff")
    return u


def _form(fund, accounts, supplier, **over):
    data = {
        "fund": fund.pk,
        "payee_name": "Office Clerk",
        "request_date": "2026-09-05",
        "reference": "REF-DRF",
        "exp_account": [accounts["61100"].code],
        "exp_debit": ["850.00"],
        "exp_credit": [""],
        "exp_description": ["Panlabot ink"],
        "exp_segment": ["DHPP"],
        "exp_cost_center": ["OS"],
        "exp_supplier": [supplier.pk],
    }
    data.update(over)
    return data


def _create(client, fund, accounts, supplier):
    resp = client.post("/cash/pcf/replenish/", _form(fund, accounts, supplier))
    assert resp.status_code == 302
    return PCFReplenishment.objects.get()


def _pcf_items(user):
    return [i for i in pending_approval_queue(user) if i["kind"] == "pcf"]


class TestCreateLandsDraft:
    def test_form_creates_draft_off_queue(self, client, role_users, fund, accounts, supplier):
        from django.test import Client as PlainClient

        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        assert replen.status == "draft"
        assert replen.voucher_no.startswith(f"PCV-{date.today().year}-")
        # the Head sees nothing: queue empty, and the inbox page has no rows for it
        assert _pcf_items(role_users["head"]) == []
        head_client = PlainClient()
        head_client.force_login(role_users["head"])
        body = head_client.get("/approvals/").content.decode()
        assert replen.voucher_no not in body

    def test_detail_shows_draft_actions_to_custodian(self, client, role_users, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        body = client.get(f"/cash/pcf/replenishments/{replen.id}/").content.decode()
        assert "Draft — not yet submitted for approval" in body
        assert f"/cash/pcf/replenishments/{replen.id}/edit/" in body
        assert f"/cash/pcf/replenishments/{replen.id}/submit/" in body
        assert "Submit for approval" in body

    def test_detail_hides_actions_from_head(self, client, role_users, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        client.force_login(role_users["head"])
        body = client.get(f"/cash/pcf/replenishments/{replen.id}/").content.decode()
        assert "not on the Head's approval queue yet" in body
        # no approver controls on a draft
        assert f"/cash/pcf/replenishments/{replen.id}/approve/" not in body
        assert "Reject with note" not in body

    def test_register_shows_draft_badge_filter_and_card(self, client, role_users, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        _create(client, fund, accounts, supplier)
        body = client.get("/cash/pcf/replenishments/").content.decode()
        assert "bg-surface-100 text-surface-700" in body  # neutral draft badge
        assert 'value="draft"' in body                    # register filter choice
        assert "Drafts" in body                           # stat card


class TestDraftCannotBeProcessed:
    """Every approver-side verb must refuse a draft (status unchanged)."""

    @pytest.mark.parametrize("verb", ["approve", "reject", "post"])
    def test_head_verbs_refuse_draft(self, client, role_users, fund, accounts, supplier, verb):
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        client.force_login(role_users["head"])
        data = {"note": "nope"} if verb == "reject" else {}
        client.post(f"/cash/pcf/replenishments/{replen.id}/{verb}/", data)
        replen.refresh_from_db()
        assert replen.status == "draft"

    def test_service_refuses_draft_verbs(self, fund, accounts, role_users):
        from apps.cash.services import PCFService
        from apps.core.exceptions import ValidationError

        replen = PCFService.request_replenishment(
            fund, [{"account_code": accounts["61100"].code, "amount": "100.00", "description": "x"}],
            user=role_users["staff"],
        )
        with pytest.raises(ValidationError):
            PCFService.approve_replenishment(replen, user=role_users["head"])
        with pytest.raises(ValidationError):
            PCFService.reject_replenishment(replen, user=role_users["head"], note="x")
        with pytest.raises(ValidationError):
            PCFService.post_replenishment(replen, user=role_users["head"])


class TestEditDraft:
    def test_edit_form_prefills_and_saves_as_draft(self, client, role_users, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        body = client.get(f"/cash/pcf/replenishments/{replen.id}/edit/").content.decode()
        assert "Panlabot ink" in body          # description prefilled
        assert 'value="850.00"' in body        # debit prefilled
        assert "REF-DRF" in body               # reference prefilled
        assert "Save changes" in body          # draft label, not resubmit
        assert "Save &amp; resubmit" not in body

        form = _form(
            fund, accounts, supplier,
            exp_description=["Smoother ink"], exp_debit=["1,250.00"],
        )
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/edit/", form)
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "draft"
        assert replen.amount == Decimal("1250.00")
        assert replen.expenses[0]["description"] == "Smoother ink"

    def test_non_preparer_cannot_edit(self, client, role_users, other_staff, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        client.force_login(other_staff)
        assert client.get(f"/cash/pcf/replenishments/{replen.id}/edit/").status_code == 403
        assert client.post(f"/cash/pcf/replenishments/{replen.id}/submit/").status_code == 302
        replen.refresh_from_db()
        assert replen.status == "draft"  # submit by stranger did nothing (service gate)


class TestSubmitDraft:
    def test_submit_queues_for_head(self, client, role_users, fund, accounts, supplier):
        from django.test import Client as PlainClient

        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/submit/")
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "requested"
        assert [i["doc"].id for i in _pcf_items(role_users["head"])] == [replen.id]
        head_client = PlainClient()
        head_client.force_login(role_users["head"])
        body = head_client.get("/approvals/").content.decode()
        assert replen.voucher_no in body
        assert f"/cash/pcf/replenishments/{replen.id}/approve/" in body
        assert f"/cash/pcf/replenishments/{replen.id}/reject/" in body

    def test_double_submit_refused(self, client, role_users, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        client.post(f"/cash/pcf/replenishments/{replen.id}/submit/")
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/submit/", follow=True)
        assert "Only draft vouchers can be submitted" in resp.content.decode()
        replen.refresh_from_db()
        assert replen.status == "requested"


class TestFullRoundTrip:
    def test_draft_edit_submit_reject_revise_approve(self, client, role_users, fund, accounts, supplier):
        """draft -> (edit) -> requested -> rejected -> (revise) -> requested
        -> approved -> CONSO-posted, entirely through the UI."""
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)

        client.post(
            f"/cash/pcf/replenishments/{replen.id}/edit/",
            _form(fund, accounts, supplier, exp_debit=["900.00"], exp_description=["Ink v2"]),
        )
        replen.refresh_from_db()
        assert (replen.status, str(replen.amount)) == ("draft", "900.00")

        client.post(f"/cash/pcf/replenishments/{replen.id}/submit/")
        replen.refresh_from_db()
        assert replen.status == "requested"

        client.force_login(role_users["head"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/reject/", {"note": "Too high this week"})
        replen.refresh_from_db()
        assert replen.status == "rejected"

        client.force_login(role_users["staff"])
        client.post(
            f"/cash/pcf/replenishments/{replen.id}/revise/",
            _form(fund, accounts, supplier, exp_debit=["450.00"], exp_description=["Ink (trimmed)"]),
        )
        replen.refresh_from_db()
        assert replen.status == "requested"
        assert replen.amount == Decimal("450.00")
        assert replen.rejection_note == ""

        client.force_login(role_users["head"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/approve/")
        replen.refresh_from_db()
        assert replen.status == "approved"
        resp = client.post(f"/ap/conso/{replen.conso_id}/post/")
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "posted"


class TestApiDraftContract:
    def test_api_replenish_creates_draft_and_submit_queues(self, role_users, fund, accounts):
        api = APIClient()
        api.force_authenticate(user=role_users["staff"])
        resp = api.post(
            f"/api/v1/cash/pcf-funds/{fund.pk}/replenish/",
            {"expenses": [{"account_code": accounts["61100"].code, "amount": "300.00", "description": "x"}]},
            format="json",
        )
        assert resp.status_code == 201
        replen_id = resp.json()["id"]
        assert resp.json()["status"] == "draft"

        resp = api.post(f"/api/v1/cash/pcf-replenishments/{replen_id}/submit/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "requested"

    def test_status_is_not_client_writable(self, role_users, fund, accounts):
        api = APIClient()
        api.force_authenticate(user=role_users["staff"])
        resp = api.post(
            f"/api/v1/cash/pcf-funds/{fund.pk}/replenish/",
            {"expenses": [{"account_code": accounts["61100"].code, "amount": "100.00", "description": "x"}]},
            format="json",
        )
        pk = resp.json()["id"]
        resp = api.patch(f"/api/v1/cash/pcf-replenishments/{pk}/", {"status": "approved"}, format="json")
        assert resp.status_code == 200
        assert resp.json()["status"] == "draft"

    def test_edit_and_delete_gated_to_draft_preparer(self, role_users, other_staff, fund, accounts):
        api = APIClient()
        api.force_authenticate(user=role_users["staff"])
        resp = api.post(
            f"/api/v1/cash/pcf-funds/{fund.pk}/replenish/",
            {"expenses": [{"account_code": accounts["61100"].code, "amount": "100.00", "description": "x"}]},
            format="json",
        )
        pk = resp.json()["id"]

        # preparer may edit while draft
        resp = api.patch(f"/api/v1/cash/pcf-replenishments/{pk}/", {"reference": "R1"}, format="json")
        assert resp.status_code == 200
        assert resp.json()["reference"] == "R1"

        # a stranger may not touch it
        other = APIClient()
        other.force_authenticate(user=other_staff)
        assert other.patch(f"/api/v1/cash/pcf-replenishments/{pk}/", {"reference": "R2"}, format="json").status_code == 403
        assert other.delete(f"/api/v1/cash/pcf-replenishments/{pk}/").status_code == 403

        # after it leaves the desk, edits/deletes are refused even for the preparer
        api.post(f"/api/v1/cash/pcf-replenishments/{pk}/submit/")
        assert api.patch(f"/api/v1/cash/pcf-replenishments/{pk}/", {"reference": "R3"}, format="json").status_code == 403
        assert api.delete(f"/api/v1/cash/pcf-replenishments/{pk}/").status_code == 403


    def test_preparer_can_discard_own_draft(self, role_users, fund, accounts):
        api = APIClient()
        api.force_authenticate(user=role_users["staff"])
        resp = api.post(
            f"/api/v1/cash/pcf-funds/{fund.pk}/replenish/",
            {"expenses": [{"account_code": accounts["61100"].code, "amount": "50.00", "description": "x"}]},
            format="json",
        )
        pk = resp.json()["id"]
        assert api.delete(f"/api/v1/cash/pcf-replenishments/{pk}/").status_code == 204
        assert not PCFReplenishment.objects.filter(pk=pk).exists()


class TestGLAccountNamePersisted:
    """The GL title (code + name) survives every save path — create, draft
    edit, rejected-revise — and the detail screen resolves names even for
    rows stored before the name was captured."""

    def test_create_stores_name_and_detail_shows_it(self, client, role_users, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        assert replen.expenses[0]["account_name"] == accounts["61100"].name
        body = client.get(f"/cash/pcf/replenishments/{replen.id}/").content.decode()
        assert f"{accounts['61100'].code} {accounts['61100'].name}" in body

    def test_draft_edit_keeps_account_name(self, client, role_users, fund, accounts, supplier):
        """Regression: the draft-edit POST used to rewrite expenses without
        account_name, wiping the GL title from the detail screen."""
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        resp = client.post(
            f"/cash/pcf/replenishments/{replen.id}/edit/",
            _form(fund, accounts, supplier, exp_debit=["1,000.00"], exp_description=["Ink v2"]),
        )
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.expenses[0]["account_name"] == accounts["61100"].name
        body = client.get(f"/cash/pcf/replenishments/{replen.id}/").content.decode()
        assert f"{accounts['61100'].code} {accounts['61100'].name}" in body

    def test_revise_keeps_account_name(self, client, role_users, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        client.post(f"/cash/pcf/replenishments/{replen.id}/submit/")
        client.force_login(role_users["head"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/reject/", {"note": "trim it"})
        client.force_login(role_users["staff"])
        resp = client.post(
            f"/cash/pcf/replenishments/{replen.id}/revise/",
            _form(fund, accounts, supplier, exp_debit=["400.00"], exp_description=["Ink (trimmed)"]),
        )
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "requested"
        assert replen.expenses[0]["account_name"] == accounts["61100"].name

    def test_detail_resolves_name_for_stored_rows_without_one(self, client, role_users, fund, accounts):
        """Old vouchers (JSON predating account_name) still show the title."""
        replen = PCFReplenishment.objects.create(
            fund=fund, request_date=date(2026, 9, 5), amount=Decimal("100.00"),
            expenses=[
                {"account_code": accounts["61100"].code, "side": "dr", "amount": "100.00",
                 "description": "Legacy line", "segment": "DHPP", "cost_center": "OS"}
            ],
            status="draft", requested_by=role_users["staff"], voucher_no="PCV-LEGACY-0001",
        )
        client.force_login(role_users["staff"])
        body = client.get(f"/cash/pcf/replenishments/{replen.id}/").content.decode()
        assert f"{accounts['61100'].code} {accounts['61100'].name}" in body

    def test_service_survives_unknown_account_code(self, fund, role_users):
        from apps.cash.services import PCFService

        replen = PCFService.request_replenishment(
            fund, [{"account_code": "99999", "amount": "50.00", "description": "ghost"}],
            user=role_users["staff"],
        )
        assert replen.expenses[0]["account_name"] == ""

    def test_form_rejects_unknown_account_code(self, client, role_users, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        resp = client.post("/cash/pcf/replenish/", _form(fund, accounts, supplier, exp_account=["99999"]))
        assert resp.status_code == 200
        assert "not found" in resp.content.decode()
        assert PCFReplenishment.objects.count() == 0


class TestPcfToCheckVoucherFlow:
    """PCF replenishment → Check Voucher parity with RFP flow:
    approved + CONSO-posted PCF can be issued a CV; CV approve → clear;
    disbursement stamped. Print/detail render correctly for both sources."""

    @pytest.fixture
    def post_pc_fund(self, company, segment, accounts, role_users):
        return PettyCashFund.objects.create(
            fund_code="PCF-CV", name="CV Test Fund", custodian=role_users["staff"],
            custodian_name="Test Custodian", imprest_amount="20000.00",
            gl_account=accounts["10010"], company=company, is_active=True,
        )

    def test_create_cv_from_posted_pcf(self, client, role_users, post_pc_fund, accounts, supplier):
        """Full lifecycle: draft → submit → approve → post → create CV."""
        from apps.cash.models import PCFReplenishment

        # Prepare & submit
        client.force_login(role_users["staff"])
        resp = client.post("/cash/pcf/replenish/", _form(post_pc_fund, accounts, supplier))
        assert resp.status_code == 302
        replen = PCFReplenishment.objects.get()
        assert replen.status == "draft"

        # Staff submits (draft → requested)
        client.force_login(role_users["staff"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/submit/")
        replen.refresh_from_db()
        assert replen.status == "requested"

        # Head approves (auto-creates CONSO batch)
        client.force_login(role_users["head"])
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/approve/")
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "approved"

        # Post through CONSO
        resp = client.post(f"/ap/conso/{replen.conso_id}/post/")
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "posted"
        assert replen.journal_entry_id

        # Create CV against posted PCF
        bank = accounts["10110"]
        resp = client.post("/ap/cv/new/", {
            "source_type": "pcf",
            "source_id": replen.pk,
            "bank_account": bank.pk,
            "cv_date": "2026-09-15",
            "gross_amount": str(replen.amount),
            "withheld_tax": "0.00",
            "check_no": "",
        })
        assert resp.status_code == 302  # redirect to detail
        cv = CheckVoucher.objects.last()
        assert cv is not None
        assert PCFReplenishment.objects.get(pk=replen.pk).cv_id  # FK set

    def test_cv_from_pcf_has_correct_je(self, client, role_users, post_pc_fund, accounts, supplier):
        """CV created from PCF source builds 2-line JE: Dr Fund | Cr Bank — no WHT."""
        from apps.cash.models import PCFReplenishment

        # Prep → submit → approve → post → CV
        client.force_login(role_users["staff"])
        resp = client.post("/cash/pcf/replenish/", _form(post_pc_fund, accounts, supplier))
        assert resp.status_code == 302
        replen = PCFReplenishment.objects.get()

        # Submit (draft → requested)
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/submit/")
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "requested"

        client.force_login(role_users["head"])
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/approve/")
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "approved"
        assert replen.conso_id is not None

        resp = client.post(f"/ap/conso/{replen.conso_id}/post/")
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "posted"

        # Create CV
        resp = client.post("/ap/cv/new/", {
            "source_type": "pcf", "source_id": replen.pk,
            "bank_account": accounts["10110"].pk,
            "cv_date": "2026-09-15", "gross_amount": str(replen.amount),
            "withheld_tax": "0.00", "check_no": "",
        })
        assert resp.status_code == 302
        cv = CheckVoucher.objects.last()
        assert cv.rfp_id is None  # not an RFP-backed CV
        assert cv.journal_entry_id

        entry = cv.journal_entry
        lines = list(entry.lines.all().order_by("line_no"))
        assert len(lines) == 2, f"Expected 2 lines (no WHT), got {len(lines)}"

        # Line 1: Dr Fund GL
        assert lines[0].debit > 0
        assert lines[0].account_id == post_pc_fund.gl_account_id

        # Line 2: Cr Bank Account
        assert lines[1].credit > 0
        assert lines[1].account_id == accounts["10110"].id

        # No withholding tax line
        wht_lines = [l for l in lines if l.account.account_type in ("liability",)]
        wht = [l for l in wht_lines if "wht" in l.description.lower() or "withholding" in l.description.lower()]
        assert len(wht) == 0, "No WHT line should exist for PCF-sourced CV"

    def test_cv_detail_shows_pcf_metadata(self, client, role_users, post_pc_fund, accounts, supplier):
        """GET /ap/cv/<pk>/ renders PCF context fields when CV pays a PCF."""
        from apps.cash.models import PCFReplenishment
        from apps.ap.models import CheckVoucher

        client.force_login(role_users["staff"])
        resp = client.post("/cash/pcf/replenish/", _form(post_pc_fund, accounts, supplier))
        assert resp.status_code == 302
        replen = PCFReplenishment.objects.get()

        # Submit (draft → requested)
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/submit/")
        assert resp.status_code == 302
        client.force_login(role_users["head"])
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/approve/")
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.conso_id is not None
        client.post(f"/ap/conso/{replen.conso_id}/post/")
        replen.refresh_from_db()

        resp = client.post("/ap/cv/new/", {
            "source_type": "pcf", "source_id": replen.pk,
            "bank_account": accounts["10110"].pk,
            "cv_date": "2026-09-15", "gross_amount": str(replen.amount),
            "withheld_tax": "0.00", "check_no": "",
        })
        assert resp.status_code == 302
        cv = CheckVoucher.objects.last()
        body = client.get(f"/ap/cv/{cv.pk}/").content.decode()
        assert replen.voucher_no in body
        assert post_pc_fund.fund_code in body

    def test_clear_stamps_check_disbursement(self, client, role_users, post_pc_fund, accounts, supplier):
        """CV clear action stamps CheckDisbursement record with cleared_at."""
        from apps.cash.models import PCFReplenishment, CheckDisbursement
        from apps.ap.models import CheckVoucher

        client.force_login(role_users["staff"])
        resp = client.post("/cash/pcf/replenish/", _form(post_pc_fund, accounts, supplier))
        assert resp.status_code == 302
        replen = PCFReplenishment.objects.get()

        # Submit (draft → requested)
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/submit/")
        assert resp.status_code == 302
        client.force_login(role_users["head"])
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/approve/")
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.conso_id is not None
        client.post(f"/ap/conso/{replen.conso_id}/post/")
        replen.refresh_from_db()

        resp = client.post("/ap/cv/new/", {
            "source_type": "pcf", "source_id": replen.pk,
            "bank_account": accounts["10110"].pk,
            "cv_date": "2026-09-15", "gross_amount": str(replen.amount),
            "withheld_tax": "0.00", "check_no": "CHK-001",
        })
        assert resp.status_code == 302
        cv = CheckVoucher.objects.last()

        # Approve then clear
        assert client.post(f"/ap/cv/{cv.pk}/approve/").status_code == 302
        assert CheckDisbursement.objects.filter(cv_id=cv.pk).count() == 0

        # Clear stamps disb record
        resp = client.post(f"/ap/cv/{cv.pk}/clear/")
        assert resp.status_code == 302
        assert CheckDisbursement.objects.filter(cv_id=cv.pk).exists()

    def test_rfp_to_cv_still_works(self, client, company, segment, accounts, user, supplier, fiscal_period, segment_account_map):
        """Regression: existing RFP → CV flow remains unchanged."""
        # Use the existing TestPCFReplenishmentScreen fixture setup pattern:
        # Create an RFP, fully approve it (checked → acctg → fin), let auto-assign
        # add it to CONSO, then post → issued.
        from django.contrib.auth import get_user_model
        from apps.foundation.models import UserProfile
        from apps.ap.services import RFPService, CONSOService

        h = get_user_model().objects.create_user(username="head2", password="x")
        UserProfile.objects.create(user=h, approval_role="head")

        rfp = RFPService.create_rfp(
            ap_number="A9998", rfp_date=date(2026, 9, 10), payee=supplier,
            segment=segment, lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "3000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "3000.00"},
            ], user=user,
        )
        # Advance through approvals (below P100k so no CNR needed)
        RFPService.advance_step(rfp, role="checked", user=h)
        RFPService.advance_step(rfp, role="acctg_approved", user=h)
        RFPService.advance_step(rfp, role="fin_approved", user=h)

        # Manually assign to CONSO batch and post
        batch = CONSOBatch.objects.create(batch_no="CONSO-2026-09", conso_date=date(2026, 9, 10), total_amount=Decimal("3000.00"))
        rfp.conso = batch
        rfp.save()
        assert rfp.conso_id is not None

        # Post the batch
        CONSOService.post_batch(rfp.conso, user=h)
        rfp.refresh_from_db()
        assert rfp.status == "posted"

        # Create CV from posted RFP
        client.force_login(user)
        resp = client.post("/ap/cv/new/", {
            "source_type": "rfp", "source_id": rfp.pk,
            "bank_account": accounts["10110"].pk,
            "cv_date": "2026-09-15", "gross_amount": "3000.00",
            "withheld_tax": "0.00", "check_no": "",
        })
        assert resp.status_code == 302
        cv = CheckVoucher.objects.get()
        assert cv.rfp_id == rfp.pk
        assert cv.status == "created"


class TestPrepareForFellowCustodian:
    """Any preparer may draft, edit and submit on a FELLOW custodian's fund;
    the stranger-out gates (neither preparer nor custodian) still refuse."""

    def test_dropdown_lists_fellow_custodians_funds(self, client, role_users, fund, fund_b):
        client.force_login(role_users["staff"])
        body = client.get("/cash/pcf/replenish/").content.decode()
        assert fund.fund_code in body
        assert "PCF-B — Fellow Fund — otherstaff" in body  # fellow fund, labelled

    def test_staff_can_draft_on_fellow_fund(self, client, role_users, fund_b, accounts, supplier):
        client.force_login(role_users["staff"])
        resp = client.post("/cash/pcf/replenish/", _form(fund_b, accounts, supplier))
        assert resp.status_code == 302
        replen = PCFReplenishment.objects.get()
        assert replen.fund_id == fund_b.pk
        assert replen.requested_by == role_users["staff"]
        assert replen.status == "draft"

    def test_fund_switch_between_fellow_funds_on_draft_edit(self, client, role_users, fund, fund_b, accounts, supplier):
        """The old 'Select one of your own petty cash funds' refusal is gone:
        a draft's fund may be re-picked across active funds."""
        client.force_login(role_users["staff"])
        replen = _create(client, fund, accounts, supplier)
        resp = client.post(
            f"/cash/pcf/replenishments/{replen.id}/edit/",
            _form(fund_b, accounts, supplier),
        )
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.fund_id == fund_b.pk
        assert replen.status == "draft"

    def test_custodian_can_edit_and_submit_a_preparers_draft(self, client, role_users, other_staff, fund_b, accounts, supplier):
        client.force_login(role_users["staff"])
        replen = _create(client, fund_b, accounts, supplier)
        client.force_login(other_staff)  # the fund's custodian
        assert client.get(f"/cash/pcf/replenishments/{replen.id}/edit/").status_code == 200
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/submit/")
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "requested"
        assert replen.requested_by == role_users["staff"]  # preparer preserved

    def test_original_preparer_can_revise_after_rejection(self, client, role_users, fund_b, accounts, supplier):
        client.force_login(role_users["staff"])
        replen = _create(client, fund_b, accounts, supplier)
        client.post(f"/cash/pcf/replenishments/{replen.id}/submit/")
        client.force_login(role_users["head"])
        client.post(f"/cash/pcf/replenishments/{replen.id}/reject/", {"note": "trim"})
        client.force_login(role_users["staff"])
        resp = client.post(
            f"/cash/pcf/replenishments/{replen.id}/revise/",
            _form(fund_b, accounts, supplier, exp_debit=["450.00"], exp_description=["Trimmed"]),
        )
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "requested"
        assert replen.fund_id == fund_b.pk

    def test_third_party_cannot_touch_proxy_draft(self, client, role_users, fund_b, accounts, supplier):
        client.force_login(role_users["staff"])
        replen = _create(client, fund_b, accounts, supplier)
        stranger = get_user_model().objects.create_user(username="nosy", password="x")
        UserProfile.objects.create(user=stranger, approval_role="staff")
        client.force_login(stranger)  # neither preparer nor the fund's custodian
        assert client.get(f"/cash/pcf/replenishments/{replen.id}/edit/").status_code == 403
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/submit/")
        assert resp.status_code == 302
        replen.refresh_from_db()
        assert replen.status == "draft"

    def test_missing_fund_renders_clean_error(self, client, role_users, fund, accounts, supplier):
        client.force_login(role_users["staff"])
        resp = client.post("/cash/pcf/replenish/", {**_form(fund, accounts, supplier), "fund": ""})
        assert resp.status_code == 200
        assert "Select a petty cash fund" in resp.content.decode()
        assert PCFReplenishment.objects.count() == 0
