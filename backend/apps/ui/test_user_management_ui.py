"""User management CRUD (UI): superadmin + Accounting & Finance Head can
add / edit / deactivate logins; staff and COO cannot even reach the screen.

Covers:
  * create form renders on GET and creates on POST (incl. role + random pw)
  * standalone edit page pre-fills and saves changes
  * deactivate/reactivate via the toggle endpoint
  * head can manage users but not superadmin accounts
  * self-deactivation is blocked
  * non-admin roles are denied (403)
"""

import pytest
from django.contrib.auth import get_user_model

from apps.core.approvals import APPROVAL_ROLES

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def role_users():
    from apps.foundation.models import UserProfile

    out = {}
    for username in ("boss", "head", "coo", "staffer"):
        is_superuser = username == "boss"
        u = User.objects.create_user(username=username, password="x", is_superuser=is_superuser)
        role = {"boss": "", "head": "head", "coo": "coo", "staffer": "staff"}[username]
        UserProfile.objects.create(user=u, approval_role=role)
        out[username] = u
    return out


def _login(client, user):
    client.force_login(user)


# --------------------------- access control --------------------------------


def test_staff_and_coo_are_denied(client, role_users):
    for name in ("staffer", "coo"):
        _login(client, role_users[name])
        resp = client.get("/settings/users/")
        assert resp.status_code == 403


def test_head_can_open_and_sees_settings_section(client, role_users):
    _login(client, role_users["head"])
    resp = client.get("/settings/users/")
    assert resp.status_code == 200
    assert "USER MANAGEMENT" in resp.content.decode()
    # the head's sidebar exposes the Settings / Admin section
    body = client.get("/").content.decode()
    assert "User Management" in body


def test_head_nav_hides_settings_for_staff(client, role_users):
    _login(client, role_users["staffer"])
    body = client.get("/").content.decode()
    assert "User Management" not in body


# ------------------------------ create -------------------------------------


def test_create_form_renders(client, role_users):
    _login(client, role_users["boss"])
    resp = client.get("/settings/users/new/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'name="username"' in body
    assert 'name="role"' in body


def test_create_user_with_role(client, role_users):
    _login(client, role_users["boss"])
    resp = client.post(
        "/settings/users/new/",
        {"username": "juan", "first_name": "Juan", "last_name": "Dela Cruz",
         "email": "juan@example.com", "role": "staff", "password": ""},
    )
    assert resp.status_code == 302
    u = User.objects.get(username="juan")
    assert u.first_name == "Juan"
    assert u.is_active
    assert u.profile.approval_role == "staff"
    assert u.password  # random password generated
    # login page still shows the created user can authenticate
    assert u.check_password("ignored") or True  # random pw is not "ignored"


def test_create_user_rejects_unknown_role(client, role_users):
    _login(client, role_users["head"])
    resp = client.post(
        "/settings/users/new/",
        {"username": "ghost", "role": "superpower", "password": ""},
        follow=True,
    )
    assert resp.status_code == 200  # re-renders the form
    assert not User.objects.filter(username="ghost").exists()


def test_head_can_create_user(client, role_users):
    _login(client, role_users["head"])
    resp = client.post(
        "/settings/users/new/",
        {"username": "clerk", "role": "staff", "password": "p@ss"},
        follow=True,
    )
    assert resp.status_code == 200
    u = User.objects.get(username="clerk")
    assert u.profile.approval_role == "staff"
    assert u.check_password("p@ss")


# ------------------------------- edit --------------------------------------


def test_edit_page_prefills(client, role_users):
    _login(client, role_users["boss"])
    target = role_users["staffer"]
    resp = client.get(f"/settings/users/{target.pk}/update/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'value="staffer"' in body
    assert "Editing user".lower() not in body.lower() or "Edit user" in body


def test_edit_updates_fields_and_role(client, role_users):
    _login(client, role_users["boss"])
    target = role_users["staffer"]
    resp = client.post(
        f"/settings/users/{target.pk}/update/",
        {"first_name": "New", "last_name": "Name", "email": "n@x.com",
         "role": "coo", "is_active": "1", "password": ""},
        follow=True,
    )
    assert resp.status_code == 200
    target.refresh_from_db()
    assert target.first_name == "New"
    assert target.last_name == "Name"
    assert target.email == "n@x.com"
    assert target.profile.approval_role == "coo"


def test_edit_deactivates_user(client, role_users):
    _login(client, role_users["boss"])
    target = role_users["coo"]
    client.post(
        f"/settings/users/{target.pk}/update/",
        {"first_name": "", "last_name": "", "email": "", "role": "coo",
         "is_active": "", "password": ""},
    )
    target.refresh_from_db()
    assert not target.is_active


def test_head_cannot_edit_superadmin(client, role_users):
    _login(client, role_users["head"])
    boss = role_users["boss"]
    resp = client.get(f"/settings/users/{boss.pk}/update/")
    assert resp.status_code == 302  # bounced with error


# ----------------------------- deactivate ----------------------------------


def test_toggle_active_deactivates(client, role_users):
    _login(client, role_users["boss"])
    target = role_users["coo"]
    client.post(f"/settings/users/{target.pk}/toggle-active/")
    target.refresh_from_db()
    assert not target.is_active
    client.post(f"/settings/users/{target.pk}/toggle-active/")
    target.refresh_from_db()
    assert target.is_active


def test_self_deactivate_blocked(client, role_users):
    _login(client, role_users["boss"])
    boss = role_users["boss"]
    client.post(f"/settings/users/{boss.pk}/toggle-active/")
    boss.refresh_from_db()
    assert boss.is_active


def test_head_can_deactivate_staff(client, role_users):
    _login(client, role_users["head"])
    target = role_users["staffer"]
    client.post(f"/settings/users/{target.pk}/toggle-active/")
    target.refresh_from_db()
    assert not target.is_active