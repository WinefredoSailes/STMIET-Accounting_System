"""Frontend convention guards (Phase 9) — pin the UI architecture invariants.

These tests are the executable half of the UI convention ADR (ADR-046):

  1. Navigation is driven by a single config (``apps/ui/nav.py:NAV_SECTIONS``),
     not hand-coded in templates.
  2. Every paginated list/register screen renders the shared filter bar engine
     (``ui/partials/filter_bar.html`` + ``apps.ui.filtering.FilterSpec``).
  3. Every wide table fragment renders a mobile dual-view: the desktop table is
     ``hidden md:block`` and a ``md:hidden`` stacked-card list exists, so no
     screen requires horizontal scrolling on a phone.
  4. Sidebar icons resolve: every icon name used in NAV_SECTIONS exists as an
     ``i-<name>`` symbol in ``ui/partials/icons.html``.
  5. Colours stay on palette: templates must not hardcode brand hex values.
"""

import re
from pathlib import Path

import pytest

from django.contrib.auth import get_user_model

User = get_user_model()

pytestmark = pytest.mark.django_db

BASE = Path(__file__).resolve().parent
TEMPLATES = BASE / "templates" / "ui"

# ---------------------------------------------------------------------------
# 1. Navigation single source of truth
# ---------------------------------------------------------------------------


def test_nav_sections_are_config_driven(client):
    """The sidebar must be rendered from NAV_SECTIONS by the nav_sections
    context processor — not a manually maintained link list."""
    import ast

    nav_src = (BASE / "nav.py").read_text(encoding="utf-8")
    ast.parse(nav_src)

    sidebar_src = (TEMPLATES / "_sidebar.html").read_text(encoding="utf-8")
    assert "nav_sections" in sidebar_src
    # the template must not hardcode any single nav URL
    assert "{% url 'ui:dashboard' %}" not in sidebar_src


def test_all_nav_items_resolve_to_real_urls(client, user):
    """Every NAV_SECTIONS entry must reverse to a real URL (no '#')."""
    from django.urls import NoReverseMatch, reverse

    from apps.ui.nav import NAV_SECTIONS

    for section in NAV_SECTIONS:
        if section.get("superuser_only") or section.get("roles_allowed"):
            continue  # visibility-gated sections are covered separately
        for item in section["items"]:
            try:
                url = reverse(f"ui:{item['name']}", args=item.get("args") or [])
            except NoReverseMatch:
                pytest.fail(f"nav item {item['name']!r} does not resolve")
            assert url and url != "#"


def test_all_nav_icons_exist():
    """Every icon name referenced in NAV_SECTIONS has an i-<name> symbol."""
    import re as _re

    from apps.ui.nav import NAV_SECTIONS

    icons_src = (TEMPLATES / "partials" / "icons.html").read_text(encoding="utf-8")
    defined = set(_re.findall(r'<symbol id="(i-[^"]+)"', icons_src))
    for section in NAV_SECTIONS:
        for item in section["items"]:
            assert f"i-{item['icon']}" in defined, (
                f"nav icon {item['icon']!r} missing from icons.html"
            )


def test_all_nav_icons_are_unique():
    """No two sidebar entries may share one heroicon (ADR-046 polish)."""
    from collections import Counter

    from apps.ui.nav import NAV_SECTIONS

    counts = Counter(
        item["icon"] for section in NAV_SECTIONS for item in section["items"]
    )
    dupes = sorted(k for k, v in counts.items() if v > 1)
    assert not dupes, f"duplicated nav icons: {dupes}"


# ---------------------------------------------------------------------------
# 2. Shared filter engine
# ---------------------------------------------------------------------------


def test_filter_specs_all_have_names(client):
    """Every list screen that embeds the filter bar must pair with a
    FilterSpec factory carrying at least one field."""
    from apps.ui import filter_specs

    for name in filter_specs.__all__:
        if name.endswith("_filter_spec"):
            spec = getattr(filter_specs, name)()
            assert spec.fields, f"{name}() declares no fields"


# ---------------------------------------------------------------------------
# 3. Mobile dual-view on every table fragment
# ---------------------------------------------------------------------------


def _table_fragments():
    return sorted(TEMPLATES.rglob("_*table*.html"))


def test_every_table_fragment_has_mobile_cards(client):
    """Every wide-table fragment must offer a md:hidden mobile card list."""
    fragments = _table_fragments()
    assert fragments, "expected table fragments to exist"
    for f in fragments:
        src = f.read_text(encoding="utf-8")
        # pcf funds renders a responsive card grid, no desktop table at all
        if f.name == "_pcf_table.html":
            continue
        assert "hidden md:block" in src, f"{f.name} lacks a desktop-hidden table"
        assert "md:hidden" in src, f"{f.name} lacks a mobile card list"
        assert "mobile-card" in src, f"{f.name} mobile section is empty"


def test_aging_pages_have_mobile_cards(client):
    for name in ("ar_aging.html", "ap_aging.html"):
        src = (TEMPLATES / ("ar" if name.startswith("ar") else "ap") / name).read_text(encoding="utf-8")
        assert "hidden md:block" in src
        assert "mobile-card" in src


# ---------------------------------------------------------------------------
# 4. Palette discipline
# ---------------------------------------------------------------------------


def _all_template_sources():
    for p in TEMPLATES.rglob("*.html"):
        yield p


@pytest.mark.parametrize("filename", [
    "ap/_rfp_table.html", "ap/_cv_table.html", "ar/_receipt_table.html",
    "cash/_recon_table.html", "posting/_je_table.html",
])
def test_list_fragments_have_no_raw_indigo_patches(client, filename):
    """No template may hardcode the pre-redesign indigo accent color."""
    src = (TEMPLATES / filename).read_text(encoding="utf-8")
    assert "#6366f1" not in src and "#4f46e5" not in src


# Legacy palette tokens that must never come back on UI (non-print) screens.
LEGACY_TOKENS = ("indigo-", "slate-", "blue-", "teal-", "red-", "orange-")


def test_ui_templates_use_only_theme_tokens(client):
    """Every non-print template renders from the finance-nature palette:
    brand / surface / accent / emerald / amber / rose / violet."""
    import re

    offenders = []
    for p in TEMPLATES.rglob("*.html"):
        if "_print" in p.name:
            continue
        src = p.read_text(encoding="utf-8")
        hits = [t for t in LEGACY_TOKENS if re.search(re.escape(t) + r"\d", src)]
        if hits:
            offenders.append((str(p.relative_to(TEMPLATES)), hits))
    assert not offenders, f"legacy palette tokens found: {offenders[:10]}"


def test_base_layout_uses_design_tokens(client):
    src = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "bg-surface-50" in src or "bg-surface-100" in src
    assert "brand-" in src  # the finance-nature primary palette


# ---------------------------------------------------------------------------
# 5. Config modules are importable and consistent
# ---------------------------------------------------------------------------


def test_statuses_and_nav_config_load():
    from apps.ui import nav
    from apps.ui.context_processors import nav_sections
    from apps.ui.templatetags.ui_filters import STATUS_COLOR_CLASSES

    assert nav.NAV_SECTIONS
    assert STATUS_COLOR_CLASSES
    assert callable(nav_sections)


def test_dashboard_chart_vendor_is_self_hosted(client):
    """Chart.js must be vendored (offline-safe), not CDN-loaded."""
    chart = Path(__file__).resolve().parents[2] / "static" / "js" / "vendor" / "chart.umd.min.js"
    assert chart.exists(), "chart.umd.min.js missing from static/js/vendor"
    dash = (TEMPLATES / "home" / "dashboard.html").read_text(encoding="utf-8")
    assert "vendor/chart.umd.min.js" in dash
    assert "cdn." not in dash and "jsdelivr" not in dash

def test_page_widths_are_unified():
    """All pages — lists, dashboards AND forms — run full width so large
    screens are used (responsive grids inside handle field widths). Banned
    max-w-6xl/7xl/8xl/screen*: 7xl wastes widescreen space and 8xl isn't
    even a real Tailwind class. Small caps (max-w-sm..3xl) are allowed only
    on inner text blocks like verse_footer, never on page wrappers."""
    banned = ("max-w-6xl", "max-w-7xl", "max-w-8xl", "max-w-screen")
    offenders = []
    for f in TEMPLATES.rglob("*.html"):
        body = f.read_text(encoding="utf-8")
        for token in banned:
            if token in body:
                offenders.append(f"{f.name}:{token}")
    assert not offenders, f"width caps returned: {offenders}"


def test_back_to_top_button_is_universal():
    """Every authenticated page ships the floating back-to-top control:
    markup in base.html, arrow-up sprite symbol, and the pure decision fn
    in base.js that the node tests cover."""
    from pathlib import Path

    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert 'data-back-to-top' in base
    assert "#i-arrow-up" in base
    assert "no-print" in base
    icons = (TEMPLATES / "partials" / "icons.html").read_text(encoding="utf-8")
    assert 'id="i-arrow-up"' in icons
    js = (Path(__file__).resolve().parents[2] / "static" / "js" / "base.js").read_text(encoding="utf-8")
    assert "backToTopShouldShow" in js
    assert "prefers-reduced-motion" in js
