# ADR-046: UI Redesign — Finance-Nature Theme, Config-Driven Navigation, Executive Dashboard, Mobile Dual-View

**Status:** Accepted
**Date:** 2026-09-23
**Deciders:** Architecture Team

**References:**
- [ADR-036: UI Frontend Decision](./ADR-036-ui-frontend.md) — server-rendered UI + HTMX
- [ADR-039: Folder Structure & Template Partials](./ADR-039-folder-structure-and-template-partials.md) — shared partials
- [ADR-041: Static Asset Cache Policy](./ADR-041-static-asset-cache-policy.md) — static serving
- [ADR-043: Unified System Experience](./ADR-043-unified-system-experience.md) — unification mandate

---

## Context

The UI was functionally complete but visually and structurally dated:

- a generic indigo/slate palette (indistinguishable from any "blue" admin tool);
- a hand-maintained sidebar with ~35 links across 13 static section headers —
  every new screen required editing the template;
- wide financial tables that forced horizontal scrolling on phones;
- no management-level view: executives had to assemble the business picture
  by visiting the statements, aging and cash screens one by one;
- lists filters, buttons, badges, fonts and prints each evolved independently,
  so the same concept looked different per screen.

The business needs were explicit: a finance-nature identity (not generic navy
blue), a bird's-eye view for real-time decision making, mobile-friendly on all
sides, and long-run maintainability of the frontend.

## Decision

### 1. Finance-nature design tokens

Tailwind theme extended with three named palettes
(`backend/frontend/tailwind.config.js`):

| Token | Role | Replaces |
|---|---|---|
| `brand` (teal-based) | Primary actions, active nav, focus rings | indigo / blue / teal |
| `accent` (amber-based) | Warnings, attention badges | orange, ad-hoc ambers |
| `surface` (stone-based) | Backgrounds, neutrals, text | slate |

Headings/body/muted text, cards, tables, forms, badges and toasts all consume
the tokens. Status badge colors remain the single canonical mapping in
`STATUS_COLOR_CLASSES`. Danger is `rose` (was `red`). The convergence is
complete: **no non-print template references the legacy tokens** (indigo/
slate/blue/teal/red/orange) — pinned by the
`test_ui_templates_use_only_theme_tokens` guard. Print templates are excluded
by design (user-approved layouts).

### 2. Config-driven navigation

The sidebar is rendered from **one** config,
`apps/ui/nav.py:NAV_SECTIONS`, resolved by the `nav_sections` context
processor into URL + active-state data. Sections are **collapsible accordions**
(auto-open the active section, persist user state in `localStorage`), and the
sidebar itself collapses to an **icon-only rail** (persisted, tooltips on
hover). Adding a module = one config entry; zero template edits. A duplicated
icon sprite lives in `ui/partials/icons.html` (`i-<name>` symbols).

### 3. Executive Dashboard (4 zones)

`/` is a management dashboard built live from the posted GL
(`apps/ui/services.py::executive_dashboard_context`):

- **Zone A** — 8 KPI cards (Revenue/Expenses/Net Income/Cash/GPM/NPM/AR/AP)
  with MoM trend arrows and drill-down links; segment pill filter
  (DHPP/DMIE/OPS/All) re-scopes every GL-derived number.
- **Zone B** — 4 Chart.js charts (self-hosted UMD in
  `static/js/vendor/chart.umd.min.js`): Revenue vs Expenses, Cash Flow,
  Segment Performance, Expense Breakdown (doughnut with center total).
- **Zone C** — AR/AP aging snapshots (bucket bars) linking to the aging screens.
- **Zone D** — Disbursement pipeline, waiting-on-you, reversal pending,
  unposted documents, and the month-end close checklist.

**Accuracy contract:** figures mirror the statement builders exactly
(`apps/reporting/services.py` — sales 400/410/420, discounts 405/415/425,
COS 50/51/52, other income 430/431); GPM = (Net sales − COS) ÷ Net sales;
NPM = Net income ÷ Net sales — the same ratios the printed Income Statement
shows. All amounts are signed via account `normal_balance`.

### 4. Mobile first everywhere

- Every wide table fragment (`_*table*.html`) is dual-view: desktop table is
  `hidden md:block`; below `md` a stacked **mobile-card** list renders the
  same rows (`md:hidden`). No register requires horizontal scrolling on a
  phone. Long line-item grids keep the fixed-column layout as an accepted
  exception (data-entry surfaces, not reads).
- Filters, headers, form cards and the dashboard grid all collapse to a
  single column.

### 5. Unified list engine extended

The `FilterSpec` engine (ADR-043) now covers **every** list/register screen
(previously 9 of ~19): Billing, CONSO, Banks, Cycles, PCF funds,
PCF replenishments, Recon, Cash Short, Sales Invoices, Fixed Assets — each
with a per-screen `*_filter_spec()` factory, the shared `filter_bar.html`
partial, and an HTMX table fragment. Exports reuse the same spec.

### 6. User management: superadmin + Head CRUD

`/settings/users/` (list, add, edit, deactivate/reactivate) is granted to the
superadmin **and** the Accounting & Finance Head (`roles_allowed: ['head']`
in the nav config). Heads cannot manage superadmin accounts; self-deactivation
is blocked. Username is immutable; password reset is optional-on-edits.

### 7. Featured Bible verse (ESV)

Every page footer and the login screen show a **verse of the week**: 52 ESV
verses (a mix of stewardship/work themes and the gospel) rotate by ISO week —
one per week, a full year's catalog, then it wraps. Served by
`apps/ui/verses.py` + the `weekly_verse` context processor, rendered through
`ui/partials/verse_footer.html`. The ESV® attribution is always visible
(tooltip on the mark, full text in the catalog module).

## Consequences

### Positive
- One palette/token source; restyling is a tailwind-config change, not a
  120-file sweep (utilities are compiled from the tokens).
- Sidebar grows declaratively; icons, labels, ordering, permissions live in one
  file with a guard test that every entry resolves and every icon exists.
- Executives get the bird's-eye view with statement-consistent numbers and
  drill-downs; offline-safe charts.
- Phones/tablets get native stacked cards instead of pinched tables.
- Convention guard tests (`apps/ui/test_frontend_conventions.py`) pin the
  architecture: config-driven nav, dual-view fragments, self-hosted charts,
  palette discipline — so regressions fail CI instead of drifting.

### Negative
- Two extra static assets (chart UMD ~200 KB + charts.js) on the dashboard
  only (loading is page-scoped in the `extra_js` block, not global).
- Dashboard GL aggregation queries run per page view (24 window queries) —
  acceptable today; caching is the remediation path if the GL grows large.
- Wide data-entry grids remain horizontally scrollable (accepted trade-off:
  they are entry surfaces with fixed columns, per the print layout parity).

### Neutral
- The legacy JS bundles (base.js, amount-format.js, form-draft.js, …) remain
  as-is; consolidation was attempted and reverted because it broke the
  draft-autosave script ordering. Revisit only with explicit ordering tests.
- Print layouts are untouched by this redesign; users' approved forms keep
  rendering exactly as reviewed.

---

## Guard tests (executable summary)

`backend/apps/ui/test_frontend_conventions.py` enforces:

1. sidebar rendered from `nav_sections` (no hardcoded nav URLs);
2. every NAV_SECTIONS URL reverses; every icon symbol exists;
3. every `*_filter_spec()` declares fields;
4. every table fragment has `hidden md:block` + a `md:hidden` mobile-card list;
5. list fragments contain no raw pre-redesign accent hexes;
6. base layout consumes design tokens; Chart.js is vendored, no CDN.