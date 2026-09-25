"""Statement print/export robustness (prod 500 regression, Sep-2025 logs).

/reports/cos/print/ raised TypeError (raw str period reached the GL service's
`period_start - timedelta`) and /reports/cos/export/ raised
fromisoformat(date-object) whenever the toolbar links were clicked without
query params — for every one of the five statement types. The default page
also rendered its "Period:" line blank because the |date filter got strings.
"""

from datetime import date

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db

TYPES = ("is", "sfp", "cos", "te", "soce")


@pytest.fixture
def c(user, company, accounts):
    cl = Client()
    cl.force_login(user)
    return cl


@pytest.mark.parametrize("t", TYPES)
def test_print_without_params_is_200(c, t):
    resp = c.get(f"/reports/{t}/print/")
    assert resp.status_code == 200


@pytest.mark.parametrize("t", TYPES)
def test_print_renders_real_period_line(c, t):
    body = c.get(f"/reports/{t}/print/").content.decode()
    assert "Period:" in body
    # dates (not strings) through the |date filter -> month names present
    assert str(date.today().year - 1) in body


@pytest.mark.parametrize("t", TYPES)
def test_print_bad_dates_fall_back_not_500(c, t):
    for q in (
        "?period_start=junk&period_end=9999-99-99",
        "?period_start=2026-01-01",  # half a range
        "?period_end=2026-12-31",
        "?period_start=2026-13-45&period_end=2026-01-01",
    ):
        assert c.get(f"/reports/{t}/print/{q}").status_code == 200, q


@pytest.mark.parametrize("t", TYPES)
def test_export_default_xlsx_without_params(c, t):
    assert c.get(f"/reports/{t}/export/").status_code == 200


@pytest.mark.parametrize("fmt", ["xlsx", "csv", "pdf"])
def test_export_formats_with_and_without_dates(c, fmt):
    assert c.get(f"/reports/cos/export/?format={fmt}").status_code == 200
    q = f"/reports/cos/export/?format={fmt}&period_start=2026-01-01&period_end=2026-12-31"
    assert c.get(q).status_code == 200


@pytest.mark.parametrize("t", TYPES)
def test_export_bad_dates_fall_back_not_500(c, t):
    resp = c.get(f"/reports/{t}/export/?period_start=notadate&period_end=zzz")
    assert resp.status_code == 200
