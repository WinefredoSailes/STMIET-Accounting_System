"""Merged audit trail on source-document detail screens.

The Finance Head reads the CV / Transfer / Billing detail page to confirm what
*actually happened* — created → posted to GL → reversed. Those events live
partly on the document's own ActionLog rows and partly on its Journal Entry
(post to GL, reversal request/approval). These tests pin the merged
doc + JE + reversal timeline on the detail screens.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.ap.models import Supplier
from apps.ap.services import CVPaymentService
from apps.cash.models import BankAccount
from apps.cash.services import TransferService
from apps.posting.services import ReversalService

pytestmark = pytest.mark.django_db


@pytest.fixture
def supplier(segment):
    return Supplier.objects.create(code="S-1", name="Payee One", default_segment=segment)


@pytest.fixture
def banks(company, segment, accounts):
    b_from = BankAccount.objects.create(
        code="1VB-CHK", name="First Valley Bank",
        account_type="checking", bank_name="First Valley Bank", bank_code="1VB",
        gl_account=accounts["10110"], company=company,
    )
    b_to = BankAccount.objects.create(
        code="MB-CHK", name="Metrobank",
        account_type="checking", bank_name="Metrobank", bank_code="MB",
        gl_account=accounts["10010"], company=company,
    )
    return b_from, b_to


@pytest.fixture
def transfer(banks, segment, role_users):
    b_from, b_to = banks
    return TransferService.transfer(
        from_account=b_from, to_account=b_to, amount="150000.00",
        purpose="Fund transfer to Metrobank", reference="REF-TRAIL",
        transfer_date="2026-09-17", segment=segment, user=role_users["staff"],
    )


@pytest.fixture
def cleared_cv(supplier, segment, accounts, role_users, segment_account_map):
    cv = CVPaymentService.create_cv(
        cv_number="CV-2026-0001",
        cv_date=date(2026, 1, 20),
        payee=supplier,
        bank_account=accounts["10110"],
        gross_amount=Decimal("100000.00"),
        withheld_tax=Decimal("0.00"),
        check_no="CHK-1",
        user=role_users["staff"],
    )
    CVPaymentService.approve(cv, user=role_users["head"])
    CVPaymentService.clear(cv, user=role_users["head"])
    return cv


class TestCvDetailTrail:
    def test_cleared_cv_shows_doc_and_je_events(self, client, cleared_cv, role_users):
        client.force_login(role_users["head"])
        body = client.get(f"/ap/cv/{cleared_cv.id}/").content.decode()
        assert "Created" in body
        assert "Approved" in body
        assert "Cleared — JE posted to GL" in body
        assert "Posted to GL (CONSO)" in body

    def test_cleared_cv_shows_reversal_chain(self, client, cleared_cv, role_users):
        request = ReversalService.request(
            cleared_cv.journal_entry, reason="Posting error — duplicate", user=role_users["staff"]
        )
        ReversalService.approve(request, user=role_users["head"])
        client.force_login(role_users["head"])
        body = client.get(f"/ap/cv/{cleared_cv.id}/").content.decode()
        assert "Reversal requested" in body
        assert "Reversal approved — reversing entry posted" in body
        assert "Posted to GL (CONSO)" in body

    def test_cv_detail_renders_without_linked_entry(self, client, supplier, segment, accounts, role_users, segment_account_map):
        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0002",
            cv_date=date(2026, 1, 21),
            payee=supplier,
            bank_account=accounts["10110"],
            gross_amount=Decimal("1000.00"),
            withheld_tax=Decimal("0.00"),
            check_no="",
            user=role_users["staff"],
        )
        client.force_login(role_users["head"])
        resp = client.get(f"/ap/cv/{cv.id}/")
        assert resp.status_code == 200
        assert "Created" in resp.content.decode()


class TestTransferDetailTrail:
    def test_approved_transfer_shows_je_posted(self, client, transfer, role_users):
        TransferService.submit(transfer, user=role_users["staff"])
        TransferService.approve(transfer, user=role_users["head"])
        client.force_login(role_users["staff"])
        body = client.get(f"/cash/transfers/{transfer.id}/").content.decode()
        assert "Approved" in body
        assert "Posted to GL (CONSO)" in body
