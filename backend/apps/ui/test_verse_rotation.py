"""Featured Bible verse (ESV) rotation + rendering.

The app shows a rotating verse of the week on every page footer and on the
login screen (UI convention, ADR-046 §7): 52 ESV verses, one per ISO week,
mixing stewardship/finance themes with the gospel.
"""

from datetime import date

import pytest

pytestmark = pytest.mark.django_db


def test_verse_catalog_has_a_full_year():
    from apps.ui.verses import ESV_VERSES

    assert len(ESV_VERSES) == 52
    refs = [r for r, _ in ESV_VERSES]
    assert len(set(refs)) == 52  # no duplicate references


def test_weekly_rotation_is_stable_and_wraps():
    from apps.ui.verses import ESV_VERSES, weekly_verse

    v1 = weekly_verse(today=date(2026, 1, 5))
    v2 = weekly_verse(today=date(2026, 1, 11))
    assert v1["week"] == v2["week"] == 2
    assert v1["ref"] == v2["ref"]
    # 52 weeks later, week 54/2 wraps back to the same slot (modulo behavior)
    v_week1 = weekly_verse(today=date(2026, 1, 5))
    v_week53 = weekly_verse(today=date(2026, 12, 28))
    assert v_week53["week"] in (53, 52)
    assert v_week53["ref"] == ESV_VERSES[(v_week53["week"] - 1) % 52][0]
    assert v_week1["ref"] != v_week53["ref"]  # a later week shows a different verse


def test_login_page_shows_verse(client):
    from apps.ui.verses import weekly_verse

    body = client.get("/login/").content.decode()
    verse = weekly_verse()
    assert verse["ref"] in body
    assert "ESV" in body


def test_authenticated_pages_show_verse_footer(client, user):
    from apps.ui.verses import weekly_verse

    client.force_login(user)
    verse = weekly_verse()
    for path in ("/", "/journal/", "/ap/suppliers/"):
        body = client.get(path).content.decode()
        assert verse["ref"] in body, f"verse missing on {path}"
        assert "Verse of the week" in body, f"verse footer missing on {path}"


def test_verse_attribution_is_present(client, user):
    from apps.ui.verses import ESV_ATTRIBUTION

    client.force_login(user)
    body = client.get("/").content.decode()
    assert "Crossway" in body  # attribution title rendered in the footer