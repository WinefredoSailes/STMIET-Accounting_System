"""UI smoke tests: every server-rendered screen renders, and the write paths
(create draft JE -> post, month-end close) behave exactly like the services.

The UI is a thin layer over the same bounded-context services the DRF API uses,
so these tests are mostly 200/redirect checks rather than business logic
re-tests.
"""

from datetime import date
from decimal import Decimal
from calendar import monthrange

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.foundation.models import Account, FiscalPeriod, FiscalYear, Segment
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(db, user):
    c = Client()
    c.force_login(user)
    return c


def _draft_entry(*, entry_no, transaction_date, lines, desc="Test entry", user=None):
    from apps.foundation.models import Company

    company = Company.objects.first()
    first = Account.objects.get(code=lines[0][0])
    segment = Segment.objects.get_or_create(
        code=first.segment, company=company, defaults={"name": first.segment}
    )[0]
    je = JournalEntry.objects.create(
        entry_no=entry_no,
        company=company,
        segment=segment,
        transaction_date=transaction_date,
        status=PostingStatus.DRAFT,
        description=desc,
        created_by=user,
    )
    for i, (code, raw) in enumerate(lines, start=1):
        amount = Decimal(raw)
        JournalEntryLine.objects.create(
            entry=je,
            line_no=i,
            account=Account.objects.get(code=code),
            debit=amount if amount >= 0 else Decimal("0.00"),
            credit=-amount if amount < 0 else Decimal("0.00"),
        )
    je.recalc_totals()
    return je


class TestAuth:
    def test_login_page_renders(self, client):
        c = Client()
        resp = c.get("/login/")
        assert resp.status_code == 200
        assert "Sign in" in resp.content.decode()

    def test_login_post_redirects_to_dashboard(self, client):
        c = Client()
        resp = c.post("/login/", {"username": "tester", "password": "x"})
        assert resp.status_code == 302
        assert resp.url == "/"

    def test_screens_require_login(self, client):
        c = Client()
        for path in ["/", "/journal/", "/reports/trial-balance/", "/ar/customers/"]:
            assert c.get(path).status_code == 302


class TestScreens:
    SCREENS = [
        "/",
        "/journal/",
        "/journal/new/",
        "/reports/trial-balance/",
        "/reports/is/",
        "/reports/sfp/",
        "/reports/cos/",
        "/reports/te/",
        "/reports/soce/",
        "/reports/month-end-close/",
        "/ar/customers/",
        "/ar/receipts/",
        "/ar/receipts/new/",
        "/ap/suppliers/",
        "/ap/suppliers/new/",
        "/ap/rfps/",
        "/ap/rfps/new/",
        "/ap/cv/",
        "/ap/cv/new/",
        "/ap/conso/",
        "/ap/conso/new/",
        "/cash/banks/",
        "/cash/banks/new/",
        "/cash/cycles/",
        "/cash/cycles/generate/",
        "/cash/pcf/",
        "/cash/pcf/new/",
        "/cash/pcf/replenish/",
        "/cash/pcf/replenishments/",
        "/cash/recon/",
        "/cash/recon/new/",
        "/cash/collections-summary/",
        "/cash/short/",
        "/cash/short/new/",
        "/cash/transfers/",
        "/ap/aging/",
        "/reports/cash-flow/",
        "/reports/fleet/fuel/",
        "/reports/tax/",
        "/reports/tax/vat/",
        "/reports/tax/wht/",
        "/reports/tax/provision/",
        "/reports/tax/calendar/",
        "/assets/",
        "/assets/new/",
    ]

    @pytest.mark.parametrize("path", SCREENS)
    def test_screen_renders(self, client, company, accounts, path):
        resp = client.get(path)
        assert resp.status_code == 200

    def test_je_detail_renders(self, client, company, accounts, fiscal_period, user):
        je = _draft_entry(entry_no="JE-0001", transaction_date=date(2026, 1, 10),
                          lines=[("10010", "1000.00"), ("20000", "-1000.00")], user=user)
        resp = client.get(f"/journal/{je.id}/")
        assert resp.status_code == 200
        assert je.entry_no in resp.content.decode()


class TestEntryWorkflow:
    def test_create_draft_via_form(self, client, company, segment, accounts, fiscal_period):
        resp = client.post("/journal/new/", {
            "company": company.id,
            "segment": segment.id,
            "transaction_date": "2026-01-15",
            "description": "UI-created entry",
            "source_doc_type": "JE",
            "account": [accounts["10010"].id, accounts["20000"].id],
            "debit": ["1000.00", ""],
            "credit": ["", "1000.00"],
            "line_description": ["Cash in", "AP"],
        })
        assert resp.status_code == 302
        je = JournalEntry.objects.first()
        assert je.entry_no == "2026-00001"
        assert je.status == PostingStatus.DRAFT
        assert je.is_balanced
        assert je.lines.count() == 2

    def test_post_draft_under_threshold(self, client, company, accounts, fiscal_period, user):
        je = _draft_entry(entry_no="JE-0002", transaction_date=date(2026, 1, 10),
                          lines=[("10010", "1000.00"), ("20000", "-1000.00")], user=user)
        resp = client.post(f"/journal/{je.id}/post/")
        assert resp.status_code == 302
        je.refresh_from_db()
        assert je.is_posted

    def test_post_over_threshold_requires_approval(self, client, company, accounts, fiscal_period, user):
        je = _draft_entry(entry_no="JE-0003", transaction_date=date(2026, 1, 10),
                          lines=[("10010", "150000.00"), ("20000", "-150000.00")], user=user)
        resp = client.post(f"/journal/{je.id}/post/")
        je.refresh_from_db()
        assert not je.is_posted  # approval gate blocked the post
        resp = client.post(f"/journal/{je.id}/post/", {"approve": "on"})
        je.refresh_from_db()
        assert je.is_posted

    def test_reverse_redirects_with_message(self, client, company, accounts, fiscal_period, user):
        je = _draft_entry(entry_no="JE-0004", transaction_date=date(2026, 1, 10),
                          lines=[("10010", "1000.00"), ("20000", "-1000.00")], user=user)
        resp = client.post(f"/journal/{je.id}/reverse/")
        assert resp.status_code == 302


class TestReporting:
    def test_trial_balance_shows_balances(self, client, company, accounts, fiscal_period, user):
        je = _draft_entry(entry_no="JE-0005", transaction_date=date(2026, 1, 10),
                          lines=[("10010", "1000.00"), ("20000", "-1000.00")], user=user)
        PostingService.post(je, user=user)
        resp = client.get("/reports/trial-balance/?as_of=2026-01-31")
        assert resp.status_code == 200
        assert "10010" in resp.content.decode()

    def test_statement_generation(self, client, company, accounts, fiscal_period, user):
        je = _draft_entry(entry_no="JE-0006", transaction_date=date(2026, 1, 10),
                          lines=[("10010", "1000.00"), ("20000", "-1000.00")], user=user)
        PostingService.post(je, user=user)
        resp = client.post("/reports/is/", {
            "period_start": "2026-01-01", "period_end": "2026-01-31",
        })
        assert resp.status_code == 200
        assert "Income Statement" in resp.content.decode()


class TestMonthEndClose:
    @pytest.fixture
    def aug_period(self, db, company):
        fy = FiscalYear.objects.create(
            company=company, code="2026", start_date="2026-01-01", end_date="2026-12-31"
        )
        today = date.today()
        last = monthrange(today.year, today.month)[1]
        return FiscalPeriod.objects.create(
            fiscal_year=fy,
            period_no=today.month,
            start_date=today.replace(day=1),
            end_date=today.replace(day=last),
        )

    def test_advance_steps_then_complete(self, client, company, accounts, aug_period):
        for step in ["accruals", "recon", "close", "appropriations"]:
            resp = client.post("/reports/month-end-close/advance/", {"step": step})
            assert resp.status_code == 302
        resp = client.post("/reports/month-end-close/complete/")
        assert resp.status_code == 302
        aug_period.refresh_from_db()
        assert aug_period.is_closed

    def test_complete_blocked_before_all_steps(self, client, company, accounts, aug_period):
        resp = client.post("/reports/month-end-close/complete/")
        aug_period.refresh_from_db()
        assert not aug_period.is_closed

    def test_page_shows_steps(self, client, company, accounts, aug_period):
        resp = client.get("/reports/month-end-close/")
        assert resp.status_code == 200
        assert "accruals" in resp.content.decode()


class TestMasterScreens:
    def test_customer_create(self, client, company, segment, accounts, user):
        from django.test import Client

        user.is_superuser = True
        user.save()
        c = Client()
        c.force_login(user)
        resp = c.post("/ar/customers/new/", {
            "code": "C001",
            "name": "DHPP Fuel Client",
            "group": "fuel",
            "segment": segment.id,
            "pricing_tier": "regular",
            "tin": "123-456-789",
            "address": "Sta. Isabel, Dipolog",
            "contact_no": "0917-000-0000",
        })
        assert resp.status_code == 302
        from apps.ar.models import Customer

        c = Customer.objects.get(code="C001")
        assert c.name == "DHPP Fuel Client"
        assert c.segment == segment

    def test_customer_update_superadmin_only(self, client, company, segment, accounts):
        from apps.ar.models import Customer

        cust = Customer.objects.create(
            code="C002", name="Client Two", group="fuel", segment=segment,
            contact_no="0000",
        )
        update = client.get(f"/ar/customers/{cust.pk}/update/")
        assert update.status_code == 403

        from django.contrib.auth import get_user_model
        from django.test import Client

        sup = get_user_model().objects.create_user(username="sup", password="x", is_superuser=True)
        c = Client()
        c.force_login(sup)
        resp = c.post(f"/ar/customers/{cust.pk}/update/", {
            "code": cust.code,
            "name": cust.name,
            "group": "fuel",
            "segment": segment.id,
            "pricing_tier": "regular",
            "contact_no": "0999-EDIT-123",
        })
        assert resp.status_code == 302
        cust.refresh_from_db()
        assert cust.contact_no == "0999-EDIT-123"


    def test_supplier_create(self, client, company, segment, accounts):
        resp = client.post("/ap/suppliers/new/", {
            "code": "S001",
            "name": "Shell Fuel Depot",
            "supplier_type": "equipment",
            "tin": "987-654-321",
            "default_segment": segment.id,
        })
        assert resp.status_code == 302
        from apps.ap.models import Supplier

        s = Supplier.objects.get(code="S001")
        assert s.default_segment == segment

    def test_bank_create(self, client, company, segment, accounts):
        resp = client.post("/cash/banks/new/", {
            "code": "BDO-1",
            "name": "BDO Checking - DHPP",
            "account_type": "checking",
            "bank_name": "BDO",
            "bank_code": "BDO",
            "gl_account": accounts["10110"].id,
            "segment": segment.id,
            "adb_required": "5000.00",
        })
        assert resp.status_code == 302
        from apps.cash.models import BankAccount

        b = BankAccount.objects.get(code="BDO-1")
        assert b.gl_account_id == accounts["10110"].id

    def test_cycle_generate(self, client, company, segment, accounts):
        resp = client.post("/cash/cycles/generate/", {
            "segment": segment.id,
            "start_date": "2026-01-06",
            "end_date": "2026-01-19",
        })
        assert resp.status_code == 302
        from apps.cash.models import WeeklyCashCycle

        cycles = list(WeeklyCashCycle.objects.order_by("cycle_start"))
        assert len(cycles) == 2
        assert cycles[0].cycle_start.isoformat() == "2026-01-06"


class TestReceiptScreen:
    def test_receipt_create_posts(self, client, company, segment, accounts, fiscal_period, user):
        from apps.ar.models import Customer

        Customer.objects.create(
            code="C001", name="Fuel Client", group="fuel", segment=segment, pricing_tier="regular"
        )
        resp = client.post("/ar/receipts/new/", {
            "customer": Customer.objects.get(code="C001").id,
            "transaction_date": "2026-01-15",
            "amount": "15000.00",
            "cash_account": accounts["10010"].id,
            "payment_method": "cash",
            "check_no": "",
        })
        assert resp.status_code == 302
        from apps.ar.models import AcknowledgmentReceipt

        receipt = AcknowledgmentReceipt.objects.get()
        assert receipt.receipt_no == "2026-00001"
        assert receipt.journal_entry_id
        assert receipt.journal_entry.is_posted


class TestRFPScreen:
    @pytest.fixture
    def supplier(self, db, company, segment, accounts):
        from apps.ap.models import Supplier

        return Supplier.objects.create(
            code="S001", name="Shell Fuel Depot", supplier_type="equipment", default_segment=segment
        )

    def test_rfp_create_documents(self, client, company, segment, accounts, supplier):
        resp = client.post("/ap/rfps/new/", {
            "payee": supplier.id,
            "segment": segment.id,
            "rfp_date": "2026-01-15",
            "purpose": "GEN-FUEL",
            "line_segment": [segment.id, segment.id],
            "line_account": ["61100", "20000"],
            "line_amount": ["50000.00", "50000.00"],
            "line_side": ["dr", "cr"],
            "line_description": ["Fuel purchase", "AP - Shell Fuel Depot"],
        })
        assert resp.status_code == 302
        from apps.ap.models import RFPDocument

        rfp = RFPDocument.objects.get()
        assert rfp.status == "prepared"
        assert rfp.amount == Decimal("50000.00")
        assert rfp.lines.count() == 2
        assert rfp.particulars == "Fuel purchase"  # mirrors the first line
        supplier.refresh_from_db()
        assert supplier.last_ap == rfp.ap_number

    def test_rfp_full_approval_chain(self, client, company, segment, accounts, fiscal_period,
                                     user, supplier):
        """prepared -> submitted -> checked -> acctg_approved -> fin_approved
        -> cnr_approved (amount > P100k). The head (Alywin) checks + approves
        acctg/fin; only the COO may sign as CNR (ADR-036)."""
        from apps.ap.models import RFPDocument
        from apps.ap.services import RFPService

        rfp = RFPService.create_rfp(
            ap_number="A0001",
            rfp_date=date(2026, 1, 15),
            payee=supplier,
            segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "150000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "150000.00"},
            ],
            user=user,
        )
        User = get_user_model()
        head = User.objects.create_user(username="head", password="x")
        coo = User.objects.create_user(username="coo", password="x")
        from apps.foundation.models import UserProfile

        for u, role in ((head, "head"), (coo, "coo")):
            UserProfile.objects.create(user=u, approval_role=role)

        resp = client.post(f"/ap/rfps/{rfp.id}/submit/")
        rfp.refresh_from_db()
        assert rfp.status == "submitted"

        client.force_login(head)
        for expected in ("checked", "acctg_approved", "fin_approved"):
            resp = client.post(f"/ap/rfps/{rfp.id}/approve/")
            rfp.refresh_from_db()
            assert rfp.status == expected

        client.force_login(coo)
        resp = client.post(f"/ap/rfps/{rfp.id}/approve-cnr/")
        rfp.refresh_from_db()
        assert rfp.status == "cnr_approved"
        assert rfp.approved_by_cnr == coo

    def test_rfp_same_user_cannot_approve(self, client, company, segment, accounts,
                                          fiscal_period, user, supplier):
        from apps.ap.models import RFPDocument
        from apps.ap.services import RFPService

        rfp = RFPService.create_rfp(
            ap_number="A0002",
            rfp_date=date(2026, 1, 15),
            payee=supplier,
            segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "30000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "30000.00"},
            ],
            user=user,
        )
        resp = client.post(f"/ap/rfps/{rfp.id}/approve/")
        rfp.refresh_from_db()
        assert rfp.status == "prepared"

    def test_rfp_approve_swaps_row_inline(self, client, company, segment, accounts,
                                          fiscal_period, user, supplier):
        """HTMX inline approval swaps the row partial in place (Phase 8b)."""
        from apps.ap.models import RFPDocument
        from apps.ap.services import RFPService

        rfp = RFPService.create_rfp(
            ap_number="A0004",
            rfp_date=date(2026, 1, 15),
            payee=supplier,
            segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "30000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "30000.00"},
            ],
            user=user,
        )
        User = get_user_model()
        head = User.objects.create_user(username="head9", password="x")
        from apps.foundation.models import UserProfile

        UserProfile.objects.create(user=head, approval_role="head")
        client.force_login(head)

        resp = client.post(f"/ap/rfps/{rfp.id}/approve/", {}, HTTP_HX_REQUEST="true")
        assert resp.status_code == 200
        assert resp.headers["HX-Trigger"]
        rfp.refresh_from_db()
        assert rfp.status == "checked"

        # Row partial reflects the advanced status badge and toast trigger.
        body = resp.content.decode()
        assert "rfp-row-" in body
        assert "Checked" in body
        assert "showToast" in resp.headers["HX-Trigger"]

        # The head acts at every step, so a next inline action is still shown.
        assert "hx-post" in body

    def test_rfp_detail_shows_timeline(self, client, company, segment, accounts, supplier, user):
        from apps.ap.models import RFPDocument
        from apps.ap.services import RFPService

        rfp = RFPService.create_rfp(
            ap_number="A0003",
            rfp_date=date(2026, 1, 15),
            payee=supplier,
            segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "30000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "30000.00"},
            ],
            user=user,
        )
        rfp = RFPDocument.objects.get()
        resp = client.get(f"/ap/rfps/{rfp.id}/")
        assert resp.status_code == 200
        assert rfp.ap_number in resp.content.decode()
        assert "Checked / Recommending" in resp.content.decode()


class TestRFPRejectCycle:
    """Approver rejects with a note; the preparer revises and resubmits
    (ADR-020 reject/revise loop)."""

    @pytest.fixture
    def supplier(self, db, company, segment, accounts):
        from apps.ap.models import Supplier

        return Supplier.objects.create(
            code="S999", name="Shell Fuel Depot", default_segment=segment
        )

    @pytest.fixture
    def staff(self, db, role_users):
        return role_users["staff"]

    def _make_rfp(self, segment, supplier, staff, ap_number):
        from apps.ap.services import RFPService

        return RFPService.create_rfp(
            ap_number=ap_number,
            rfp_date=date(2026, 1, 15),
            payee=supplier,
            segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "30000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "30000.00"},
            ],
            user=staff,
        )

    def test_reject_requires_note_and_records_it(self, client, company, segment, accounts,
                                                 supplier, role_users, staff):
        from apps.ap.models import RFPDocument

        rfp = self._make_rfp(segment, supplier, staff, "A2101")
        client.force_login(staff)
        client.post(f"/ap/rfps/{rfp.id}/submit/")

        client.force_login(role_users["head"])
        # No note -> rejected.
        resp = client.post(f"/ap/rfps/{rfp.id}/approve/")
        rfp.refresh_from_db()
        assert rfp.status == "checked"
        resp = client.post(f"/ap/rfps/{rfp.id}/reject/", {"note": ""})
        rfp.refresh_from_db()
        assert rfp.status == "checked"
        assert rfp.rejection_note == ""

        # With note -> rejected with details.
        resp = client.post(f"/ap/rfps/{rfp.id}/reject/", {"note": "Split the WHT line."})
        rfp.refresh_from_db()
        assert rfp.status == "rejected"
        assert rfp.rejection_note == "Split the WHT line."
        assert rfp.rejected_by == role_users["head"]
        assert rfp.rejected_at is not None

    def test_preparer_revises_and_resubmits(self, client, company, segment, accounts,
                                            supplier, role_users, staff):
        from apps.ap.models import RFPDocument
        from apps.ap.services import RFPService

        rfp = self._make_rfp(segment, supplier, staff, "A2102")
        client.force_login(staff)
        client.post(f"/ap/rfps/{rfp.id}/submit/")
        client.force_login(role_users["head"])
        client.post(f"/ap/rfps/{rfp.id}/reject/", {"note": "Amount too low, revise."})
        rfp.refresh_from_db()
        assert rfp.status == "rejected"

        # Non-preparer cannot revise.
        client.force_login(role_users["head"])
        resp = client.post(f"/ap/rfps/{rfp.id}/revise/", {})
        assert resp.status_code == 302

        # Preparer revises via the edit form.
        client.force_login(staff)
        resp = client.get(f"/ap/rfps/{rfp.id}/revise/")
        assert resp.status_code == 200
        resp = client.post(f"/ap/rfps/{rfp.id}/revise/", {
            "purpose": "GEN-FUEL",
            "line_segment": [segment.id, segment.id],
            "line_account": ["61100", "20000"],
            "line_amount": ["35000.00", "35000.00"],
            "line_side": ["dr", "cr"],
            "line_description": ["Fuel purchase", "AP - Shell Fuel Depot"],
        })
        rfp.refresh_from_db()
        assert rfp.status == "submitted"
        assert rfp.rejection_note == ""
        assert rfp.rejected_by is None
        assert rfp.amount == Decimal("35000.00")

        # Continues through the approval chain again.
        client.force_login(role_users["head"])
        for expected in ("checked", "acctg_approved", "fin_approved"):
            resp = client.post(f"/ap/rfps/{rfp.id}/approve/")
            rfp.refresh_from_db()
            assert rfp.status == expected

    def test_cannot_reject_posted(self, client, company, segment, accounts,
                                  supplier, role_users, staff):
        from apps.ap.models import RFPDocument
        from apps.ap.services import RFPService

        rfp = self._make_rfp(segment, supplier, staff, "A2103")
        client.force_login(staff)
        client.post(f"/ap/rfps/{rfp.id}/submit/")
        client.force_login(role_users["head"])
        for expected in ("checked", "acctg_approved", "fin_approved"):
            client.post(f"/ap/rfps/{rfp.id}/approve/")
            rfp.refresh_from_db()
        assert rfp.status == "fin_approved"
        # Fully approved below P100k: not awaiting an approval step.
        resp = client.post(f"/ap/rfps/{rfp.id}/reject/", {"note": "late change"})
        rfp.refresh_from_db()
        assert rfp.status == "fin_approved"
        assert rfp.rejection_note == ""


class TestAssetScreen:
    @pytest.fixture
    def category(self, db, accounts):
        from apps.assets.models import AssetCategory

        return AssetCategory.objects.create(
            code="MACH",
            name="Machinery & Equipment",
            useful_life_years=5,
            asset_account=accounts["10010"],
            depreciation_expense_account=accounts["61100"],
            accumulated_dep_account=accounts["10010"],
        )

    def test_asset_lifecycle(self, client, company, segment, accounts, fiscal_period,
                             user, category):
        from apps.foundation.models import SegmentAccountMap

        Account.objects.create(code="27000", name="Loans Payable - DHPP", account_type="liability")
        loss_acc = Account.objects.create(code="62000", name="Loss on Disposal", account_type="expense")
        # Data-driven segment default accounts (Phase 2): the COA slice here
        # lacks a loans/gain code, so map only the roles this test exercises.
        SegmentAccountMap.objects.create(
            segment=segment, role=SegmentAccountMap.ROLE_CASH, account=accounts["10010"]
        )
        SegmentAccountMap.objects.create(
            segment=segment, role=SegmentAccountMap.ROLE_DISPOSAL_LOSS, account=loss_acc
        )
        resp = client.post("/assets/new/", {
            "name": "Diesel Generator",
            "category": category.id,
            "segment": segment.id,
            "acquisition_date": "2026-01-15",
            "cost": "80000.00",
            "residual_value": "8000.00",
            "acquisition_fees": "0.00",
            "funding_source": "cash",
            "financed_loan_reference": "",
        })
        assert resp.status_code == 302
        from apps.assets.models import Asset

        asset = Asset.objects.get()
        assert asset.asset_no == "FA-2026-0001"
        assert asset.status == "active"
        assert asset.acquisition_journal_id
        assert asset.acquisition_journal.is_posted

        resp = client.post(f"/assets/{asset.id}/depreciate/", {"period_start": "2026-01-01"})
        asset.refresh_from_db()
        row = asset.depreciation_schedule.get()
        assert row.status == "posted"
        assert row.journal_entry.is_posted

        resp = client.post(f"/assets/{asset.id}/dispose/", {
            "disposal_date": "2026-01-20",
            "proceeds": "40000.00",
            "cash_account": accounts["10010"].id,
            "reason": "Sold",
        })
        assert resp.status_code == 302
        asset.refresh_from_db()
        assert asset.status == "disposed"
        assert asset.disposal.status == "posted"

    def test_asset_detail_shows_schedule(self, client, company, segment, accounts,
                                         fiscal_period, user, category, segment_account_map):
        from apps.assets.models import Asset
        from apps.assets.services import AssetService

        Account.objects.create(code="27000", name="Loans Payable - DHPP", account_type="liability")
        asset = AssetService.acquire(
            asset_no="FA-2026-0002",
            name="Generator",
            category=category,
            segment=segment,
            acquisition_date=date(2026, 1, 15),
            cost="80000.00",
            residual_value="8000.00",
            funding_source="cash",
            user=user,
        )
        resp = client.get(f"/assets/{asset.id}/")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "FA-2026-0002" in body
        assert "Net book value" in body
        assert "Dispose asset" in body


class TestCheckVoucherScreen:
    @pytest.fixture
    def approved_rfp(self, db, company, segment, accounts, user):
        from apps.ap.models import Supplier
        from apps.ap.services import RFPService

        supplier = Supplier.objects.create(
            code="S001", name="Shell Fuel Depot", supplier_type="equipment", default_segment=segment
        )
        rfp = RFPService.create_rfp(
            ap_number="A0001",
            rfp_date=date(2026, 1, 15),
            payee=supplier,
            segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "20000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "20000.00"},
            ],
            user=user,
        )
        rfp.status = "fin_approved"
        rfp.checked_by = user
        rfp.approved_by_acctg = user
        rfp.approved_by_fin = user
        rfp.save()
        return rfp

    def test_cv_create_posts(self, client, company, segment, accounts, fiscal_period,
                             user, approved_rfp, segment_account_map):
        resp = client.post("/ap/cv/new/", {
            "rfp": approved_rfp.id,
            "cv_date": "2026-01-16",
            "bank_account": accounts["10110"].id,
            "gross_amount": "20000.00",
            "withheld_tax": "500.00",
            "check_no": "CHK-1001",
        })
        assert resp.status_code == 302
        from apps.ap.models import CheckVoucher

        cv = CheckVoucher.objects.get()
        assert cv.cv_number == "CV-2026-0001"
        assert cv.net_amount == Decimal("19500.00")
        assert cv.status == "created"
        assert cv.journal_entry_id
        assert cv.journal_entry.is_posted
        assert cv.journal_entry.lines.count() == 3  # Dr AP | Cr Cash | Cr WHT

    def test_cv_lifecycle(self, client, company, segment, accounts, fiscal_period,
                          user, approved_rfp, role_users, segment_account_map):
        from apps.ap.models import CheckVoucher
        from apps.ap.services import CVPaymentService

        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0002",
            cv_date=date(2026, 1, 16),
            payee=approved_rfp.payee,
            bank_account=accounts["10110"],
            gross_amount="10000.00",
            rfp=approved_rfp,
            check_no="CHK-1002",
            user=user,
        )
        # release before sign is blocked
        client.force_login(role_users["staff"])
        client.post(f"/ap/cv/{cv.id}/release/")
        cv.refresh_from_db()
        assert cv.status == "created"

        # COO signs, staff (treasury, e.g. Quibs) releases, head clears (ADR-036)
        client.force_login(role_users["coo"])
        client.post(f"/ap/cv/{cv.id}/sign/")
        cv.refresh_from_db()
        assert cv.status == "signed"
        assert cv.signed_by == role_users["coo"]

        client.force_login(role_users["staff"])
        client.post(f"/ap/cv/{cv.id}/release/")
        cv.refresh_from_db()
        assert cv.status == "released"
        assert cv.released_by == role_users["staff"]

        client.force_login(role_users["head"])
        client.post(f"/ap/cv/{cv.id}/clear/")
        cv.refresh_from_db()
        assert cv.status == "cleared"

    def test_cv_detail_renders(self, client, company, segment, accounts, fiscal_period,
                               user, approved_rfp, segment_account_map):
        from apps.ap.services import CVPaymentService

        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0003",
            cv_date=date(2026, 1, 16),
            payee=approved_rfp.payee,
            bank_account=accounts["10110"],
            gross_amount="10000.00",
            rfp=approved_rfp,
            user=user,
        )
        resp = client.get(f"/ap/cv/{cv.id}/")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "CV-2026-0003" in body
        assert "ACCTG-FOR-010" in body
        assert "GROSS AMOUNT" in body


class TestPCFReplenishmentScreen:
    @pytest.fixture
    def fund(self, db, company, segment, accounts, user):
        from apps.cash.models import PettyCashFund

        return PettyCashFund.objects.create(
            fund_code="general",
            name="PCF-General",
            custodian=user,
            imprest_amount=Decimal("20000.00"),
            gl_account=accounts["10110"],
            company=company,
        )

    def test_replenish_creates(self, client, company, segment, accounts, fiscal_period,
                               user, fund):
        resp = client.post("/cash/pcf/replenish/", {
            "fund": fund.id,
            "payee_name": "ADRIANO SILVA",
            "request_date": "2026-01-15",
            "reference": "OR-1234",
            "exp_account": [accounts["61100"].id],
            "exp_segment": [segment.code],
            "exp_cost_center": ["OS"],
            "exp_amount": ["850.00"],
            "exp_description": ["PTO cable for MAW7645"],
        })
        assert resp.status_code == 302
        from apps.cash.models import PCFReplenishment

        replen = PCFReplenishment.objects.get()
        assert replen.amount == Decimal("850.00")
        assert replen.payee_name == "ADRIANO SILVA"
        assert replen.status == "requested"
        assert replen.expenses[0]["account_code"] == "61100"

    def test_replenishment_post(self, client, company, segment, accounts, fiscal_period,
                                user, fund):
        from apps.cash.models import PCFReplenishment
        from apps.cash.services import PCFService

        replen = PCFService.request_replenishment(
            fund,
            [{"account_code": "61100", "amount": "850.00", "description": "Cable"}],
            user=user,
        )
        resp = client.post(f"/cash/pcf/replenishments/{replen.id}/post/")
        replen.refresh_from_db()
        assert replen.status == "posted"
        assert replen.journal_entry_id
        assert replen.journal_entry.is_posted

    def test_replenishment_detail_renders(self, client, company, segment, accounts,
                                          fiscal_period, user, fund):
        from apps.cash.models import PCFReplenishment
        from apps.cash.services import PCFService

        replen = PCFService.request_replenishment(
            fund,
            [{"account_code": "61100", "amount": "850.00", "description": "Cable"}],
            user=user,
        )
        resp = client.get(f"/cash/pcf/replenishments/{replen.id}/")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "PETTY CASH VOUCHER" in body
        assert "ACCTG-FOR-002" in body
        assert "850.00" in body

    def test_pcf_fund_create(self, client, company, segment, accounts, user):
        resp = client.post("/cash/pcf/new/", {
            "fund_code": "maintenance",
            "name": "PCF-Maintenance",
            "custodian": user.id,
            "segment": segment.id,
            "gl_account": accounts["10010"].id,
            "imprest_amount": "20000.00",
        })
        assert resp.status_code == 302
        from apps.cash.models import PettyCashFund

        fund = PettyCashFund.objects.get(fund_code="maintenance")
        assert fund.custodian == user
        assert fund.gl_account_id == accounts["10010"].id

    def test_pcf_fund_edit(self, client, company, segment, accounts, user, fund):
        from apps.cash.models import PettyCashFund

        # Edit form prefills the existing fund.
        resp = client.get(f"/cash/pcf/{fund.id}/update/")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert fund.fund_code in body
        assert "Save changes" in body

        # Change imprest amount, custodian, and deactivate.
        other = get_user_model().objects.create_user(
            username="otherpf", password="x", first_name="Other", last_name="Custodian"
        )
        resp = client.post(f"/cash/pcf/{fund.id}/update/", {
            "fund_code": fund.fund_code,
            "name": "PCF-General (revised)",
            "custodian": other.id,
            "custodian_name": other.get_full_name(),
            "gl_account": accounts["10010"].id,
            "imprest_amount": "25000.00",
            "replenish_trigger_pct": "90",
            "is_active": "1",
        })
        assert resp.status_code == 302
        fund.refresh_from_db()
        assert fund.name == "PCF-General (revised)"
        assert fund.imprest_amount == Decimal("25000.00")
        assert fund.custodian_id == other.id
        assert fund.replenish_trigger_pct == Decimal("0.9000")
        assert fund.is_active is True

        # Deactivate via the Active checkbox off.
        resp = client.post(f"/cash/pcf/{fund.id}/update/", {
            "fund_code": fund.fund_code,
            "name": fund.name,
            "custodian": other.id,
            "gl_account": accounts["10010"].id,
            "imprest_amount": "25000.00",
            "replenish_trigger_pct": "90",
        })
        assert resp.status_code == 302
        fund.refresh_from_db()
        assert fund.is_active is False


class TestReconScreen:
    @pytest.fixture
    def cycle(self, db, company, segment, accounts):
        from apps.cash.models import WeeklyCashCycle

        return WeeklyCashCycle.objects.create(
            cycle_start="2026-01-06",
            cycle_end="2026-01-12",
            segment=segment,
        )

    @pytest.fixture
    def bank(self, db, company, segment, accounts):
        from apps.cash.models import BankAccount

        return BankAccount.objects.create(
            code="BDO-1",
            name="BDO Checking",
            account_type="checking",
            gl_account=accounts["10110"],
            company=company,
        )

    def test_recon_create(self, client, company, segment, accounts, cycle, bank):
        resp = client.post("/cash/recon/new/", {
            "cycle": cycle.id,
            "bank_account": bank.id,
            "bank_statement_balance": "45000.00",
        })
        assert resp.status_code == 302
        from apps.cash.models import BankReconciliation

        recon = BankReconciliation.objects.get()
        assert recon.book_balance == Decimal("0.00")
        assert recon.bank_statement_balance == Decimal("45000.00")
        assert recon.difference == Decimal("45000.00")
        assert recon.status == "open"

    def test_recon_resolved_when_matching(self, client, company, segment, accounts,
                                          cycle, bank, fiscal_period, user):
        from apps.cash.models import BankReconciliation
        from apps.cash.services import BankReconService

        entry = _draft_entry(entry_no="JE-0099", transaction_date=date(2026, 1, 8),
                             lines=[("10110", "45000.00"), ("20000", "-45000.00")], user=user)
        PostingService.post(entry, user=user)
        BankReconService.reconcile(cycle=cycle, bank_account=bank,
                                   bank_statement_balance="45000.00", user=user)
        recon = BankReconciliation.objects.get()
        assert recon.difference == Decimal("0.00")
        assert recon.status == "resolved"


class TestCashShortScreen:
    @pytest.fixture
    def cycle(self, db, company, segment, accounts):
        from apps.cash.models import WeeklyCashCycle

        return WeeklyCashCycle.objects.create(
            cycle_start="2026-01-06",
            cycle_end="2026-01-12",
            segment=segment,
        )

    def test_record_and_approve(self, client, company, segment, accounts, cycle, user):
        from apps.foundation.models import UserProfile

        resp = client.post("/cash/short/new/", {
            "cycle": cycle.id,
            "expected_cash": "10000.00",
            "actual_cash": "9500.00",
            "cause": "Cashier miscount",
            "cause_category": "cashier",
        })
        assert resp.status_code == 302
        from apps.cash.models import CashShortExcessWorksheet

        ws = CashShortExcessWorksheet.objects.get()
        assert ws.variance == Decimal("-500.00")
        assert ws.status == "open"

        # The head approves variances; the reporter cannot (ADR-036).
        UserProfile.objects.create(user=user, approval_role="head")
        client.post(f"/cash/short/{ws.id}/approve/")
        ws.refresh_from_db()
        assert ws.status == "approved"
        assert ws.approved_by == user


class TestCONSOScreen:
    @pytest.fixture
    def approved_rfp(self, db, company, segment, accounts, user):
        from apps.ap.models import Supplier
        from apps.ap.services import RFPService

        supplier = Supplier.objects.create(
            code="S001", name="Shell Fuel Depot", supplier_type="equipment", default_segment=segment
        )
        rfp = RFPService.create_rfp(
            ap_number="A0001",
            rfp_date=date(2026, 1, 15),
            payee=supplier,
            segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "20000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "20000.00"},
            ],
            user=user,
        )
        rfp.status = "fin_approved"
        rfp.checked_by = user
        rfp.approved_by_acctg = user
        rfp.approved_by_fin = user
        rfp.save()
        return rfp

    def test_batch_lifecycle(self, client, company, segment, accounts, fiscal_period,
                             user, approved_rfp):
        resp = client.post("/ap/conso/new/", {"conso_date": "2026-01-16"})
        assert resp.status_code == 302
        from apps.ap.models import CONSOBatch, RFPDocument

        batch = CONSOBatch.objects.get()
        assert batch.batch_no == "CONSO-2026-01"
        assert batch.status == "open"

        resp = client.post(f"/ap/conso/{batch.id}/add-rfp/", {"rfp": approved_rfp.id})
        batch.refresh_from_db()
        assert batch.rfps.count() == 1
        assert batch.total_amount == Decimal("20000.00")

        resp = client.post(f"/ap/conso/{batch.id}/post/")
        batch.refresh_from_db()
        assert batch.status == "posted"
        approved_rfp.refresh_from_db()
        assert approved_rfp.status == "posted"
        assert approved_rfp.journal_entry_id
        assert approved_rfp.journal_entry.is_posted

    def test_post_blocked_with_pending_rfp(self, client, company, segment, accounts,
                                           fiscal_period, user, approved_rfp):
        from apps.ap.models import CONSOBatch

        batch = CONSOBatch.objects.create(batch_no="CONSO-2026-02", conso_date="2026-01-16")
        client.post(f"/ap/conso/{batch.id}/add-rfp/", {"rfp": approved_rfp.id})
        approved_rfp.refresh_from_db()
        approved_rfp.status = "prepared"
        approved_rfp.save(update_fields=["status"])
        client.post(f"/ap/conso/{batch.id}/post/")
        batch.refresh_from_db()
        assert batch.status == "open"


class TestCollectionsSummaryScreen:
    @pytest.fixture
    def cycle(self, db, company, segment, accounts):
        from apps.cash.models import WeeklyCashCycle

        return WeeklyCashCycle.objects.create(
            cycle_start="2026-01-06",
            cycle_end="2026-01-12",
            segment=segment,
        )

    def test_summary_renders_per_cycle(self, client, company, segment, accounts,
                                       fiscal_period, user, cycle):
        from apps.ar.models import ARInvoice, Customer
        from apps.ar.services import CollectionService
        from apps.cash.models import BankAccount

        customer = Customer.objects.create(
            code="C001", name="MORTE FUEL-BAYLIMANGO", group="fuel",
            segment=segment, pricing_tier="regular",
        )
        BankAccount.objects.create(
            code="EW-1", name="EW Checking", account_type="checking",
            bank_name="EW Bank", bank_code="EW",
            gl_account=accounts["10110"], company=company,
        )
        invoice = ARInvoice.objects.create(
            invoice_no="SI-2026-001", customer=customer,
            transaction_date=date(2026, 1, 8), segment=segment,
            total=Decimal("15000.00"),
        )

        CollectionService.record_collection(
            receipt_no="2026-00001", customer=customer,
            transaction_date=date(2026, 1, 7), amount="10000.00",
            cash_account=accounts["10010"], payment_method="cash",
            segment=segment, user=user,
        )
        CollectionService.record_collection(
            receipt_no="2026-00002", customer=customer,
            transaction_date=date(2026, 1, 8), amount="15000.00",
            cash_account=accounts["10110"], payment_method="check",
            check_no="EW 12345", segment=segment, applied_to=invoice, user=user,
        )

        resp = client.get(f"/cash/collections-summary/?cycle={cycle.id}")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "DAILY COLLECTIONS JOURNAL ENTRIES SUMMARY" in body
        assert "MORTE FUEL-BAYLIMANGO" in body
        assert "10,000.00" in body         # cash on hand collection (comma-separated)
        assert "15,000.00" in body         # bank collection + totals
        assert "EW" in body                # bank column header
        assert "SI-2026-001" in body       # applied-invoice remark / particulars
        assert "VARIANCE" in body
        assert "TOTAL DEBITS" in body
        assert "TOTAL CREDITS" in body


class TestMyApprovals:
    """The named-person inbox (ADR-036): each position sees exactly its queue,
    approve buttons act only for the assigned role, and mistakes are loud.
    head = Alywin (checks + acctg + fin), coo = CNR above P100k only."""

    @pytest.fixture
    def supplier(self, db, company, segment, accounts):
        from apps.ap.models import Supplier

        return Supplier.objects.create(
            code="S001", name="Shell Fuel Depot", default_segment=segment
        )

    def _create(self, amount, segment, supplier, user, ap_number):
        from apps.ap.models import RFPDocument
        from apps.ap.services import RFPService

        return RFPService.create_rfp(
            ap_number=ap_number,
            rfp_date=date(2026, 1, 15),
            payee=supplier,
            segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": amount},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": amount},
            ],
            user=user,
        )

    def _approve_through(self, rfp, role_users, until):
        from apps.ap.services import RFPService

        for role in ("checked", "acctg_approved", "fin_approved"):
            RFPService.advance_step(rfp, role=role, user=role_users["head"])
            if role == until:
                return

    def test_inbox_routes_the_chain(self, client, company, segment, accounts, supplier,
                                    role_users, user):
        rfp = self._create("50000.00", segment, supplier, role_users["staff"], "A2001")

        # Prepared RFPs are not in anyone's inbox: staff must submit first.
        client.force_login(role_users["head"])
        resp = client.get("/approvals/")
        assert resp.status_code == 200
        assert b"A2001" not in resp.content

        client.force_login(role_users["staff"])
        resp = client.post(f"/ap/rfps/{rfp.id}/submit/")
        assert resp.status_code == 302
        rfp.refresh_from_db()
        assert rfp.status == "submitted"

        # The head's inbox shows the submitted RFP and approves it inline
        # three times (check -> acctg -> fin, same person, two clicks each).
        client.force_login(role_users["head"])
        resp = client.get("/approvals/")
        assert b"A2001" in resp.content
        assert b"Awaiting Accounting &amp; Finance Head" in resp.content
        resp = client.post(f"/ap/rfps/{rfp.id}/approve/")
        assert resp.status_code == 302
        rfp.refresh_from_db()
        assert rfp.status == "checked"
        assert rfp.checked_by == role_users["head"]

        resp = client.get("/approvals/")
        assert b"A2001" in resp.content
        client.post(f"/ap/rfps/{rfp.id}/approve/")
        rfp.refresh_from_db()
        assert rfp.status == "acctg_approved"
        client.post(f"/ap/rfps/{rfp.id}/approve/")
        rfp.refresh_from_db()
        assert rfp.status == "fin_approved"
        # Fully approved below P100k: out of every inbox (the bare number
        # can linger in a success message, so assert on the chip).
        resp = client.get("/approvals/")
        assert b"Awaiting Accounting &amp; Finance Head" not in resp.content
        assert b"Awaiting Accounting & Finance Head" not in resp.content

    def test_cnr_queue_only_above_100k(self, client, company, segment, accounts,
                                       supplier, role_users):
        big = self._create("150000.00", segment, supplier, role_users["staff"], "A2002")
        small = self._create("50000.00", segment, supplier, role_users["staff"], "A2003")
        for rfp in (big, small):
            self._approve_through(rfp, role_users, "fin_approved")
        assert big.status == "fin_approved" and small.status == "fin_approved"

        # Small RFP needs no CNR; the big one lands in the COO's inbox.
        client.force_login(role_users["coo"])
        body = client.get("/approvals/").content
        assert b"A2002" in body
        assert b"A2003" not in body

        client.post(f"/ap/rfps/{big.id}/approve-cnr/")
        big.refresh_from_db()
        assert big.status == "cnr_approved"
        assert big.approved_by_cnr == role_users["coo"]

    def test_wrong_role_approve_is_loud(self, client, company, segment, accounts,
                                        supplier, role_users):
        rfp = self._create("50000.00", segment, supplier, role_users["staff"], "A2004")
        self._approve_through(rfp, role_users, "checked")
        client.force_login(role_users["coo"])
        resp = client.post(f"/ap/rfps/{rfp.id}/approve/", follow=True)
        rfp.refresh_from_db()
        assert rfp.status == "checked"  # nothing moved
        assert b"Accounting &amp; Finance Head" in resp.content  # names the assignee
        assert b"was not moved" in resp.content

    def test_cv_and_cash_short_queues(self, client, company, segment, accounts,
                                      supplier, role_users, user, segment_account_map):
        from apps.ap.models import CheckVoucher, CONSOBatch
        from apps.ap.services import CVPaymentService

        rfp = self._create("20000.00", segment, supplier, role_users["staff"], "A2005")
        self._approve_through(rfp, role_users, "fin_approved")
        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0001", cv_date=date(2026, 1, 20),
            payee=supplier, bank_account=accounts["10110"],
            gross_amount="20000.00", rfp=rfp, user=user,
        )
        from apps.cash.models import CashShortExcessWorksheet, WeeklyCashCycle

        cycle = WeeklyCashCycle.objects.create(
            cycle_start="2026-01-06", cycle_end="2026-01-12", segment=segment
        )
        ws = CashShortExcessWorksheet.objects.create(
            cycle=cycle, segment=segment, expected_cash=Decimal("10000.00"),
            actual_cash=Decimal("9500.00"), variance=Decimal("-500.00"),
            cause="miscount", cause_category="cashier",
            created_by=role_users["staff"],
        )

        client.force_login(role_users["coo"])
        body = client.get("/approvals/").content
        assert b"CV-2026-0001" in body and b"Sign" in body
        client.post(f"/ap/cv/{cv.id}/sign/")
        cv.refresh_from_db()
        assert cv.status == "signed"

        client.force_login(role_users["staff"])
        body = client.get("/approvals/").content
        assert b"CV-2026-0001" in body and b"Release" in body
        client.post(f"/ap/cv/{cv.id}/release/")
        cv.refresh_from_db()
        assert cv.status == "released"

        # the open cash-short worksheet is approved by the head, who also clears the CV
        client.force_login(role_users["head"])
        body = client.get("/approvals/").content
        assert b"variance" in body and b"Clear" in body
        client.post(f"/cash/short/{ws.id}/approve/")
        client.post(f"/ap/cv/{cv.id}/clear/")
        cv.refresh_from_db()
        ws.refresh_from_db()
        assert cv.status == "cleared"
        assert ws.status == "approved"

    def test_user_without_role_has_empty_inbox(self, client, company, segment, accounts,
                                               supplier, role_users):
        rfp = self._create("50000.00", segment, supplier, role_users["staff"], "A2006")
        client.force_login(role_users["staff"])  # staff has a role but no steps
        resp = client.get("/approvals/")
        assert resp.status_code == 200
        assert b"A2006" not in resp.content
        client.force_login(get_user_model().objects.create_user(username="guest", password="x"))
        resp = client.get("/approvals/")
        assert resp.status_code == 200
        assert b"no approval role" in resp.content

    def test_sidebar_badge_shows_pending_count(self, client, company, segment, accounts,
                                               supplier, role_users):
        rfp = self._create("50000.00", segment, supplier, role_users["staff"], "A2007")
        resp = client.post(f"/ap/rfps/{rfp.id}/submit/")
        assert resp.status_code == 302
        client.force_login(role_users["head"])
        # The badge (amber pill) is rendered by the context processor on every screen.
        resp = client.get("/journal/general/")
        assert resp.status_code == 200
        assert b"My Approvals" in resp.content
        assert b"bg-amber-500" in resp.content


class TestStatementChaining:
    """Phase 8b: the UI chains the IS net profit into SFP equity and the SOCE."""

    @pytest.fixture
    def statement_fixture(self, db, company, segment, accounts, fiscal_period, user):
        from apps.foundation.models import Account

        for code, name, atype, nb in [
            ("30000", "E.Bagatua Capital - DHPP", "equity", "credit"),
            ("40000", "Sales - Fuel Hauling", "revenue", "credit"),
            ("50000", "COGS - Fuel Purchase", "expense", "debit"),
            ("61000", "Operating Expenses", "expense", "debit"),
        ]:
            Account.objects.create(
                code=code, name=name, account_type=atype, segment="DHPP", normal_balance=nb
            )

        def post(code_lines, entry_no, desc):
            je = JournalEntry.objects.create(
                entry_no=entry_no,
                company=company,
                segment=segment,
                transaction_date=date(2026, 1, 10),
                status=PostingStatus.APPROVED,
                description=desc,
                created_by=user,
            )
            for i, (code, raw) in enumerate(code_lines, start=1):
                amt = Decimal(raw)
                JournalEntryLine.objects.create(
                    entry=je,
                    line_no=i,
                    account=Account.objects.get(code=code),
                    debit=amt if amt >= 0 else Decimal("0.00"),
                    credit=-amt if amt < 0 else Decimal("0.00"),
                )
            je.recalc_totals()
            PostingService.post(je, user=user)

        post([("10010", "400000.00"), ("30000", "-400000.00")], "JE-C1", "Opening capital")
        post([("12030", "250000.00"), ("40000", "-250000.00")], "JE-C2", "Fuel sales")
        post([("50000", "150000.00"), ("20000", "-150000.00")], "JE-C3", "COGS")
        post([("61000", "25000.00"), ("20000", "-25000.00")], "JE-C4", "Operating expenses")

    def test_sfp_and_soce_carry_is_net_profit(self, company, statement_fixture, user):
        from apps.ui.services import StatementService

        is_fs = StatementService.generate(
            statement_type="is", period_start="2026-01-01", period_end="2026-01-31", user=user
        )
        net = is_fs.rows_by_key()["net_profit"]["amounts"]["GRAND"]
        assert net == "75000.00"

        sfp = StatementService.generate(
            statement_type="sfp", period_start="2026-01-01", period_end="2026-01-31", user=user
        )
        assert sfp.rows_by_key()["eq_net_profit"]["amounts"]["GRAND"] == net

        soce = StatementService.generate(
            statement_type="soce", period_start="2026-01-01", period_end="2026-01-31", user=user
        )
        assert soce.rows_by_key()["soce_net_profit"]["amounts"]["GRAND"] == net


class TestAPAgingScreen:
    @pytest.fixture
    def open_rfp(self, db, company, segment, accounts, user):
        from apps.ap.models import Supplier

        supplier = Supplier.objects.create(
            code="S001", name="Shell Fuel Depot", supplier_type="depot", default_segment=segment
        )
        from apps.ap.services import RFPService

        rfp = RFPService.create_rfp(
            ap_number="A0001",
            rfp_date=date(2026, 1, 5),
            payee=supplier,
            segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "20000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "20000.00"},
            ],
            user=user,
        )
        rfp.status = "posted"  # open payable: no clearing CV yet
        rfp.save(update_fields=["status", "updated_at"])
        return rfp, supplier

    def test_buckets_and_register(self, client, company, segment, accounts, open_rfp):
        rfp, supplier = open_rfp
        resp = client.get("/ap/aging/?as_of=2026-03-31")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "AP AGING" in body
        assert "A0001" in body
        # 1/5 -> 3/31 is 85 days: bucket 61-90, open 20,000 (money-filtered: 20,000.00).
        assert "A0001" in body
        assert "20,000.00" in body

    def test_cleared_rfp_not_open(self, client, company, segment, accounts,
                                  open_rfp, fiscal_period, user, segment_account_map):
        from apps.ap.services import CVPaymentService

        rfp, supplier = open_rfp
        CVPaymentService.create_cv(
            cv_number="CV-2026-0001",
            cv_date=date(2026, 2, 1),
            payee=supplier,
            bank_account=accounts["10110"],
            gross_amount="20000.00",
            withheld_tax="0.00",
            rfp=rfp,
            user=user,
        )
        resp = client.get("/ap/aging/?as_of=2026-03-31")
        body = resp.content.decode()
        assert "No open payables" in body


class TestFleetFuelScreen:
    @pytest.fixture
    def vehicle(self, db, company, segment, accounts):
        from apps.fleet.models import Vehicle

        v = Vehicle.objects.create(plate_no="XV-123", make_model="Isuzu NPR", segment=segment)
        return v

    def test_record_and_report(self, client, company, segment, accounts, vehicle):
        resp = client.post("/reports/fleet/fuel/", {
            "vehicle": vehicle.id,
            "logged_at": "2026-01-15",
            "liters": "120.50",
            "cost_amount": "7500.00",
            "segment": "",
            "notes": "DHPP run",
        })
        assert resp.status_code == 200
        from apps.fleet.models import FuelLog

        log = FuelLog.objects.get()
        assert log.liters == Decimal("120.50")
        assert log.cost_amount == Decimal("7500.00")

        body = client.get("/reports/fleet/fuel/").content.decode()
        assert "XV-123" in body
        assert "120.50" in body
        assert "7,500.00" in body

    def test_filter_by_segment(self, client, company, segment, accounts, vehicle):
        from apps.fleet.services import record_fuel_log

        record_fuel_log(
            vehicle=vehicle, logged_at=date(2026, 1, 15), liters="50.00",
            cost_amount="3000.00", segment=segment,
        )
        body = client.get(f"/reports/fleet/fuel/?segment={segment.code}").content.decode()
        assert "50.00" in body
        body = client.get("/reports/fleet/fuel/?segment=OPS").content.decode()
        assert "50.00" not in body


class TestHTMXPartialUpdates:
    def test_coa_filter_returns_fragment(self, client, company, accounts):
        resp = client.get(
            "/foundation/coa/?q=100&segment=&account_type=", HTTP_HX_REQUEST="true"
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "10010" in body
        # fragment only: no page chrome, no sidebar
        assert "STMIET" not in body
        assert "AP Aging" not in body

    def test_cash_short_approve_swaps_row(self, client, company, segment, accounts, user):
        from apps.cash.models import CashShortExcessWorksheet, WeeklyCashCycle
        from apps.foundation.models import UserProfile

        cycle = WeeklyCashCycle.objects.create(
            cycle_start="2026-01-06", cycle_end="2026-01-12", segment=segment
        )
        ws = CashShortExcessWorksheet.objects.create(
            cycle=cycle, segment=segment, expected_cash="10000.00",
            actual_cash="9500.00", variance="-500.00", cause="Miscount", status="open",
        )
        UserProfile.objects.create(user=user, approval_role="head")
        resp = client.post(f"/cash/short/{ws.id}/approve/", {}, HTTP_HX_REQUEST="true")
        assert resp.status_code == 200
        assert resp.headers["HX-Trigger"]
        ws.refresh_from_db()
        assert ws.status == "approved"
        assert "approved" in resp.content.decode()

    def test_cv_sign_swaps_row(self, client, company, segment, accounts, fiscal_period,
                               user, role_users, segment_account_map):
        from apps.ap.models import Supplier
        from apps.ap.services import CVPaymentService, RFPService

        supplier = Supplier.objects.create(
            code="S001", name="Shell Fuel Depot", supplier_type="equipment", default_segment=segment
        )
        rfp = RFPService.create_rfp(
            ap_number="A0001", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "10000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "10000.00"},
            ],
            user=user,
        )
        rfp.status = "fin_approved"
        rfp.checked_by = user
        rfp.approved_by_acctg = user
        rfp.approved_by_fin = user
        rfp.save()
        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0001", cv_date=date(2026, 1, 16), payee=supplier,
            bank_account=accounts["10110"], gross_amount="10000.00", withheld_tax="0.00",
            rfp=rfp, user=user,
        )
        client.force_login(role_users["coo"])
        resp = client.post(f"/ap/cv/{cv.id}/sign/", {}, HTTP_HX_REQUEST="true")
        assert resp.status_code == 200
        assert resp.headers["HX-Trigger"]
        cv.refresh_from_db()
        assert cv.status == "signed"
        assert "signed" in resp.content.decode()
