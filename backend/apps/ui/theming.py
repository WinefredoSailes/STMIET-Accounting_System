"""Theme presets (ADR-048) — display metadata for the My Profile picker.

The FULL 20-stop palettes live in the [data-theme="..."] blocks of
frontend/src/input.css (compiled into static/css/output.css) — that CSS is
the single source of truth for actual colors, applied server-side as
<html data-theme="..."> from UserProfile.theme.

This module only carries what Python needs: the valid keys (mirrored by
UserProfile.Theme), human labels, and the two chip hexes the swatch preview
shows (== the block's --brand-600 / --accent-500). test_theme_contrast.py
cross-checks the chips against the CSS vars and runs WCAG AA audits on
every preset's button/link/badge pairs, so this metadata can never silently
drift from the CSS.

Ramp rule: slots 600+ take the hue's 700/800/900/950 steps so white button
text clears 4.5:1 AA (several mid-ramp hues like teal-600/sky-600/orange-600
fail AA unshifted). Semantic colors (emerald/rose/amber/surface) NEVER
retheme — amounts and status stay identical in every preset.
"""

THEMES = {
    "teal": {"label": "Teal", "brand": "#0f766e", "accent": "#eab308"},
    "ocean": {"label": "Ocean", "brand": "#0369a1", "accent": "#f97316"},
    "indigo": {"label": "Indigo", "brand": "#4338ca", "accent": "#f59e0b"},
    "plum": {"label": "Plum", "brand": "#6d28d9", "accent": "#d946ef"},
    "sunset": {"label": "Sunset", "brand": "#c2410c", "accent": "#eab308"},
    "forest": {"label": "Forest", "brand": "#15803d", "accent": "#0ea5e9"},
    "blossom": {"label": "Blossom", "brand": "#be185d", "accent": "#f59e0b"},
    "crimson": {"label": "Crimson", "brand": "#b91c1c", "accent": "#f59e0b"},
}

DEFAULT = "teal"
