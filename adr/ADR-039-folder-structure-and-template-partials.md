# ADR-039: Frontend Folder Structure & Reusable Template Partials

**Status:** Accepted
**Date:** 2026-09-07
**Last updated:** 2026-09-08 (status Proposed → Accepted after the phased refactor shipped)
**Deciders:** Architecture Team

**References:**
- [ADR-009: Modular Apps](./ADR-009-modular-apps.md) — bounded contexts as separate Django apps
- [ADR-036: Server-Rendered UI](./ADR-036-ui-frontend.md) — Django templates + HTMX + Tailwind decision
- [ADR-020: AP Approval Matrix](./ADR-020-ap-approval-matrix.md) — workflow action patterns
- [ADR-032: Voucher Format](./ADR-032-voucher-format-specification.md) — document shell layout

---

## Context

The UI app (`backend/apps/ui/`) currently has **72 templates** and **0 dedicated JS/CSS files**. All interactivity lives in per-page inline `<script>` blocks. All styling comes from Tailwind's utility classes, compiled from a single `input.css`.

Three problems have accumulated:

1. **Template duplication** — Six distinct visual patterns are copy-pasted across 40+ screens:
   - List/table card (15 screens)
   - Create/edit form card (12 screens)
   - Document voucher shell (6 screens)
   - Status badge (7+ status enums)
   - Report export toolbar (3 screens)
   - Workflow action bar (3 document types)

2. **No shared JS** — The searchable-combobox enhancer (230 lines) lives in `base.html`. Per-page JS (JE line-grid totals, CV gross-WHT-net calc, RFP reject-toggle) is inline with no re-use path.

3. **Flat template directory** — 72 files in `templates/ui/` with only a `partials/` subfolder. Finding, navigating, and onboarding new screens is slow.

---

## Decision

### 1. Restructure `backend/static/` — dedicated JS and CSS modules

```
backend/static/
├── css/
│   └── output.css                    (compiled Tailwind — unchanged)
├── img/
│   └── logo.svg
└── js/
    ├── htmx.min.js                   (vendored — unchanged)
    ├── base.js                       NEW — sidebar, CSRF, toast, searchable combobox
    ├── line-grid.js                  NEW — generic add-line / running totals for JE & similar
    ├── gross-net-calc.js             NEW — CV-style gross − WHT = net computation
    └── toggle-block.js               NEW — show/hide a sibling block (reject note, etc.)
```

**What moves where:**

| Current location | New file | Rationale |
|---|---|---|
| `base.html` inline `<script>` (sidebar toggle, CSRF, toast, searchable combobox — ~230 lines) | `static/js/base.js` | Loaded once by `base.html` via `{% static 'js/base.js' %}`. Removes 230 lines from the template. |
| `je_form.html` inline `<script>` (add-line + running debit/credit totals — ~35 lines) | `static/js/line-grid.js` | Generic: works on any table with `.amount-debit` / `.amount-credit` inputs and `#add-line` button. JE, future AP distribution grids, etc. |
| `cv_form.html` inline `<script>` (gross − WHT = net — ~20 lines) | `static/js/gross-net-calc.js` | Reusable for any voucher form with withholdings. |
| `rfp_detail.html` inline `<script>` (reject-toggle — ~10 lines) | `static/js/toggle-block.js` | One-liner: `document.querySelectorAll('[data-toggle]').forEach(…)` + delegated listener. Replaces identical blocks in RFP, CV, any future reject/expand pattern. |

**Tailwind config update** — no change needed; `tailwind.config.js` content glob already scans `../apps/**/templates/**/*.html`. The new JS files are static assets, not templates.

### 2. Restructure `backend/apps/ui/templates/ui/` — domain subdirectories

Current flat structure → organized by bounded context, matching `apps/` layout:

```
backend/apps/ui/templates/ui/
├── base.html                          (master layout — unchanged)
├── _sidebar.html                      (nav — unchanged)
│
├── partials/                          SHARED COMPONENTS (expanded)
│   ├── pagination.html                (existing — unchanged)
│   ├── page_header.html               NEW — back-link + title + subtitle + action button(s)
│   ├── list_card.html                 NEW — full list/table card wrapper
│   ├── form_card.html                 NEW — create/edit form card wrapper
│   ├── status_badge.html              NEW — centralized status→color mapping
│   ├── document_shell.html            NEW — ACCTG-FOR header + meta grid + line table
│   ├── workflow_actions.html           NEW — status→action-button matrix (per doc type)
│   └── report_toolbar.html            NEW — format dropdown + Export + Print buttons
│
├── auth/
│   ├── login.html
│   └── dashboard.html
│
├── approvals/
│   └── approvals.html
│
├── posting/
│   ├── je_list.html
│   ├── je_detail.html
│   └── je_form.html
│
├── foundation/
│   ├── coa_list.html
│   ├── coa_form.html
│   ├── coa_print.html
│   ├── _coa_rows.html
│   └── user_management.html
│
├── reporting/
│   ├── trial_balance.html
│   ├── trial_balance_print.html
│   ├── statement.html
│   ├── statement_print.html
│   ├── month_end_close.html
│   ├── general_journal.html
│   └── cash_flow.html
│
├── ar/
│   ├── customer_list.html
│   ├── customer_form.html
│   ├── receipt_list.html
│   ├── receipt_form.html
│   └── aging.html
│
├── ap/
│   ├── supplier_list.html
│   ├── supplier_form.html
│   ├── supplier_update.html
│   ├── rfp_list.html
│   ├── rfp_form.html
│   ├── rfp_detail.html
│   ├── _rfp_row.html
│   ├── cv_list.html
│   ├── cv_form.html
│   ├── cv_detail.html
│   ├── _cv_row.html
│   ├── conso_list.html
│   ├── conso_form.html
│   ├── conso_detail.html
│   ├── advances.html
│   └── aging.html
│
├── cash/
│   ├── bank_list.html
│   ├── bank_form.html
│   ├── bank_update.html
│   ├── cycle_list.html
│   ├── cycle_form.html
│   ├── pcf_list.html
│   ├── pcf_form.html
│   ├── pcf_replenish_form.html
│   ├── pcf_replenishment_list.html
│   ├── pcf_replenishment_detail.html
│   ├── recon_list.html
│   ├── recon_form.html
│   ├── cash_short_list.html
│   ├── cash_short_form.html
│   ├── _cash_short_row.html
│   ├── collections_summary.html
│   ├── collectibles.html
│   ├── cash_flow.html
│   └── transfers.html
│
├── assets/
│   ├── asset_list.html
│   ├── asset_form.html
│   ├── asset_detail.html
│   ├── asset_dispose_form.html
│   ├── asset_reverse_form.html
│   └── _asset_rows.html
│
├── fleet/
│   └── fuel.html
│
└── tax/
    ├── dashboard.html
    ├── vat.html
    ├── wht.html
    ├── provision.html
    └── calendar.html
```

**Impact on `tailwind.config.js`:** No change — the content glob `../apps/**/templates/**/*.html` already matches nested directories.

**Impact on `apps/ui/urls.py`:** No change — Django template loader finds templates by `{app_label}/{template_name}` path, not by URL.

**Migration strategy:** Move files, then update all `{% include %}` and `{% extends %}` paths in one pass. The existing `partial` includes already use `ui/partials/` — they just gain new siblings.

### 3. Reusable template partials — extraction specification

Each partial receives its data through Django template context variables. Partials never import models or call services directly.

#### 3a. `partials/page_header.html`

Replaces the repeated `&larr; Back` link + `<h1>` + `<p>` + optional action button block.

```html
{# Usage: {% include "ui/partials/page_header.html" with back_url="ui:customer_list" back_label="Customers" title="New Customer" subtitle="…" %} #}
<a href="{% url back_url %}" class="text-sm text-slate-500 hover:text-slate-700">&larr; {{ back_label }}</a>
<h1 class="text-xl font-semibold text-slate-900 mt-1">{{ title }}</h1>
{% if subtitle %}<p class="text-sm text-slate-500 mt-1">{{ subtitle }}</p>{% endif %}
```

Used by: every form page, every detail page (~25 screens).

#### 3b. `partials/list_card.html`

Wraps the page header + filter bar + table card + pagination into a single include. The caller provides only: `title`, `subtitle`, `create_url`, `create_label`, `table_head` (block), `table_body` (block), optional `table_foot`.

```html
{# Wraps: header + table card + pagination. Caller fills table_head/table_body blocks. #}
{% include "ui/partials/page_header.html" with back_url=None title=title subtitle=subtitle %}
<div class="flex items-center justify-between mt-4">
  <div></div>
  {% if create_url %}
  <a href="{% url create_url %}" class="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700">{{ create_label|default:"+ New" }}</a>
  {% endif %}
</div>
<div class="mt-4 bg-white rounded-xl border border-slate-200 overflow-x-auto">
  <table class="w-full text-sm min-w-[{{ min_width|default:'900' }}px]">
    <thead class="bg-slate-50 text-left text-xs uppercase tracking-wider text-slate-500">
      <tr>{{ table_head }}</tr>
    </thead>
    <tbody class="divide-y divide-slate-100">
      {{ table_body }}
    </tbody>
    {% if table_foot %}<tfoot class="bg-slate-50 font-semibold"><tr>{{ table_foot }}</tr></tfoot>{% endif %}
  </table>
</div>
{% include "ui/partials/pagination.html" %}
```

Used by: customer_list, supplier_list, je_list, bank_list, cycle_list, pcf_list, recon_list, receipt_list, asset_list, coa_list, rfp_list, cv_list, conso_list, cash_short_list, pcf_replenishment_list (~15 screens).

#### 3c. `partials/form_card.html`

Wraps the create/edit form in the standard card. Caller provides a `form_fields` block.

```html
{# Usage: {% include "ui/partials/form_card.html" with action_url="ui:customer_create" submit_label="Create customer" %} #}
<form method="post" action="{% if action_url %}{% url action_url %}{% endif %}" class="mt-6 bg-white rounded-xl border border-slate-200 p-6 space-y-4">
  {% csrf_token %}
  <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
    {{ form_fields }}
  </div>
  <div class="flex justify-end">
    <button type="submit" class="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700">{{ submit_label }}</button>
  </div>
</form>
```

Used by: customer_form, supplier_form, bank_form, receipt_form, cycle_form, pcf_form, recon_form, coa_form, asset_form, cash_short_form, advances (~12 screens).

#### 3d. `partials/status_badge.html`

Centralizes the status→color mapping so it's defined in exactly one place.

```html
{# Usage: {% include "ui/partials/status_badge.html" with status=rfp.status %} #}
{# Reads: STATUS_COLORS dict from templatetags/ui_filters.py #}
{% load ui_filters %}
<span class="inline-flex rounded-full px-2.5 py-1 text-xs font-medium {{ status|status_color_class }}">{{ status|title }}</span>
```

A new template filter `status_color_class` in `templatetags/ui_filters.py` returns the Tailwind class string for each known status. This eliminates 7+ duplicated `{% if %}` / `{% elif %}` chains.

**Status → color mapping (single source of truth):**

| Status | Tailwind classes |
|---|---|
| `posted` | `bg-emerald-100 text-emerald-800` |
| `approved`, `acctg_approved`, `fin_approved`, `cnr_approved` | `bg-emerald-100 text-emerald-800` |
| `submitted`, `checked`, `pending`, `in_progress` | `bg-amber-100 text-amber-800` |
| `rejected`, `void`, `reversed` | `bg-red-100 text-red-800` |
| `draft`, `prepared` | `bg-slate-100 text-slate-700` |
| `cleared` | `bg-blue-100 text-blue-800` |
| default | `bg-slate-100 text-slate-600` |

Used by: je_list, je_detail, rfp_list, rfp_detail, cv_detail, asset_list, _asset_rows, dashboard (~8 screens).

#### 3e. `partials/document_shell.html`

The ACCTG-FOR document header + meta grid + distribution-charges table used by RFP detail, CV form/detail, PCF replenishment detail, CONSO detail.

```html
{# Wraps a document in the standard ACCTG-FOR card. Caller provides meta_fields and line_table blocks. #}
<div class="bg-white rounded-xl border border-slate-200 overflow-x-auto">
  <div class="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
    <div>
      <div class="text-sm font-semibold text-slate-900">{{ doc_title }}</div>
      <div class="text-xs text-slate-500">{{ doc_form_id }}</div>
    </div>
    <div class="text-right text-xs text-slate-500">
      <div>AP NO: <span class="font-mono font-medium text-slate-800">{{ doc_number }}</span></div>
      {% if last_ap %}<div>LAST AP: <span class="font-mono">{{ last_ap }}</span></div>{% endif %}
    </div>
  </div>
  <div class="px-6 py-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
    {{ meta_fields }}
  </div>
  <div class="px-6 pb-4">
    {{ line_table }}
  </div>
</div>
```

Used by: rfp_detail, cv_form, cv_detail, pcf_replenishment_detail, conso_detail (~5 screens).

#### 3f. `partials/workflow_actions.html`

The status→action-button matrix for document workflows. Takes a `workflow_type` and the document object.

```html
{# Usage: {% include "ui/partials/workflow_actions.html" with doc=rfp workflow_type="rfp" %} #}
{# This is a thin dispatcher; the actual per-workflow logic stays in the template
   but is isolated to this partial rather than inlined in 6 different rfp_detail
   condition blocks. #}
```

This partial encapsulates the approve/reject/revise action forms currently spread across `rfp_detail.html` (6 branches) and `cv_detail.html` (3 branches). Each document type defines its own workflow partial under its subdirectory, but the outer container (awaiting-callout, action buttons) is shared.

Used by: rfp_detail, cv_detail, je_detail (~3 screens, expandable).

#### 3g. `partials/report_toolbar.html`

The format dropdown + Export + Print button row.

```html
{# Usage: {% include "ui/partials/report_toolbar.html" with print_url="ui:trial_balance_print" %} #}
<div class="flex items-center gap-2 mt-2">
  <select name="format" class="rounded-md border border-slate-300 px-2 py-1.5 text-sm">
    <option value="xlsx" {% if format == 'xlsx' %}selected{% endif %}>XLSX</option>
    <option value="csv" {% if format == 'csv' %}selected{% endif %}>CSV</option>
    <option value="pdf" {% if format == 'pdf' %}selected{% endif %}>PDF</option>
  </select>
  <button type="submit" name="export" class="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700">Export</button>
  <a href="{% url print_url %}" class="rounded-md bg-slate-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700">Print</a>
</div>
```

Used by: trial_balance, statement, cash_flow (~3 screens).

### 4. New JS modules — extraction specification

#### 4a. `static/js/base.js`

Extracted from `base.html` inline `<script>`. Contains:
- Sidebar toggle
- CSRF token injection into HTMX requests
- `showToast` event handler
- Searchable combobox enhancer (full `MutationObserver`-based system)

Loaded via `<script src="{% static 'js/base.js' %}"></script>` in `base.html`.

#### 4b. `static/js/line-grid.js`

Generic add-line + running totals for any JE-style line grid. Works on any `<table>` containing `.amount-debit` and `.amount-credit` inputs with an `#add-line` button.

Exposed API:
```html
<table data-line-grid>
  <!-- rows with .amount-debit / .amount-credit inputs -->
  <tfoot>…<button id="add-line">…</button></tfoot>
</table>
```

Auto-discovers all `[data-line-grid]` tables on `DOMContentLoaded`.

Used by: je_form (immediately), future AP distribution grids.

#### 4c. `static/js/gross-net-calc.js`

Gross − WHT = net computation. Activated via `data-gross-net` attribute on a container.

Used by: cv_form (immediately), future withholding forms.

#### 4d. `static/js/toggle-block.js`

Generic show/hide toggle for sibling elements. Activated via `data-toggle="target-id"` on any button.

```html
<button data-toggle="reject-form">Reject with note</button>
<div id="reject-form" class="hidden">…</div>
```

Used by: rfp_detail (immediately), any future expand/collapse pattern.

---

## Consequences

### Positive

- **Single source of truth** — Status badge colors, form card wrappers, list card wrappers, and document shell markup are defined once. Changing the status badge from `px-2.5` to `px-3` is a one-line edit, not an 8-file find-replace.
- **Faster onboarding** — New developers navigate `templates/ui/ar/` instead of scanning 72 flat files. Domain subdirectories mirror `apps/` structure.
- **Faster development** — Adding a new list screen: include `list_card.html`, fill 2 blocks. Adding a new form: include `form_card.html`, fill 1 block. Estimated 60-70% HTML reduction per new screen.
- **JS reuse** — `line-grid.js` works for JE and all future line-entry forms. `toggle-block.js` replaces identical reject-toggle snippets. New JS modules are small, focused, and testable.
- **Troubleshooting** — Forms, tables, filters, and actions are in known locations. A broken status badge → check `status_badge.html` + `ui_filters.py`. A broken list → check `list_card.html`. A broken workflow action → check `workflow_actions.html`.

### Trade-offs

- **One-time migration effort** — ~50 templates need path updates for `{% include %}` directives. Estimated 1-2 hours with automated find-replace + manual review.
- **Partial nesting depth** — Templates will have 2 levels of includes (base → partial). This is manageable; Django template loader handles it efficiently.
- **JS module loading** — `base.js` loads synchronously (not `defer`), which is correct since it sets up the DOM before HTMX fires. New JS modules use `defer` via `{% block extra_js %}`.

### Not changed

- **`apps/ui/views.py`** — No view changes needed. Templates are found by path, not URL.
- **`apps/ui/urls.py`** — No URL changes.
- **`apps/ui/services.py`** — No service changes. Partials consume the same context variables.
- **Tailwind config** — Content glob already matches nested template directories.
- **`apps/ui/templatetags/ui_filters.py`** — Extended (add `status_color_class` filter), not restructured.

---

## Implementation Plan

| Step | Description | Files touched |
|---|---|---|
| 1 | Create `static/js/base.js` — extract inline `<script>` from `base.html` | `base.html`, `static/js/base.js` |
| 2 | Create `static/js/line-grid.js` — extract from `je_form.html` | `je_form.html`, `static/js/line-grid.js` |
| 3 | Create `static/js/gross-net-calc.js` — extract from `cv_form.html` | `cv_form.html`, `static/js/gross-net-calc.js` |
| 4 | Create `static/js/toggle-block.js` — extract from `rfp_detail.html` | `rfp_detail.html`, `static/js/toggle-block.js` |
| 5 | Add `status_color_class` filter to `ui_filters.py` | `templatetags/ui_filters.py` |
| 6 | Create all 7 partials in `partials/` | `partials/*.html` |
| 7 | Move templates into domain subdirectories | ~70 files across 10 subdirs |
| 8 | Update all `{% include %}` and `{% extends %}` paths | ~50 templates |
| 9 | Refactor existing screens to use partials (batch by domain) | 40+ templates |
| 10 | Run `npm run build` to regenerate Tailwind output | `frontend/` |
| 11 | Run `pytest` to verify no regressions | test suite |
| 12 | Update `UI.md` and `BUILD-PLAN.md` with new structure | docs |

---

## Verification

1. `python manage.py test apps.ui` — all screen renders pass (200 status)
2. `pytest apps/ui/test_e2e.py` — end-to-end write paths still work
3. Manual check: every list screen renders with pagination, every form submits, every detail page loads workflow actions
4. `npm run build` — Tailwind output includes all new partial classes

---

## Accepted (2026-09-08) — Execution notes & deviations from the original plan

The refactor shipped in phases (0–8), each gated by a full test run
(`pytest apps/ui apps/ap apps/posting apps/core -q` → 172 passing) plus an
`npm run build` in Phase 8. No functional regression; screens preserved exact
Tailwind markup while tests assert status 200 + cell text.

Deliberate deviations from the draft spec:

- **`{% capture %}` tag instead of named blocks.** Django `{% include %}`
  cannot pass block content, so partials that wrap variable markup
  (`list_card`, `form_card`, `document_shell`, `page_header`, `workflow_actions`)
  receive captured `…_html` context params via the custom `CaptureNode`/
  `do_capture` tag in `templatetags/ui_filters.py`.
- **`report_toolbar.formats` is a whitespace-separated string**, split in the
  partial by a new `split` filter (literal lists were verbose and read-only).
  The format-dropdown redirect is global in `base.js`
  (`select[data-format-redirect]`); report screens don't inline JS.
- **Detail-screen status colors stay bespoke.** `rfp_detail`/`cv_detail`
  pass explicit `color` overrides to `status_badge`, preserving the historical
  per-status palette (e.g. CV cleared = emerald/slate-800) rather than the
  canonical `status_color_class` defaults.
- **`template-rows.js`** (not in the draft) was added for clone-from-`<template>`
  rows (supplier contacts) that the original `supplier_form` inlined.
- **`window.onafterprint` is centralized in `base.js`**; the five print
  templates (`cv_print`, `coa_print`, `statement_print`, `trial_balance_print`,
  `pcf_replenishment_print`) no longer inline it.
- **Domain subdirectory move was skipped.** Templates were already
  de-facto grouped by bounded context under `templates/ui/` (the ADR's target
  layout already matched the live tree), so the mechanical file-move step was
  unnecessary. The focused deliverable was the partials + JS-module extraction.
- **All 16 remaining multi-line inline `<script>` blocks were removed.**
  The only intentional inline JS left is the full-page RFP-prefill redirect in
  `cv_form` (`onchange="if(this.value) location.href='?rfp='+this.value"`)
  and the sidebar toggles in `base.html` that call the global
  `toggleSidebar` (defined in `base.js`).

## Execution notes � dropdown sizing regression (fixed)
- **Root cause (2006-09-08):** the searchable-combobox widget builds its DOM at
  runtime in `base.js` (trigger button, chevron SVG, open panel). Tailwind only
  scanned `apps/**/templates/**/*.html`, so classes used *only* by JS
  (`.h-4`, `.max-h-56`, `.z-50`) were never compiled into `output.css`. The
  chevron `<svg class="h-4 w-4">` then lost its height, was blockified as a flex
  item, and its intrinsic size snapped to the full button content box (424x424px
  on a 1280px viewport), inflating the trigger to ~443-633px and the host grid
  rows to >400px on every searchable field (New/Edit Bank GL, RFP payee/item
  account). The open panel was also uncapped (`max-h-56` missing) and
  un-layered (`z-50` missing, it rendered below the z-40 sidebar).
- **Fix (shared, not per-field):** added `"./../static/js/**/*.js"` to the
  Tailwind `content` glob so runtime-generated classes are always emitted.
  `npm run build` regenerated `output.css` with `.h-4`, `.max-h-56`, `.z-50`.
  Verified headlessly in Edge: trigger 38px, chevron 16x16, grid rows back to
  ~62px, panels capped at 224px with z-50, all native selects ~32-39px, RFP
  compact triggers 30px � at desktop and 390px widths.
- **Operational rule:** any Tailwind class introduced inside `static/js/`
  requires the JS content glob above (or an inline fallback). Do not reintroduce
  per-field height overrides.
