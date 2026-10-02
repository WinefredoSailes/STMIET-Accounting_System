"""Print chrome regression: floating UI must never appear on printouts.

The assistant chat widget (#chat-widget, fixed bottom-right) is included by
ui/base.html on every authenticated page — including all *_print.html pages,
which all extend ui/base.html. A global @media print rule in the compiled
stylesheet hides it, plus the app sidebar/header (which the reporting prints
otherwise have no print CSS for at all).

These tests pin that behavior so a stale Tailwind rebuild can't silently
reintroduce chrome that overlays printed data.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client

from apps.foundation.models import Account

pytestmark = pytest.mark.django_db


def _print_css():
    css = (Path(settings.BASE_DIR) / "static" / "css" / "output.css").read_text()
    blocks = re.findall(r"@media print\{(?:[^{}]|\{[^{}]*\})*\}", css)
    assert blocks, "compiled CSS has no @media print block"
    return "\n".join(blocks)


def test_chat_widget_hidden_in_print():
    assert re.search(r"#chat-widget[^{]*\{[^}]*display:\s*none", _print_css())


def test_sidebar_and_header_hidden_in_print():
    block = _print_css()
    assert re.search(r"#sidebar[^{]*\{[^}]*display:\s*none", block)
    assert re.search(r"(?<![\w#-])header\s*\{[^}]*display:\s*none", block)


@pytest.fixture
def c(user, company, accounts):
    cl = Client()
    cl.force_login(user)
    return cl


REPORT_PRINT_URLS = [
    "/reports/trial-balance/print/",
    "/reports/is/print/",
    "/reports/sfp/print/",
    "/reports/cos/print/",
    "/reports/te/print/",
    "/reports/soce/print/",
    "/reports/ledger/print/",
]


@pytest.mark.parametrize("url", REPORT_PRINT_URLS)
def test_reporting_prints_render(c, url):
    assert c.get(url).status_code == 200, url


def test_gl_account_print_renders(c):
    acct = Account.objects.get(code="10110")
    assert c.get(f"/reports/ledger/{acct.pk}/print/").status_code == 200
