import json

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from apps.assistant.services import AssistantService
from apps.assistant.models import ChatSession, ChatMessage, SearchLog

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
def service():
    return AssistantService()


class TestAssistantService:
    def test_process_query_creates_session(self, user, service):
        response = service.process_query(user, "show suppliers")
        assert "session_id" in response
        assert ChatSession.objects.filter(user=user).exists()

    def test_process_query_saves_messages(self, user, service):
        service.process_query(user, "show suppliers")
        assert ChatMessage.objects.filter(session__user=user).count() >= 2

    def test_process_query_returns_response(self, user, service):
        response = service.process_query(user, "show suppliers")
        assert "text" in response
        assert "results" in response
        assert "suggestions" in response

    def test_process_query_logs_search(self, user, service):
        service.process_query(user, "show suppliers")
        assert SearchLog.objects.filter(user=user).exists()

    def test_get_history(self, user, service):
        response = service.process_query(user, "show suppliers")
        session_id = response["session_id"]
        history = service.get_history(session_id, user)
        assert len(history) >= 2

    def test_get_greeting(self, user, service):
        greeting = service.get_greeting(user)
        assert "text" in greeting
        assert "suggestions" in greeting

    def test_multi_intent_query(self, user, service, db):
        response = service.process_query(user, "show suppliers and customers")
        assert "session_id" in response
