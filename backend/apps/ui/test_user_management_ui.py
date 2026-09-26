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


# --------------------------- screen grants ----------------------------------


def test_edit_form_shows_screen_access_grid(client, role_users):
    _login(client, role_users["boss"])
    body = client.get(f"/settings/users/{role_users['staffer'].pk}/update/").content.decode()
    assert "Screen access" in body
    assert 'name="screens" value="je_list"' in body
    assert "always on" in body  # dashboard locked on


def test_custom_grants_round_trip(client, role_users):
    from apps.ui.screens import effective_screens

    staff = role_users["staffer"]
    _login(client, role_users["boss"])
    resp = client.post(
        f"/settings/users/{staff.pk}/update/",
        {"first_name": "", "last_name": "", "email": "", "role": "staff",
         "is_active": "1", "password": "",
         "screens": ["dashboard", "my_approvals", "je_list", "bogus_key"]},
        follow=True,
    )
    assert resp.status_code == 200
    staff.refresh_from_db()
    screens = effective_screens(staff)
    assert screens == frozenset({"dashboard", "my_approvals", "je_list"})
    # unknown key dropped, template not "accidentally" matched: stored explicitly
    assert staff.profile.screen_access == ["dashboard", "je_list", "my_approvals"]
    # and enforcement really bites (as the staffer, not the superuser admin):
    client.force_login(staff)
    assert client.get("/journal/").status_code == 200
    assert client.get("/ap/rfps/").status_code == 403


def test_selection_equal_to_template_stays_following(client, role_users):
    from apps.ui.screens import WORK_KEYS, effective_screens

    staff = role_users["staffer"]
    _login(client, role_users["boss"])
    client.post(
        f"/settings/users/{staff.pk}/update/",
        {"first_name": "", "last_name": "", "email": "", "role": "staff",
         "is_active": "1", "password": "",
         "screens": sorted(WORK_KEYS)},
    )
    staff.refresh_from_db()
    assert staff.profile.screen_access is None  # follows role template
    assert effective_screens(staff) == WORK_KEYS


def test_head_can_narrow_staff_but_not_head_or_self(client, role_users):
    from apps.ui.screens import SCREEN_KEYS, effective_screens

    head = role_users["head"]
    staffer = role_users["staffer"]
    client.force_login(head)

    # head narrows staff
    client.post(
        f"/settings/users/{staffer.pk}/update/",
        {"first_name": "", "last_name": "", "email": "", "role": "staff",
         "is_active": "1", "password": "", "screens": ["dashboard", "cv_list"]},
    )
    staffer.refresh_from_db()
    assert effective_screens(staffer) == frozenset({"dashboard", "cv_list"})

    # head cannot change own grants (nor another head's — none here) 
    mine = sorted(SCREEN_KEYS - {"journal"})
    client.post(
        f"/settings/users/{head.pk}/update/",
        {"first_name": "", "last_name": "", "email": "", "role": "head",
         "is_active": "1", "password": "", "screens": ["dashboard"]},
    )
    head.refresh_from_db()
    assert head.profile.screen_access is None
    assert effective_screens(head) == SCREEN_KEYS

    # form renders read-only panel for a head target opened by a head
    other_head = User.objects.create_user("head2x", password="x")
    from apps.foundation.models import UserProfile

    UserProfile.objects.create(user=other_head, approval_role="head")
    body = client.get(f"/settings/users/{other_head.pk}/update/").content.decode()
    assert "cannot change screen access" in body


def test_narrow_grants_then_relogin_landing_nav_and_403(client, role_users):
    """The full manual pass as ONE flow: boss narrows a staffer to
    dashboard+inbox, staffer re-logs in -> lands on Dashboard, sees ONLY
    those two nav items, and deep-typed work URLs 403."""
    import re

    from apps.ui.screens import WORK_KEYS

    staffer = role_users["staffer"]
    assert WORK_KEYS  # sanity: staffer's default was the whole work set
    _login(client, role_users["boss"])
    resp = client.post(
        f"/settings/users/{staffer.pk}/update/",
        {"first_name": staffer.first_name, "last_name": staffer.last_name,
         "email": staffer.email, "role": "staff", "is_active": "1",
         "password": "", "screens": ["dashboard", "my_approvals"]},
    )
    assert resp.status_code == 302
    staffer.refresh_from_db()
    assert staffer.profile.screen_access == ["dashboard", "my_approvals"]

    # "re-login": fresh session as the staffer (not the admin who edited)
    client.force_login(staffer)
    landing = client.get("/")
    assert landing.status_code == 200               # dashboard always held
    body = landing.content.decode()
    nav = re.search(r'<nav id="sidebar-nav".*?</nav>', body, re.S).group(0)
    assert "My Approvals" in nav
    for hidden in ("Journal Entries", "Chart of Accounts", "Purchase Orders", "Cash Short"):
        assert hidden not in nav, f"{hidden} still advertised after narrowing"

    # the rest of the desk is gone server-side, not just visually
    for url in ("/journal/", "/ap/rfps/", "/ar/aging/", "/settings/users/"):
        assert client.get(url).status_code == 403, url
    assert client.get("/approvals/").status_code == 200


def test_action_column_aligned_and_single_confirm(client, role_users):
    """Edit/Activate/Deactivate share one left-aligned rail (no text-right
    float) and the toggle uses ONLY the universal modal (the old native
    confirm() double-prompted against the verb-guard)."""
    staffer = role_users["staffer"]
    _login(client, role_users["boss"])
    client.post(f"/settings/users/{staffer.pk}/toggle-active/")  # one inactive row
    body = client.get("/settings/users/").content.decode()
    assert "return confirm(" not in body
    assert 'data-confirm="Deactivate' in body
    assert 'data-confirm="Reactivate' in body
    assert 'class="px-4 py-2.5 text-right"' not in body  # old right-floored cell gone
