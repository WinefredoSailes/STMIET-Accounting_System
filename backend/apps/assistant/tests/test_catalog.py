"""Catalog spec tests — the 100-question registry must stay coherent.

Guards the contract the dispatcher relies on: every ready entry has a
routable handler behind a real screen, their own question text fires them,
the disambiguation pairs pick the right side, and no id is duplicated.
"""

from __future__ import annotations

import importlib
from datetime import date

import pytest

from apps.assistant.answers.base import ResolvedPeriod
from apps.assistant.answers.context import Entities
from apps.assistant.catalog import CATALOG, CATALOG_BY_ID, match
from apps.ui.screens import SCREEN_KEYS

EXPECTED_IDS = set(
    [f"A{n}" for n in range(1, 16)]
    + [f"B{n}" for n in range(16, 25)]
    + [f"C{n}" for n in range(25, 31)]
    + [f"D{n}" for n in range(31, 38)]
    + [f"E{n}" for n in range(38, 46)]
    + [f"F{n}" for n in range(46, 55)]
    + [f"G{n}" for n in range(55, 65)]
    + [f"H{n}" for n in range(65, 73)]
    + [f"I{n}" for n in range(73, 81)]
    + [f"J{n}" for n in range(81, 90)]
    + [f"K{n}" for n in range(90, 101)]
    + [f"L{n}" for n in range(101, 118)]
)


@pytest.fixture(autouse=True)
def dummy_period():
    """Catalog matching needs entities; give it a harmless resolved one."""
    return Entities(
        period=ResolvedPeriod(date(2026, 1, 1), date(2026, 1, 31))
    )


def test_catalog_has_exactly_117_rows_with_expected_ids():
    assert len(CATALOG) == 117
    ids = [e.qid for e in CATALOG]
    assert len(ids) == len(set(ids)), "duplicate qid in catalog"
    assert set(ids) == EXPECTED_IDS


def test_every_entry_has_phrase_and_category():
    seen_categories = set()
    for e in CATALOG:
        assert e.phrases, f"{e.qid} has no phrases"
        assert e.category in "ABCDEFGHIJKL", f"{e.qid} bad category"
        seen_categories.add(e.category)
    assert seen_categories == set("ABCDEFGHIJKL")


def test_ready_entries_have_handler_and_screen():
    for e in CATALOG:
        if e.status == "ready":
            assert e.handler, f"{e.qid} ready but no handler"
            assert e.screen in SCREEN_KEYS, f"{e.qid} screen {e.screen!r} unknown"
            module_name, _, fn_name = e.handler.partition(".")
            module = importlib.import_module(f"apps.assistant.answers.handlers.{module_name}")
            assert callable(getattr(module, fn_name, None)), f"{e.qid} handler {e.handler!r} missing"


def test_needs_stub_entries_point_at_not_tracked():
    for e in CATALOG:
        if e.status == "needs-stub":
            assert e.handler in ("stubs.not_tracked", "journal.supporting_doc"), e.qid
            assert e.stub_kind, e.qid


def test_non_routable_statuses_have_no_handler():
    for e in CATALOG:
        if e.status in ("projection", "pending-external", "write-deferred"):
            assert e.handler is None, f"{e.qid} should not route yet"


def test_ready_entries_fire_on_their_own_question_text(service_user):
    """The registered question wording must match its own entry.

    Questions phrased with "the supplier" / "the je" instead of a real name
    can't resolve a concrete entity from the wording alone, so the test
    injects a stub into the *missing* required entity slot — the point is
    that the phrases and requirement logic agree with the wording.
    """
    from apps.assistant.answers.context import resolve_entities
    from apps.assistant.parser.query_parser import QueryParser

    parser = QueryParser()
    aliases = {"E40": "E41", "E41": "E40"}  # same movement_reason handler
    for e in CATALOG:
        if e.status == "ready":
            # C26 depends on AP context ("rfp"/"payable"/"ap" or a resolved
            # supplier) to disambiguate from D32; a bare "still unpaid" is
            # deliberately AR by default (guarded by its own test).
            if e.qid == "C26":
                assert match("unpaid rfps", Entities()).qid == "C26"
                continue
            question = e.question
            parsed = parser.parse(question)
            ents = resolve_entities(service_user, parsed, question, question.lower(), [])
            _stub_missing_entities(ents, e)
            hit = match(question.lower(), ents, statuses=("ready",))
            assert hit is not None, f"{e.qid} does not fire on its own wording"
            # Same-handler aliases are intentional (A14/C28 payments,
            # E40/E41 movement reason, G61/H65/B23 journal lookup) — what
            # must not happen is a *different* handler stealing the question.
            ok_ids = {e.qid, aliases.get(e.qid, "")}
            assert (
                hit.qid in ok_ids or hit.handler == e.handler
            ), f"{e.qid} shadowed by {hit.qid} ({hit.handler})"


def _stub_missing_entities(ents, entry):
    for req in entry.requires:
        alts = req.split("|")
        if any(k == "none" or k.startswith("word:") or ents.resolved(k) for k in alts):
            continue
        if "po" in alts:
            ents.po = object()
        elif "rfp" in alts or "doc" in alts:
            ents.rfp = object()
        elif "cv" in alts:
            ents.cv = object()
        elif "je" in alts:
            ents.je = object()
        elif "supplier" in alts:
            ents.supplier = object()
        elif "customer" in alts:
            ents.customer = object()
        elif "account" in alts:
            ents.account = object()
        elif "bank" in alts:
            ents.bank = object()
        elif "advance" in alts:
            ents.advance = object()
        elif "party" in alts:
            ents.party_text = "someone"
        elif "item_text" in alts:
            ents.item_text = "x"


def test_disambiguation_overdue_ap_vs_ar():
    ents = Entities()
    assert match("which supplier payables are overdue", ents).qid == "C27"
    assert match("which receivables are overdue", ents).qid == "D35"


def test_disambiguation_approval_payment_vs_journal():
    ents = Entities()
    assert match("who approved this payment", ents) is None
    assert match("who approved the journal entry", ents) is None


def test_disambiguation_check_cleared_requires_doc():
    ents = Entities()
    # list-style stays F51 without a doc...
    assert match("which checks have cleared", ents).qid == "F51"
    # ...a specific check with a doc code goes to G60
    je = type("J", (), {"pk": 1, "entry_no": "JE-2026-0001"})()
    ents.je = je
    assert match("has the check cleared by now for JE-2026-0001", ents).qid == "G60"


def test_reports_default_and_explicit_periods():
    # "compare" needs a period word/token context (K100)
    assert match("compare this month with previous month", Entities()).qid == "K100"
    # a bare "compare" must NOT hijack
    assert match("compare the two suppliers", Entities()) is None


def test_total_cash_fires_without_entity():
    assert match("how much cash do we currently have", Entities()).qid == "F47"
    assert match("total cash balance", Entities()).qid == "F47"  # K95 alias


def test_suggestions_and_legacy_phrases_do_not_fire():
    for phrase in [
        "Top 5 suppliers by amount",
        "What are the pending CVs?",
        "Bank balance summary",
        "Journal entries last week",
        "latest cv approved",
        "any reference from limdon",
        "show all suppliers",
    ]:
        assert match(phrase.lower(), Entities()) is None, phrase


@pytest.fixture
def service_user(db):
    from django.contrib.auth import get_user_model

    from apps.foundation.models import UserProfile

    u = get_user_model().objects.create_user(username="catalog_user", password="x")
    UserProfile.objects.create(user=u, approval_role="staff")
    return u