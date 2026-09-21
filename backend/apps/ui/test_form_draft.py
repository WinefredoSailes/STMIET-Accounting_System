"""Draft-autosave opt-in tests (client-side entry preservation on Back/Cancel).

The actual save/restore runs in the browser (static/js/form-draft.js, unit
covered by `node --test` in backend/frontend/tests). These tests pin the
server-rendered contract it depends on:

  * base.html loads the draft scripts in the required order (core before
    base.js so markers can be processed; glue after extra_js so line grids
    and per-screen listeners are bound before restore dispatches events);
  * every CREATE form carries data-autosave (and data-autosave-user);
  * EDIT/REVISE renderings of shared templates never carry it — restoring a
    stale browser draft over a live record is the one thing that must not
    happen;
  * a create view that re-renders after a validation error still opts in, so
    the client-side restore can repopulate the empty grid.
"""

from pathlib import Path

import pytest
from django.test import Client
from django.template.loader import get_template

from apps.posting.models import JournalEntry, PostingStatus

pytestmark = pytest.mark.django_db

CREATE_FORMS = [
    "/journal/new/",
    "/ap/rfps/new/",
    "/ap/cv/new/",
    "/ap/pos/new/",
    "/billing/new/",
    "/cash/transfers/new/",
    "/cash/pcf/replenish/",
]

# Shared create/edit templates: the attribute must sit in the create branch.
SHARED_TEMPLATES = [
    "ui/posting/je_form.html",
    "ui/ap/rfp_form.html",
    "ui/ap/po_form.html",
    "ui/cash/transfer_form.html",
]


@pytest.fixture
def client(db, user):
    c = Client()
    c.force_login(user)
    return c


def _tpl_source(name):
    return Path(get_template(name).origin.name).read_text(encoding="utf-8")


class TestDraftScriptsLoaded:
    def test_base_html_includes_draft_scripts(self, client):
        html = client.get("/").content.decode()
        assert "form-draft-core.js" in html
        assert "form-draft.js" in html

    def test_script_order_is_race_safe(self, client):
        html = client.get("/").content.decode()
        # core -> base.js (marker processing needs StmiDraftCore)
        assert html.index("form-draft-core.js") < html.index('src="/static/js/base.js"')
        # glue last: after base.js and after any per-screen extra_js scripts
        assert html.index('src="/static/js/amount-format.js"') < html.index("js/form-draft.js")

    def test_glue_loads_after_extra_js(self, client):
        # /journal/new/ emits line-grid.js via extra_js; the glue must come
        # after it so restored rows re-run the bound totals listeners.
        html = client.get("/journal/new/").content.decode()
        assert html.index("js/line-grid.js") < html.index("js/form-draft.js")


class TestCreateFormsOptIn:
    @pytest.mark.parametrize("path", CREATE_FORMS)
    def test_create_form_opts_in(self, client, company, accounts, path):
        html = client.get(path).content.decode()
        assert "data-autosave" in html, f"{path} must opt into draft autosave"
        assert "data-autosave-user" in html, f"{path} must scope drafts per user"

    def test_cv_drafts_are_scoped_by_basis_query(self, client, company, accounts):
        html = client.get("/ap/cv/new/").content.decode()
        assert 'data-autosave-scope="query"' in html

    def test_validation_error_rerender_keeps_opt_in(self, client, company):
        # Unbalanced/empty JE re-renders the create form (200, not redirect):
        # exactly the page where the client restores the lost grid.
        resp = client.post("/journal/new/", {"transaction_date": "2026-01-05"})
        assert resp.status_code == 200
        html = resp.content.decode()
        assert "Add at least one line" in html
        assert "data-autosave" in html


class TestEditFormsNeverOptIn:
    @pytest.mark.parametrize("tpl", SHARED_TEMPLATES)
    def test_shared_template_gates_attr_on_not_editing(self, tpl):
        src = _tpl_source(tpl)
        assert "{% if not editing %} data-autosave" in src, (
            f"{tpl} must only render data-autosave on the create branch"
        )

    def test_je_edit_page_has_no_autosave(self, client, company, segment, accounts):
        resp = client.post("/journal/new/", {
            "transaction_date": "2026-01-05",
            "account": [str(accounts["10010"].id)],
            "line_segment": [str(segment.id)],
            "debit": ["100.00"],
            "credit": ["0.00"],
            "line_description": ["seed"],
            "line_cost_center": [""],
        })
        assert resp.status_code == 302
        entry = JournalEntry.objects.get()
        assert entry.status == PostingStatus.DRAFT
        html = client.get(f"/journal/{entry.id}/edit/").content.decode()
        assert "data-autosave" not in html
