"""Guards that keep source-document JEs inside their document's approval flow.

A JE owned by a CV / RFP / Transfer / Billing / PCF / AR document is actioned
from that document's screen — never through the generic JE editor, the JE API,
or the JE approval workflow. These tests pin:

- ``entry_source_doc`` ownership detection (None for manual JEs);
- API ``post`` / ``reverse`` refusal on managed JEs (400, entry unchanged);
- ``PostEntrySerializer`` refusal on managed JEs;
- JE audit-trail logging: ``created`` (API create), ``approved`` (API approve),
  ``posted`` (every posting path incl. reversal copies).
"""

from datetime import date

import pytest
from rest_framework.test import APIClient, APIRequestFactory

from apps.ap.models import ActionLog
from apps.cash.models import BankAccount
from apps.cash.services import TransferService
from apps.core.exceptions import ValidationError as AccountingValidationError
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.serializers import JournalEntrySerializer, PostEntrySerializer
from apps.posting.services import PostingService, entry_source_doc

pytestmark = pytest.mark.django_db


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
        from_account=b_from,
        to_account=b_to,
        amount="150000.00",
        purpose="Fund transfer to Metrobank",
        reference="REF-GUARD",
        transfer_date="2026-09-17",
        segment=segment,
        user=role_users["staff"],
    )


def _manual(company, segment, fiscal_period, accounts, *, status=PostingStatus.DRAFT):
    je = JournalEntry.objects.create(
        company=company, segment=segment, fiscal_period=fiscal_period,
        transaction_date=date(2026, 1, 15), status=status, description="manual JE",
    )
    JournalEntryLine.objects.create(entry=je, line_no=1, account=accounts["10010"], debit="100.00")
    JournalEntryLine.objects.create(entry=je, line_no=2, account=accounts["20000"], credit="100.00")
    je.recalc_totals()
    return je


def _request(user):
    request = APIRequestFactory().post("/")
    request.user = user
    return request


class TestEntrySourceDoc:
    def test_manual_je_has_no_source(self, company, segment, fiscal_period, accounts):
        assert entry_source_doc(_manual(company, segment, fiscal_period, accounts)) is None

    def test_transfer_je_has_source(self, transfer):
        src = entry_source_doc(transfer.journal_entry)
        assert src is not None
        assert src["label"] == "Inter-Account Transfer"
        assert src["pk"] == transfer.id
        assert src["detail"] == "ui:transfer_detail"


class TestApiGuards:
    def test_api_post_refuses_transfer_je(self, transfer, role_users):
        api = APIClient()
        api.force_authenticate(user=role_users["head"])
        je = transfer.journal_entry
        resp = api.post(f"/api/v1/posting/entries/{je.id}/post/", {"approve": True}, format="json")
        assert resp.status_code == 400
        je.refresh_from_db()
        assert je.status == PostingStatus.DRAFT

    def test_api_reverse_refuses_transfer_je(self, transfer, role_users):
        je = transfer.journal_entry
        je.status = PostingStatus.POSTED
        je.save(update_fields=["status", "updated_at"])
        api = APIClient()
        api.force_authenticate(user=role_users["staff"])
        resp = api.post(f"/api/v1/posting/entries/{je.id}/reverse/", {"reason": "dup"}, format="json")
        assert resp.status_code == 400
        je.refresh_from_db()
        assert je.status == PostingStatus.POSTED
        assert not je.reversal_token

    def test_api_post_still_posts_manual_je(self, company, segment, fiscal_period, accounts, role_users):
        je = _manual(company, segment, fiscal_period, accounts)
        api = APIClient()
        api.force_authenticate(user=role_users["head"])
        resp = api.post(f"/api/v1/posting/entries/{je.id}/post/", {"approve": True}, format="json")
        assert resp.status_code == 200
        je.refresh_from_db()
        assert je.status == PostingStatus.POSTED

    def test_serializer_refuses_transfer_je(self, transfer, role_users):
        serializer = PostEntrySerializer(
            data={"entry": transfer.journal_entry.id, "approve": True},
            context={"request": _request(role_users["head"])},
        )
        serializer.is_valid(raise_exception=True)
        with pytest.raises(AccountingValidationError):
            serializer.save()
        transfer.journal_entry.refresh_from_db()
        assert transfer.journal_entry.status == PostingStatus.DRAFT


class TestJeAuditTrail:
    def test_post_logs_posted(self, company, segment, fiscal_period, accounts, role_users):
        je = _manual(company, segment, fiscal_period, accounts, status=PostingStatus.APPROVED)
        PostingService.post(je, user=role_users["head"])
        actions = list(
            ActionLog.objects.filter(doc_type=ActionLog.DocType.JE, doc_id=je.id)
            .values_list("action", flat=True)
        )
        assert "posted" in actions

    def test_serializer_create_logs_created(self, company, segment, accounts, role_users):
        serializer = JournalEntrySerializer(
            data={
                "company": company.id,
                "segment": segment.id,
                "transaction_date": "2026-01-15",
                "description": "API create",
                "lines": [
                    {"account": accounts["10010"].id, "debit": "100.00", "credit": "0.00", "description": "c"},
                    {"account": accounts["20000"].id, "debit": "0.00", "credit": "100.00", "description": "ap"},
                ],
            },
            context={"request": _request(role_users["staff"])},
        )
        serializer.is_valid(raise_exception=True)
        je = serializer.save()
        actions = list(
            ActionLog.objects.filter(doc_type=ActionLog.DocType.JE, doc_id=je.id)
            .values_list("action", flat=True)
        )
        assert "created" in actions

    def test_serializer_approve_logs_approved_and_posted(self, company, segment, fiscal_period, accounts, role_users):
        je = _manual(company, segment, fiscal_period, accounts, status=PostingStatus.SUBMITTED)
        serializer = PostEntrySerializer(
            data={"entry": je.id, "approve": True},
            context={"request": _request(role_users["head"])},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        actions = list(
            ActionLog.objects.filter(doc_type=ActionLog.DocType.JE, doc_id=je.id)
            .values_list("action", flat=True)
        )
        assert "approved" in actions
        assert "posted" in actions

    def test_reversal_copy_gets_posted_log(self, company, segment, fiscal_period, accounts, role_users):
        je = _manual(company, segment, fiscal_period, accounts, status=PostingStatus.APPROVED)
        PostingService.post(je, user=role_users["head"])
        from apps.posting.services import ReversalService

        request = ReversalService.request(je, reason="posting error", user=role_users["staff"])
        ReversalService.approve(request, user=role_users["head"])
        rev = request.reversal_entry
        actions = list(
            ActionLog.objects.filter(doc_type=ActionLog.DocType.JE, doc_id=rev.id)
            .values_list("action", flat=True)
        )
        assert "posted" in actions