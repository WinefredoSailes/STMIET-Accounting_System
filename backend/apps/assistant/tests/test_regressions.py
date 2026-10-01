from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from apps.ap.models import CheckVoucher, RFPDocument, Supplier
from apps.assistant.models import ChatMessage, ChatSession, SearchLog
from apps.assistant.services import AssistantService
from apps.foundation.models import Account, AccountType, Company, Segment

User = get_user_model()


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="testuser", password="testpass")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(username="otheruser", password="testpass")


@pytest.fixture
def service():
    return AssistantService()


@pytest.fixture
def segment(db):
    company = Company.objects.create(code="C01", name="Test Company")
    return Segment.objects.create(code="S01", name="Test Segment", company=company)


@pytest.fixture
def bank_account(db):
    return Account.objects.create(
        code="10010", name="Cash in Bank", account_type=AccountType.ASSET
    )


@pytest.fixture
def limdon(segment):
    return Supplier.objects.create(
        code="S900", name="Limdon Sales Corporation", default_segment=segment
    )


@pytest.fixture
def rfp(segment, limdon):
    return RFPDocument.objects.create(
        ap_number="2026-00001",
        rfp_date=date.today() - timedelta(days=10),
        payee=limdon,
        particulars="Payment for tires",
        segment=segment,
        amount=Decimal("5000.00"),
        status="fin_approved",
    )


def make_cv(limdon, bank_account, status, cv_date, number):
    return CheckVoucher.objects.create(
        cv_number=number,
        cv_date=cv_date,
        payee=limdon,
        bank_account=bank_account,
        gross_amount=Decimal("1000.00"),
        net_amount=Decimal("1000.00"),
        status=status,
    )


def labels(response):
    return {g["module"] for g in response["results"] if g.get("count")}


class TestStatusVocabulary:
    """'approved'/'posted' must map to each model's real lifecycle states."""

    def test_cv_approved_matches_cleared(self, user, service, limdon, bank_account):
        make_cv(limdon, bank_account, "cleared", date.today(), "CV-2026-0001")
        make_cv(limdon, bank_account, "created", date.today(), "CV-2026-0002")

        response = service.process_query(user, "show approved cv")

        total = sum(g["count"] for g in response["results"])
        assert total == 1
        codes = [i.get("code") for g in response["results"] for i in g["items"]]
        assert codes == ["CV-2026-0001"]

    def test_rfp_approved_matches_fin_approved(self, user, service, rfp):
        response = service.process_query(user, "show approved rfp")
        total = sum(g["count"] for g in response["results"])
        assert total == 1

    def test_latest_cv_approved_returns_records(self, user, service, limdon, bank_account):
        make_cv(limdon, bank_account, "cleared", date.today(), "CV-2026-0003")
        response = service.process_query(user, "what is the latest cv approved")
        assert "No results" not in response["text"]


class TestDateFallback:
    """A date window with nothing in it falls back to the newest records."""

    def test_empty_date_window_relaxes_for_browse_query(
        self, user, service, limdon, bank_account
    ):
        # Nothing in the current month, so the window must be dropped.
        make_cv(limdon, bank_account, "cleared", date.today() - timedelta(days=90), "CV-2026-0004")

        response = service.process_query(user, "what is the latest cv approved this month")

        assert "No results" not in response["text"]
        assert response.get("date_relaxed") is True
        assert "Nothing in that date range" in response["text"]
        assert sum(g["count"] for g in response["results"]) >= 1

    def test_date_window_within_range_is_not_relaxed(
        self, user, service, limdon, bank_account
    ):
        make_cv(limdon, bank_account, "cleared", date.today(), "CV-2026-0005")
        response = service.process_query(user, "what is the latest cv approved this month")
        # Records exist in the window, so no relaxation should be advertised.
        assert response.get("date_relaxed") is False
        assert "Nothing in that date range" not in response["text"]

    def test_master_only_named_search_widens(self, user, service, limdon, rfp):
        response = service.process_query(user, "any reference from limdon?")
        assert "No results" not in response["text"]
        assert "ap" in labels(response)

    def test_unknown_named_entity_still_returns_no_results(self, user, service):
        response = service.process_query(user, "any reference from zzzzznotathing?")
        assert "No results" in response["text"]


class TestCachingAndSessions:
    def test_cache_is_scoped_per_user(self, user, other_user, service):
        first = service.process_query(user, "show suppliers")
        second = service.process_query(other_user, "show suppliers")

        assert first["session_id"] != second["session_id"]
        assert ChatSession.objects.filter(user=user).count() == 1
        assert ChatSession.objects.filter(user=other_user).count() == 1

    def test_repeat_query_still_records_history(self, user, service):
        first = service.process_query(user, "show suppliers")
        service.process_query(user, "show suppliers", session_id=first["session_id"])

        assert ChatMessage.objects.filter(session__user=user).count() == 4
        assert SearchLog.objects.filter(user=user).count() == 2

    def test_foreign_session_id_is_not_reused(self, user, other_user, service):
        mine = service.process_query(user, "show suppliers")

        response = service.process_query(other_user, "show suppliers", session_id=mine["session_id"])

        assert response["session_id"] != mine["session_id"]
        assert ChatSession.objects.filter(session_id=response["session_id"], user=other_user).exists()
        # The other user's query must not land in the original session.
        assert not ChatMessage.objects.filter(
            session__session_id=mine["session_id"], session__user=other_user
        ).exists()

    def test_history_is_not_shared_between_users(self, user, other_user, service):
        mine = service.process_query(user, "show suppliers")
        service.process_query(other_user, "show customers", session_id=mine["session_id"])

        assert service.get_history(mine["session_id"], other_user) == []
        assert len(service.get_history(mine["session_id"], user)) >= 2

    def test_recent_session_is_reused_for_same_user(self, user, service):
        first = service.process_query(user, "show suppliers")
        second = service.process_query(user, "show customers", session_id=first["session_id"])
        assert second["session_id"] == first["session_id"]


class TestFormatterContract:
    def test_response_always_has_expected_keys(self, user, service):
        response = service.process_query(user, "show suppliers")
        for key in ("text", "results", "suggestions", "language", "session_id"):
            assert key in response

    def test_search_log_records_modules(self, user, service):
        service.process_query(user, "show suppliers")
        log = SearchLog.objects.filter(user=user).latest("id")
        assert isinstance(log.detected_modules, list)
        assert log.result_count >= 0
        assert log.response_time_ms >= 0