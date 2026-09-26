"""ScreenAccessMiddleware enforcement (ADR-047 phases 1-2).

Hidden means denied: every UI surface (pages, HTMX fragments, exports, print)
and the DRF API must return 403 for screens outside the user's effective set,
while role templates keep the status quo for staff/head.
"""

import pytest
from django.contrib.auth import get_user_model

from apps.foundation.models import UserProfile

User = get_user_model()
pytestmark = pytest.mark.django_db


def _user(username, role="staff", grants=None, superuser=False):
    u = User.objects.create_user(username, password="x", is_superuser=superuser)
    UserProfile.objects.create(user=u, approval_role=role, screen_access=grants)
    return u


def test_staff_role_template_keeps_work_access_and_denies_settings(client):
    client.force_login(_user("st"))
    assert client.get("/journal/").status_code == 200
    assert client.get("/ap/rfps/").status_code == 200
    assert client.get("/settings/users/").status_code == 403


def test_head_template_allows_everything(client):
    client.force_login(_user("hd", role="head"))
    assert client.get("/ap/cv/").status_code == 200
    assert client.get("/settings/users/").status_code == 200
    assert client.get("/foundation/coa/print/").status_code == 200


def test_coo_default_dashboard_and_inbox_only(client):
    coo = _user("co", role="coo")
    client.force_login(coo)
    assert client.get("/").status_code == 200
    assert client.get("/approvals/").status_code == 200
    for path in ("/ap/rfps/", "/journal/", "/ar/invoices/", "/cash/banks/",
                 "/ap/rfps/1/", "/foundation/coa/"):
        resp = client.get(path)
        assert resp.status_code == 403, path
        assert "Not on your desk" in resp.content.decode()


def test_dashboard_always_reachable_even_when_custom_grants_exclude_it(client):
    client.force_login(_user("cw", grants=["cv_list"]))
    assert client.get("/").status_code == 200  # landing safety
    assert client.get("/ap/cv/").status_code == 200
    assert client.get("/journal/").status_code == 403


def test_deep_typed_urls_and_exports_denied_for_custom_set(client):
    client.force_login(_user("ap1", grants=["rfp_list"]))
    assert client.get("/ap/rfps/").status_code == 200
    assert client.get("/journal/general/").status_code == 403
    assert client.get("/foundation/coa/export/?format=csv").status_code == 403
    assert client.get("/foundation/coa/print/").status_code == 403


def test_htmx_fragment_denied(client):
    client.force_login(_user("ht", role="coo"))
    resp = client.get("/journal/", headers={"HX-Request": "true"})
    assert resp.status_code == 403


def test_approval_actions_allow_inbox_only_approver(client, db):
    """A COO without registers can still sign: the action endpoints belong to
    the my_approvals screen (service-layer role guards decide who is right)."""
    coo = _user("cnr", role="coo")
    client.force_login(coo)
    # nonexistent id -> the service/view errors with 404/redirect, NOT 403
    resp = client.post("/journal/reversal/999999/approve/")
    assert resp.status_code != 403
    resp = client.get("/ap/rfps/999999/")
    assert resp.status_code == 403


def test_api_segment_enforcement_precedes_drf(client):
    client.force_login(_user("api1", role="coo"))
    resp = client.get("/api/v1/ap/rfps/")
    assert resp.status_code == 403
    body = resp.json()
    assert "assigned access" in body["detail"]
    # shared reference endpoint is not gated by the middleware (DRF may 401/200)
    assert client.get("/api/v1/foundation/accounts/").status_code != 403


def test_superuser_bypass_everywhere(client):
    client.force_login(_user("root", role="", superuser=True))
    assert client.get("/ap/rfps/").status_code == 200
    assert client.get("/settings/users/").status_code == 200
    assert client.get("/journal/").status_code == 200


def test_anonymous_flow_untouched(client):
    assert client.get("/").status_code == 302  # to login, not 403
    assert client.get("/login/").status_code == 200


def test_profileless_legacy_user_gets_work_set(client):
    u = User.objects.create_user("legacy", password="x")
    client.force_login(u)
    assert client.get("/journal/").status_code == 200
    assert client.get("/settings/users/").status_code == 403


# ------------------------------ landing --------------------------------------


def _post_login(user):
    from django.test import Client as _C

    c = _C()
    resp = c.post("/login/", {"username": user.username, "password": "x"})
    assert resp.status_code == 302
    return resp.url


def test_role_home_mapping(db):
    assert _post_login(_user("lh", role="head")) == "/"
    assert _post_login(_user("lc", role="coo")) == "/"
    assert _post_login(_user("ls", role="staff")) == "/journal/"
    assert _post_login(_user("l0", role="")) == "/"


def test_role_home_respects_narrowed_grants(db):
    narrowed = _user("ln", role="staff", grants=["dashboard", "my_approvals", "cv_list"])
    assert _post_login(narrowed) == "/approvals/"  # no journal desk → inbox
    stripped = _user("lx", role="staff", grants=["dashboard", "cv_list"])
    assert _post_login(stripped) == "/"            # no inbox either → dashboard


def test_narrowed_users_still_reach_shared_pickers(client):
    """Prod 403 regression (Sep-2026): the CV form's RFP typeahead and the
    receipt/SI customer picker were captured by the "rfp_"/"customer_"
    prefix rules, so a narrowed preparer got Forbidden -> empty picker.
    Pickers are shared; the registers themselves stay gated."""
    u = _user("cvclerk", role="staff", grants=["dashboard", "cv_list"])
    client.force_login(u)
    assert client.get("/ap/rfp-options/").status_code == 200
    assert client.get("/foundation/customer-options/").status_code == 200
    assert client.get("/ap/rfps/").status_code == 403   # RFP register stays gated
    assert client.get("/ar/customers/").status_code == 403  # ...and Customers too
