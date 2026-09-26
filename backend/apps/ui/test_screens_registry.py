"""Screen registry guards (ADR-047).

The registry is the single source of truth for screen access, so it must be
*complete*: every UI route maps to a screen (or is deliberately public /
shared), and every effective-grants rule behaves. If a new screen or route
ships without being registered, these tests fail — enforcement can never
silently miss a surface.
"""

import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from apps.ui import screens as S

User = get_user_model()
pytestmark = pytest.mark.django_db


def _ui_url_names():
    src = (Path(__file__).parent / "urls.py").read_text(encoding="utf-8")
    return set(re.findall(r'name="([a-z0-9_]+)"', src))


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------


def test_every_screen_key_is_defined_once():
    keys = [k for k, _, _ in S.SCREENS]
    assert len(keys) == len(set(keys))
    assert set(keys) == S.SCREEN_KEYS


def test_every_nav_item_is_a_registered_screen():
    """The sidebar filter hides unknown keys — typos must fail loudly instead."""
    from apps.ui.nav import NAV_SECTIONS

    unknown = [
        item["name"]
        for sec in NAV_SECTIONS
        for item in sec["items"]
        if item["name"] not in S.SCREEN_KEYS
    ]
    assert not unknown, f"nav names missing from SCREENS: {unknown}"


def test_all_screen_labels_and_sections_resolve():
    for key, label, section in S.SCREENS:
        assert S.SCREEN_LABELS[key] == label
        assert S.SCREEN_SECTIONS[key] == section


def test_every_ui_route_is_gated_or_deliberately_public():
    """No UI url name may silently fall outside the registry."""
    unmapped = []
    for name in _ui_url_names():
        if name in S.PUBLIC_UI_URLS or name in S.SHARED_UI_URL_NAMES:
            continue
        if S.screen_for_url_name(name) is None:
            unmapped.append(name)
    assert not unmapped, f"unmapped UI routes: {sorted(unmapped)}"


def test_approval_actions_map_to_inbox():
    for name in S.APPROVAL_ACTIONS:
        assert S.screen_for_url_name(name) == "my_approvals"


def test_module_prefix_resolution_examples():
    assert S.screen_for_url_name("je_detail") == "je_list"
    assert S.screen_for_url_name("cv_export") == "cv_list"
    assert S.screen_for_url_name("pcf_replenishment_post") == "pcf_replenishment_list"
    assert S.screen_for_url_name("pcf_create") == "pcf_list"
    assert S.screen_for_url_name("assets_list_export") == "asset_list"
    assert S.screen_for_url_name("banks_export") == "bank_list"
    assert S.screen_for_url_name("month_end_close") == "month_end_close"
    assert S.screen_for_url_name("ledger_account_export") == "ledger_index"
    assert S.screen_for_url_name("ar_aging") == "ar_aging"
    assert S.screen_for_url_name("ar_receipts_export") == "receipt_list"


def test_api_registry_values_are_screens():
    for screen in S.API_RESOURCE_SCREENS.values():
        assert screen in S.SCREEN_KEYS
    # shared resources must NOT be in the gated map (mutually exclusive sets)
    assert not (S.API_SHARED_RESOURCES & set(S.API_RESOURCE_SCREENS))


def test_api_path_mapping():
    assert S.screen_for_api_path("/api/v1/ap/rfps/") == "rfp_list"
    assert S.screen_for_api_path("/api/v1/ap/rfps/7/") == "rfp_list"
    assert S.screen_for_api_path("/api/v1/cash/bank-accounts/") == "bank_list"
    assert S.screen_for_api_path("/api/v1/posting/entries/3/") == "je_list"
    assert S.screen_for_api_path("/api/v1/workflow/requests/") == "my_approvals"
    assert S.screen_for_api_path("/api/v1/foundation/accounts/") is None  # shared
    assert S.screen_for_api_path("/api/v1/auth/token/") is None
    assert S.screen_for_api_path("/api/schema/") is None
    assert S.screen_for_api_path("/journal/") is None


def test_every_registered_api_router_resource_is_known():
    """All DRF router registrations are mapped or explicitly shared."""
    import io

    names = set()
    apps_dir = Path(__file__).resolve().parents[1]  # .../backend/apps
    for f in apps_dir.glob("*/urls.py"):
        src = io.open(f, encoding="utf-8").read()
        names |= set(re.findall(r'register\("([^"]+)"', src))
    known = set(S.API_RESOURCE_SCREENS) | set(S.API_SHARED_RESOURCES)
    assert names <= known, f"unmapped API resources: {sorted(names - known)}"


# ---------------------------------------------------------------------------
# Role templates + effective grants
# ---------------------------------------------------------------------------


def _profile(user, role, grants=None):
    from apps.foundation.models import UserProfile

    return UserProfile.objects.create(user=user, approval_role=role, screen_access=grants)


def test_role_templates():
    assert S.role_template("head") == S.SCREEN_KEYS
    assert S.role_template("coo") == frozenset({"dashboard", "my_approvals"})
    assert S.role_template("staff") == S.WORK_KEYS
    assert S.role_template("") == S.WORK_KEYS


def test_effective_screens_rules(db):
    super_u = User.objects.create_user("su", password="x", is_superuser=True)
    assert S.effective_screens(super_u) == S.SCREEN_KEYS

    staff = User.objects.create_user("st", password="x")
    _profile(staff, "staff")
    assert S.effective_screens(staff) == S.WORK_KEYS

    head = User.objects.create_user("hd", password="x")
    _profile(head, "head")
    assert S.effective_screens(head) == S.SCREEN_KEYS

    coo = User.objects.create_user("co", password="x")
    _profile(coo, "coo")
    assert S.effective_screens(coo) == frozenset({"dashboard", "my_approvals"})

    # explicit grants: dashboard always kept, unknown keys dropped
    weird = User.objects.create_user("w", password="x")
    _profile(weird, "staff", ["cv_list", "not_a_screen", "x"])
    assert S.effective_screens(weird) == frozenset({"dashboard", "cv_list"})

    # no profile at all (edge) -> unassigned template + dashboard
    bare = User.objects.create_user("bare", password="x")
    assert "cv_list" in S.effective_screens(bare)


def test_can_edit_grants_matrix(db):
    su = User.objects.create_user("s1", password="x", is_superuser=True)
    head = User.objects.create_user("h1", password="x")
    _profile(head, "head")
    head2 = User.objects.create_user("h2", password="x")
    _profile(head2, "head")
    staff = User.objects.create_user("s2", password="x")
    _profile(staff, "staff")
    other_su = User.objects.create_user("s3", password="x", is_superuser=True)

    assert S.can_edit_grants_for(su, head) is True          # superuser narrows head
    assert S.can_edit_grants_for(su, other_su) is True
    assert S.can_edit_grants_for(head, staff) is True       # head edits staff
    assert S.can_edit_grants_for(head, other_su) is False   # never superusers
    assert S.can_edit_grants_for(head, head2) is False      # no peer head edits
    assert S.can_edit_grants_for(head, head) is False       # no self-escalation
    assert S.can_edit_grants_for(staff, staff) is False     # staff edits nothing


def test_picker_endpoints_are_shared_not_gated():
    """Every *_options typeahead endpoint must resolve as shared (None).

    Pickers are not screens: CV/receipt/SI forms call them for users who may
    not own the register they read from. A url-name prefix like "rfp_" or
    "customer_" silently capturing one shipped a prod 403 (empty RFP picker
    on Check Voucher creation) - this guard makes that class impossible."""
    from django.urls import get_resolver

    from apps.ui import screens as S

    def walk(patterns, acc):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                walk(p.url_patterns, acc)
            elif getattr(p, "name", None):
                acc.append(p.name)
        return acc

    names = walk(get_resolver("apps.ui.urls").url_patterns, [])
    pickers = [n for n in names if n.endswith("_options")]
    assert pickers, "resolver walk found no option endpoints - test broken"
    for n in pickers:
        assert S.screen_for_url_name(n) is None, (
            f"{n} is gated as {S.screen_for_url_name(n)!r}; add it to SHARED_UI_URL_NAMES"
        )
