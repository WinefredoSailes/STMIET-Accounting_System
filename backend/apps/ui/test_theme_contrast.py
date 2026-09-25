"""Theme palette audit (ADR-048).

Reads the [generated] preset blocks in frontend/src/input.css (single source
of truth) and enforces, for EVERY theme:

  - WCAG AA for the pairs that carry actual reading load:
      * white button text on --brand-600 / --brand-700  (btn-primary + hover)
      * --brand-600 link text on white                  (numbers, nav links)
      * --brand-700 on --brand-50                       (active nav, bubbles)
      * --accent-800 on --accent-50, --accent-700 on --accent-100 (badges)
  - structural integrity: all 8 themes exist, each defines the full 20 vars,
    UserProfile.Theme choices == theming.THEMES == CSS blocks,
    preview chips == the block's --brand-600 / --accent-500,
    :root equals the teal preset (no-JS/default render is correct),
    @media print resets variables so printed documents never inherit a
    user's hue, and the default Teal buttons are the AA-safe shifted ramp.

If someone tunes a palette by hand and it fails readability, this suite
goes red with the exact pair and ratio.
"""

import re
from pathlib import Path

import pytest

from apps.ui.theming import THEMES

INPUT_CSS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "input.css"

LABELS = ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900"]

MIN_TEXT = 4.5   # WCAG AA, normal-size text
MIN_UI = 3.0     # WCAG AA, large text / UI components


def _channel(c):
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(rgb):
    r, g, b = [_channel(v) for v in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _parse_blocks():
    css = INPUT_CSS.read_text(encoding="utf-8")
    blocks = {}
    pattern = re.compile(
        r'(html\[data-theme="([a-z]+)"\]|:root|@media print \{\nhtml\[data-theme\])\s*\{(.*?)\}',
        re.S,
    )
    for m in pattern.finditer(css):
        key = m.group(2) or ("root" if m.group(1) == ":root" else "print")
        parsed = {}
        for mm in re.finditer(r"--(brand|accent)-(\d+):\s*([\d ]+);", m.group(3), re.S):
            kind, lab, val = mm.group(1), mm.group(2), mm.group(3).split()
            parsed[f"{kind}-{lab}"] = tuple(int(x) for x in val)
        blocks[key] = parsed
    # Teal has no [data-theme] block (it is the :root default); alias it.
    blocks.setdefault("teal", blocks.get("root", {}))
    return blocks


BLOCKS = _parse_blocks()
PRESET_NAMES = sorted(k for k in BLOCKS if k not in ("root", "print"))


def test_all_eight_presets_present_and_complete():
    assert PRESET_NAMES == sorted(THEMES), f"CSS presets {PRESET_NAMES} != THEMES {sorted(THEMES)}"
    for name in PRESET_NAMES:
        b = BLOCKS[name]
        for kind in ("brand", "accent"):
            for lab in LABELS:
                assert f"{kind}-{lab}" in b, f"{name} missing --{kind}-{lab}"
        assert len(b) == 20, f"{name} has {len(b)} vars, expected 20"


def test_model_choices_match_themes():
    from apps.foundation.models import UserProfile

    assert {c[0] for c in UserProfile.Theme.choices} == set(THEMES)


def test_root_is_teal_and_print_is_neutral():
    assert BLOCKS["root"] == BLOCKS["teal"]
    assert BLOCKS["print"] == BLOCKS["teal"], "printouts must not carry user hues"


def test_default_buttons_meet_aa_after_dark_shift():
    # The ramp was shifted so button text clears AA; the default teal chip is
    # teal-700 (#0f766e), not the old teal-600 (#0d9488 = 3.7:1).
    assert BLOCKS["teal"]["brand-600"] == (15, 118, 110)


@pytest.mark.parametrize("name", sorted(THEMES))
def test_palette_contrast(name):
    b = BLOCKS[name]
    white, black = (255, 255, 255), (0, 0, 0)
    pairs = [
        ("white button on brand-600", white, b["brand-600"], MIN_TEXT),
        ("white button on brand-700 (hover)", white, b["brand-700"], MIN_TEXT),
        ("brand-600 link text on white", b["brand-600"], white, MIN_TEXT),
        ("brand-700 text on brand-50", b["brand-700"], b["brand-50"], MIN_TEXT),
        ("accent-800 text on accent-50", b["accent-800"], b["accent-50"], MIN_TEXT),
        ("accent-700 text on accent-100", b["accent-700"], b["accent-100"], MIN_TEXT),
        ("brand-600 chart series on white", b["brand-600"], white, MIN_UI),
    ]
    for label, fg, bg, floor in pairs:
        ratio = contrast(fg, bg)
        assert ratio >= floor, f"{name}: {label} = {ratio:.2f} (< {floor})"


@pytest.mark.parametrize("name", sorted(THEMES))
def test_preview_chips_match_css(name):
    b = BLOCKS[name]
    brand, accent = THEMES[name]["brand"], THEMES[name]["accent"]
    assert brand.lower() == "#%02x%02x%02x" % b["brand-600"], f"{name} brand chip drift"
    assert accent.lower() == "#%02x%02x%02x" % b["accent-500"], f"{name} accent chip drift"
