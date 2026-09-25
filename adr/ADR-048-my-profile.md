# ADR-048: My Profile (Self-Service Details, Password, Photo, Theme)

**Status:** Accepted
**Date:** 2026-09-25
**Deciders:** Architecture Team

**References:**
- [ADR-047: Per-User Screen Access](./ADR-047-per-user-screen-access.md) — profile is a *shared* route; screens/role stay admin-controlled
- [ADR-046: UI Redesign](./ADR-046-ui-redesign-and-executive-dashboard.md) — design tokens this theme system converts to CSS variables
- [ADR-036: UI Frontend Decision](./ADR-036-ui-frontend.md) — server-rendered; themes applied without a JS round-trip

---

## Context

There was no self-service surface at all: a user could not read their own
approval role, fix a typo in their email, or change their password without
an administrator (superadmin/Head) editing them in User Management. Staff
must never see User Management (ADR-047 already hides it), so a personal
"front door" became the missing piece. Alongside it: avatars, and a
long-standing wish for users to choose the system's overall color from a
small set of tasteful presets ("by mood"), with amounts and status colors
guaranteed readable.

## Decision

**One shared route, four sections.** `/profile/` (`ui:profile`) is registered
in `SHARED_UI_URL_NAMES` — the screen gate never blocks it, for any role or
grant set. Every signed-in user sees exactly their own account; there is no
target parameter.

- **Details:** own `first/last name` and `email`. Approval role, username
  and effective screen grants are rendered **read-only** — access decisions
  stay admin-controlled (User Management / ADR-047) so a profile page can
  never widen anyone's world.
- **Password:** Django's `PasswordChangeForm` (current password required,
  strength validators apply). `update_session_auth_hash` keeps this device
  signed in after rotation.
- **Photo:** upload is fully **local** (Pillow 12, already a dependency — no
  external/paid service at this scale): ≤2 MB, must open as an image,
  center-cropped to square and re-encoded as a 256×256 JPEG into
  `media/avatars/` (gitignored). A Remove option clears it; the sidebar then
  shows the `initials` filter fallback.
- **Theme (new field):** `UserProfile.theme` (CharField, choices) +
  `UserProfile.avatar` (ImageField). Legacy users without a profile row get
  one created on first visit.

**Theme mechanics — CSS variables, server-rendered.** `brand` and `accent`
in `tailwind.config.js` became `rgb(var(--brand-600) / <alpha-value>)`
triples, so all existing utilities (including `/opacity` modifiers) keep
working untouched. `frontend/src/input.css` carries a generated section:
`:root` defines the default Teal palette and one `html[data-theme="…"]`
block redefines only the 20 brand/accent vars per preset. `base.html`
renders `<html data-theme="{{ request.user.profile.theme|default:'teal' }}">`
so the choice **persists per user across devices and sessions with no JS** —
the profile swatches preview live (setting the attribute client-side) but
nothing is stored until Save.

**Eight presets** (light UI; dark mode deliberately out of scope):
Teal (default) · Ocean · Indigo · Plum · Sunset · Forest · Blossom (pink) ·
Crimson (red). **Only brand + accent retheme** — success emerald, danger
rose, warning amber and the stone `surface` ramp are fixed by design, so
"green means posted, red means rejected" is identical in every theme and
money/amount legibility never changes. Printed documents also never change:
`@media print` resets the variables to the neutral palette.

**Readability is enforced, not eyeballed.** Each preset's emphasis slots are
shifted one step darker (slot 600 = hue-700 …), because several mid-ramp
hues (teal-600 3.7:1, sky-600 4.1:1, orange-600 3.5:1) fail WCAG AA for
white button text. `apps/ui/test_theme_contrast.py` parses the generated CSS
blocks — the single source of truth — and asserts AA ratios (≥4.5) for the
real reading pairs (button text, link-on-white, nav-active, badge pairs),
plus full var coverage, preview-chip equality, model↔CSS↔theming.py sync,
and the print reset. A palette edit that hurts contrast breaks the build.

**Safety guard:** the localStorage form-draft autosave now *explicitly*
skips `type="password"` fields (none of the autosaved forms carried
passwords before, but the profile made the rule structural, not luck).
Profile forms are never opted into autosave. The universal action-confirm
modal (ADR-047 era) already covers Save/Change password (explicit
`data-confirm` on the password button).

## Consequences

- Staff, COO, Head and superadmin all self-serve details/password/photo/theme
  while User Management remains the only place access is ever assigned.
- The default look changes in exactly one measurable way: primary buttons
  move from `teal-600` to the AA-safe `teal-700` — recorded here and in the
  contrast test as the intended trade of aesthetics for legibility.
- Themes add no runtime cost: one rebuilt CSS file with 8 tiny var blocks;
  no JS on page load, no extra requests.
- Avatars stay on this server; at this user count no paid storage is needed
  (the original open question is closed: **skipped, not needed**).
