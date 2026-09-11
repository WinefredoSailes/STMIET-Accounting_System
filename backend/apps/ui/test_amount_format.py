"""Comma-formatted amount submissions (live thousand-separator UI).

The amount inputs submit values like "50,000.00" (see static/js/amount-format.js);
every write path normalizes through apps.core.money.money, which strips commas.
These tests pin that contract: if the formatter or a write path ever stops
handling commas, the suite fails here first.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(db, user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def supplier(db, company, segment, accounts):
    from apps.ap.models import Supplier

    return Supplier.objects.create(
        code="S001", name="Shell Fuel Depot", supplier_type="equipment",
        default_segment=segment,
    )


@pytest.fixture
def approved_rfp(db, company, segment, accounts, user, supplier, segment_account_map):
    from apps.ap.models import CONSOBatch
    from apps.ap.services import CONSOService, RFPService

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
    batch = CONSOBatch.objects.create(batch_no="CONSO-2026-01", conso_date=date(2026, 1, 16))
    rfp.conso = batch
    rfp.save(update_fields=["conso", "updated_at"])
    CONSOService.post_batch(batch, user=user)
    rfp.refresh_from_db()
    return rfp


class TestCommaAmountSubmissions:
    def test_rfp_lines_accept_commas(self, client, company, segment, accounts, supplier):
        from apps.ap.models import RFPDocument

        resp = client.post("/ap/rfps/new/", {
            "payee": supplier.id,
            "segment": segment.id,
            "rfp_date": "2026-01-15",
            "purpose": "GEN-FUEL",
            "line_segment": [segment.id, segment.id],
            "line_account": ["61100", "20000"],
            "line_debit": ["50,000.00", ""],
            "line_credit": ["", "50,000.00"],
            "line_description": ["Fuel purchase", "AP - Shell"],
        })
        assert resp.status_code == 302
        assert RFPDocument.objects.get().amount == Decimal("50000.00")

    def test_cv_create_accepts_commas(self, client, company, segment, accounts,
                                      fiscal_period, user, approved_rfp,
                                      segment_account_map):
        from apps.ap.models import CheckVoucher

        resp = client.post("/ap/cv/new/", {
            "rfp": approved_rfp.id,
            "cv_date": "2026-01-16",
            "bank_account": accounts["10110"].id,
            "gross_amount": "20,000.00",
            "withheld_tax": "500.00",
            "check_no": "CHK-1001",
        })
        assert resp.status_code == 302
        cv = CheckVoucher.objects.get()
        assert cv.gross_amount == Decimal("20000.00")
        assert cv.net_amount == Decimal("19500.00")

    def test_transfer_accepts_commas(self, client, company, segment, accounts,
                                     fiscal_period, user):
        from apps.cash.models import BankAccount, InterAccountTransfer

        b1 = BankAccount.objects.create(
            code="BDO-1", name="BDO Checking", account_type="checking",
            gl_account=accounts["10110"], company=company)
        b2 = BankAccount.objects.create(
            code="BDO-2", name="BDO Savings", account_type="savings",
            gl_account=accounts["10010"], company=company)
        resp = client.post("/cash/transfers/new/", {
            "from_account": b1.id,
            "to_account": b2.id,
            "amount": "30,000.00",
            "purpose": "sweep",
            "transfer_date": "2026-01-15",
        })
        assert resp.status_code == 302
        assert InterAccountTransfer.objects.get().amount == Decimal("30000.00")
