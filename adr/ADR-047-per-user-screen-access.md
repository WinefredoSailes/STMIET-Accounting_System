# ADR-047: Per-User Screen Access (Role-Based Views, Checkbox Grants, Hard Enforcement)

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Architecture Team

**References:**
- [ADR-008: Approval Hierarchy](./ADR-008-approval-hierarchy.md) — signature authority stays separate
- [ADR-020: AP Approval Matrix](./ADR-020-ap-approval-matrix.md) — wrong-role refusal is unchanged
- [ADR-036: UI Frontend Decision](./ADR-036-ui-frontend.md) — server-rendered UI + HTMX
- [ADR-043: Unified System Experience](./ADR-043-unified-system-experience.md) — one mechanism, many screens
- [ADR-046: UI Redesign](./ADR-046-ui-redesign-and-executive-dashboard.md) — nav.py config-driven sidebar

---

## Context

Every screen was visible and reachable by every signed-in user, and the
sidebar was one long list. Coming roles (AR person, AP person, CV/treasury
person, cashier, a dashboard-only COO) need each account opened where its
work is — with **real** restriction: a screen someone must not use has to be
unreachable, not merely unlinked.

Two concerns must stay decoupled:

- **`approval_role`** (staff/head/coo) — whose signature is valid. Financial
  control; unchanged by this ADR.
- **Screen access** — what a person may *open*. A UI/workspace concern.

Overloading one field with both would let a desk reassignment silently change
who can approve documents.

## Decision

### 1. One registry (`apps/ui/screens.py`)

Every module is a **screen** keyed by its primary URL name; the registry maps
all UI routes (lists, detail, create, edit, exports, print) and API resources
(`/api/v1/<section>/<resource>`) to those keys. `nav.py` drives the same keys
for the sidebar; a guard test fails CI if any route or nav item is unmapped,
so enforcement can never silently miss a surface.

Special buckets:

- **shared** — picker/option endpoints and master reference data
  (accounts, segments, fiscal calendars): any authenticated caller.
- **public** — login/logout, `/api/v1/auth/*`, schema.
- **approvals bucket** — every `*_approve / *_reject / *_clear / *_cnr /
  reversal` action belongs to the *My Approvals* screen. An approver may
  always sign what waits on them **from the inbox**, even when their desk set
  contains no registers. Wrong-role calls are still refused by the ADR-020
  service guards — this bucket grants *position*, not *identity*.

### 2. Grants live on the user, default from the role

`UserProfile.screen_access` (JSON list, **NULL = follow role template**):

| Role | Template |
|---|---|
| superuser | everything (bypass) |
| head | **every screen** — the overall approver/viewer prevails (by template, so a superuser may still narrow it deliberately) |
| staff / unassigned | every work screen except Settings/User Management |
| coo | Dashboard + My Approvals only (clean lockdown; signs from the inbox) |

Deploying this ADR changes nothing: every existing user is NULL ⇒ template ⇒
today's behaviour. It becomes real when checkboxes are used.

### 3. Enforcement is one middleware, not per-view checks

`apps.ui.middleware.ScreenAccessMiddleware` resolves every authenticated
request (UI via url name, API via path resource) to a screen and returns
**403** (JSON for `/api/`) when the user's effective set excludes it — deep
URLs, HTMX fragments, exports and print views included. Hidden = denied.

Dashboard is always allowed (landing safety). The 403 page explains access
comes from the administrator.

### 4. Assignment UI: one checkbox grid

The standalone user create/edit form carries a **Screen Access** panel:
checkboxes grouped exactly like the sidebar, "All screens / reset to role /
none" helpers, role templates pre-loaded as JSON so changing the role
re-presets the grid. A selection equal to the role template stores NULL
(keeps following it); anything else stores an explicit set.

Who may edit grants: superuser (anyone, including heads); head — any other
user **except** themselves, other heads, or superusers. No self-service
expansion.

### 5. Role-based landing

`home_url_for(user)` after login: management (superuser/head/coo) and
unassigned → Executive Dashboard; staff → their desk (`/journal/`), falling
back to the inbox then the dashboard if narrowed. Staff who want a different
home use the logo link / sidebar; a per-user home preference is a deliberate
non-goal until requested.

### 6. Inbox becomes a complete approval workstation

My Approvals rows render their queue-provided `action` as an inline
Approve/Clear button plus Reject-with-note (prompt), posting `next=/approvals/`
so the approver never leaves the queue. `_safe_next()` (same-site only) was
extended to all action endpoints; without `next` the redirect is byte-identical
to before, which keeps every existing flow unchanged.

## Consequences

- New hires start on the right screen; a departing AR person's account can be
  narrowed to their desk without touching any workflow.
- API and UI can never disagree — one registry, one resolver.
- The COO can legitimately run dashboard-only today and receive CNR items in
  the inbox the moment the escalation gate is switched on.
- Cost: one registry to keep complete — enforced by
  `test_screens_registry.py` (route/nav/API coverage) and
  `test_screen_access_enforcement.py` / `test_inbox_actions.py`, so a
  forgotten mapping fails tests rather than shipping an ungated screen.
- Head-by-template (not hard-coded bypass) means a superuser could lock out a
  head; that is a conscious admin power, surfaced by the "custom grants"
  badge on the user list.

## Non-goals

- Changing approval routing/thresholds (ADR-020 untouched).
- Hiding data *within* screens (per-row scoping) or SaaS multi-tenant gates
  (ADR-037).
- A user-editable homepage preference (landing follows role).
