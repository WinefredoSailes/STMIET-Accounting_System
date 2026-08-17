# ADR-036: Server-Rendered UI (Django Templates + HTMX + Tailwind)

**Status:** Accepted
**Date:** 2026-08-15
**Deciders:** Architecture Team

**References:**
- [ADR-009: Modular Apps](../adr/ADR-009-modular-apps.md) — the UI is a separate, view-only bounded context
- [ADR-010: Framework Decision](../adr/ADR-010-framework-decision.md) — Django remains the sole application framework
- [ADR-025: Build vs Buy](../adr/ADR-025-build-vs-buy-decision.md) — no off-the-shelf ERP fits the segment-first workflow
- [ADR-035: Financial Statements](../adr/ADR-035-financial-statements.md) — reporting screens render the Phase 8 engine output
- [UI.md](../UI.md) — operator-facing user guide for every screen

---

## Context

The Phase 2–8 backend exposes every workflow as a DRF API plus a complete
service layer (contract tests, 106 passing). The operators at STMIET work in
Django templates-style document screens (JE, AR, AP, cash cycles) — they need
a browser application, not an API client. Two options existed:

1. **SPA frontend** (Vue/React + Vite) consuming the DRF API with JWT auth.
2. **Server-rendered Django templates** with HTMX for partial updates and
   Tailwind for styling, calling the same services the API uses.

### Why not the SPA

- A second app means a second build pipeline, duplicate form validation, a
  second auth story (JWT refresh handling, 401 interceptor, token storage),
  and two deployables. The team is small and the user's priority is
  *functionality with less friction*.
- The API contract is needed anyway (external consumers, integrations), but
  forcing the internal staff app through it would duplicate every error
  branch and every state transition in JavaScript.
- Document-heavy, form-first workflows (JE line grids, RFP approval chains,
  month-end close checklists) are exactly what server-rendered forms do
  well, with no client-side state machine to keep in sync.

---

## Decision

The staff application is a **server-rendered Django UI** in a new
view-only app, `apps.ui`:

- **Templates** — Django templates under `apps/ui/templates/ui/`, served by
  `apps.ui.views`. No domain models live in this app; every mutation goes
  through the bounded-context services, exactly like the DRF API (ADR-009).
  The UI and the API therefore cannot drift.
- **HTMX** — vendored at `backend/static/js/htmx.min.js` (1.9.12) for
  progressive partial updates (list filters, inline status changes) without
  a JS framework.
- **Tailwind CSS** — a real build pipeline (not CDN) at
  `backend/frontend/` (package.json, tailwind.config.js, src/input.css);
  `npm run dev` watches templates, `npm run build` emits the minified
  `backend/static/css/output.css`.
- **Auth** — Django session auth (`login_view` / `logout_view`, built-in
  `AuthenticationForm`) for operators. The DRF API keeps its JWT endpoints
  (`api/v1/auth/token/` + `/refresh/`) for machine-to-machine consumers;
  both coexist on the same users table.
- **Routes** — `apps/ui/urls.py` is mounted at `/` in the root URLconf,
  before the API routes; all API routes stay under `api/v1/`.

### Why not an SPA for the internal app

Single deployable, one auth mechanism for humans, forms-first interaction
model, and the entire business rule surface stays in Python where the
contract tests are.

---

## Consequences

**Positive:**
- Zero duplication of business logic; UI screens are thin HTML over the
  tested service layer.
- One artifact to deploy; `manage.py runserver` serves everything.
- Operators get fast, printable, document-style screens.

**Trade-offs:**
- Richer interactive views (drag-and-drop, complex dashboards) are harder
  in HTMX than an SPA; the team accepts this for document workflows.
- Tailwind output must be rebuilt after template changes in development
  (`npm run dev` in `backend/frontend/`).
- Session auth is cookie-based; fine for an internal staff app, but the API
  contract remains the right surface for external integrations.

**Testing:** `apps/ui/tests.py` smoke-tests every screen (200 on render,
302 on auth redirects) and the two end-to-end write paths (draft JE → post
with the P100k approval gate, and month-end close advance → complete).

**Deployment:** collectstatic must include `backend/static/` (Tailwind
output + HTMX). No node runtime is required at deploy time — only the
compiled CSS is shipped.
