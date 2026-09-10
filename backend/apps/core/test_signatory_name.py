"""Unit tests for printed-signature name resolution (RFP/CV signatory cells)."""

import pytest

from apps.core.approvals import signatory_name

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model()


def test_signatory_name_joins_first_and_last(user):
    u = user.objects.create_user(
        username="quibong", first_name="Elleonor", last_name="G. Quibong", password="x"
    )
    assert signatory_name(u) == "Elleonor G. Quibong"


def test_signatory_name_strips_whitespace(user):
    u = user.objects.create_user(
        username="pad", first_name="  Mary  ", last_name="  Jane  ", password="x"
    )
    assert signatory_name(u) == "Mary Jane"


def test_signatory_name_falls_back_to_first_only(user):
    u = user.objects.create_user(username="firstonly", first_name="Ruth", password="x")
    assert signatory_name(u) == "Ruth"


def test_signatory_name_falls_back_to_last_only(user):
    u = user.objects.create_user(username="lastonly", last_name="Manuel", password="x")
    assert signatory_name(u) == "Manuel"


def test_signatory_name_falls_back_to_username(user):
    u = user.objects.create_user(username="tester", password="x")
    assert signatory_name(u) == "tester"


def test_signatory_name_none_is_blank():
    assert signatory_name(None) == ""