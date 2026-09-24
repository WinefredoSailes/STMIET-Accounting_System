# STMIET Accounting System — Backend

Modular monolith for Seven-Trent Machineries Industrial Equipment Trading.
Design decisions live in `/docs/adr/` (ADR-009 modular monolith, ADR-010
Django + PostgreSQL, ADR-002 no force-balance, ADR-004 immutable journal,
ADR-005 GL derivation, ADR-013 Tue-Mon cycles, ADR-032 voucher forms,
ADR-033 payroll GL feed).

## Layout

```
backend/
  config/            project config (settings package, urls, wsgi/asgi)
  apps/
    core/            shared mixins, money, exceptions
    foundation/      COA, companies, segments, fiscal calendar  (Phase 1)
    sequences/       document numbering registry               (Phase 1)
    workflow/        approval state machine                    (Phase 1)
    posting/         journal engine, GL, posting rules         (Phase 1)
    ar/ ap/ cash/    bounded contexts (Phases 2-4)             (stubs)
    inventory/ fleet/ payroll/ assets/ tax/ reporting/         (stubs)
  requirements/      base / dev / prod
```

## Quick start

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements\dev.txt
Copy-Item .env.example .env          # edit SECRET_KEY etc.
python manage.py migrate
python manage.py import_coa --file ..\excel-files\COA-STMIET-2026.xlsx
python manage.py runserver
```

API docs: http://localhost:8000/api/schema/swagger-ui/
Admin: http://localhost:8000/admin/

## Tests

```powershell
pytest
```

The posting engine test suite (apps/posting/tests.py) is the contract for the
core invariants: no force-balance, immutable posted entries, atomic GL
projection, approval threshold, rule-driven canonical JEs (ADR-018).

## Unified document pattern (ADR-043)

Every approval-tracked document (RFP, PO, Check Voucher, Journal Entry, and
Inter-Account Transfer) follows one shape so the screens, services and tests
stay consistent. When adding a document, mirror this pattern rather than
inventing a new one:

| Concern | Convention |
|---|---|
| Lifecycle | `requested/prepared` → `submitted` → `approved` (posts to GL), with `rejected` → revise → resubmit |
| Service | one service class with `create` / `submit` / `approve` / `reject` / `revise`; the head approval is the only GL gate (no amount threshold for cash moves) |
| Audit | append-only `apps.ap.models.ActionLog` entry on every transition (`ActionLog.DocType.*`) |
| Inbox | a `*_queue()` in `apps.core.approvals` so the document appears under My Approvals for the assigned role |
| Detail page | `ui/partials/document_shell.html` + a `*_timeline()` in `ui/services.py` + `ui/partials/workflow_actions.html` + `ui/partials/audit_trail.html` |
| Actions | one `ui/partials/workflow/<type>_actions.html`; only that partial decides status → buttons |
| Exports | `rfp_export`/`cv_export`-style per-document PDF/XLSX/CSV via `apps.core.exports.table_export` |
| Lists | shared `apps.ui.filter_specs` + `filter_bar.html`: search box, status/choice filters, and exports that honour the active filters |
| Print | a fixed-column voucher grid (e.g. FTV uses 14 columns) — every row's spans must fit the grid |

Inter-Account Transfer (ADR-030) is the reference implementation of this
pattern outside AP: `apps/cash/services.py::TransferService`,
`apps/core/approvals.py::transfer_queue`, `ui/cash/transfer_detail.html`, and
`ui/partials/workflow/transfer_actions.html`.

## Frontend conventions (ADR-046)

- **Theme:** finance-nature tokens (`brand`/`accent`/`surface`, danger=`rose`)
  defined once in `backend/frontend/tailwind.config.js`; every NON-print
  template renders from them exclusively (guard:
  `test_ui_templates_use_only_theme_tokens`). CSS is rebuilt with
  `npm run build` from `backend/frontend`.
- **Navigation:** the sidebar loops `apps/ui/nav.py::NAV_SECTIONS` via the
  `nav_sections` context processor — adding a module is one config entry
  (label, icon, URL name, permissions). Sections are accordions; the sidebar
  collapses to an icon rail (state kept in `localStorage`).
- **Lists:** every register uses an `apps/ui/filter_specs` factory + the shared
  `filter_bar.html` partial + an HTMX `_*table*.html` fragment.
- **Mobile:** every table fragment is dual-view — desktop table `hidden md:block`
  plus a `md:hidden` stacked card list (`.mobile-card*` utility classes).
- **Dashboard:** `/` is the 4-zone executive dashboard
  (`apps/ui/services.py::executive_dashboard_context`, Chart.js self-hosted in
  `static/js/vendor/`). KPI math mirrors the statement builders exactly.
- **Universal confirm:** every immediate workflow action (approve, reject,
  submit, post, close, void, ...) routes through ONE shared modal —
  `static/js/confirm-core.js` (pure rules: explicit `data-confirm` text wins;
  note-textarea forms ARE their own confirmation; otherwise the button's
  first verb decides) + the delegated guard/modal in `base.js`, which also
  captures `htmx:confirm` so row buttons share the same dialog. Node-tested.
- **Guards:** `apps/ui/test_frontend_conventions.py` pins these invariants —
  nav config, dual-view fragments, self-hosted charts, palette discipline,
  user-management access (superadmin + Head CRUD).
- **Screen access (ADR-047):** `apps/ui/screens.py` maps every UI route and
  API resource to a screen; `UserProfile.screen_access` (NULL = role
  template) plus `ScreenAccessMiddleware` hard-403 anything off a user's
  desk — hidden means unreachable, deep URLs and API included. Assignment is
  the checkbox grid in the user create/edit forms; the COO signs CNR items
  inline from My Approvals without owning any register. Guards:
  `test_screens_registry.py`, `test_screen_access_enforcement.py`,
  `test_inbox_actions.py`.

## Environments

- `config.settings.dev`   — SQLite fallback, DEBUG on (default).
- `config.settings.prod`  — requires `DATABASE_URL` to PostgreSQL, strict HTTPS.
- `config.settings.test`  — in-memory SQLite, used by pytest.

PostgreSQL locally: use docker-compose (db) or point `DATABASE_URL` at a
running instance (postgres 17 present on this machine).

## Recent changes (as of UAT guide v2)

All tests passing after these session changes:

- **Print forms:** spacer rows removed from cv_print.html + rfp_print.html  
- **RFP header:** refactored: 3-col grid Payee|Date of Request|Cost Center / Ref, hidden segment + sync JS  
- **Approvals list:** actions column removed from /approvals/ table  
- **CONSO auto-assign:** double-count bug fixed (total_amount prior sum before attach)  
- **CV lifecycle:** signed_by / released_by removed (migration 0009)  
- **Tailwind:** rebuilt for new grid classes  
- **Flags:** COO_REVIEW_ENABLED + CONSO_AUTO_ASSIGN both default False; flip at go-live  
- **Cleanup:** removed unstaged experimental changes from earlier session (core/approvals.py, core/tests.py, related test artifacts) that caused test regressions; working tree now clean and focused on ₹100k threshold removal + PDF export objectives  

Run `pytest --nomigrations -q` all green.

## Recent changes (transfer unification)

- **Inter-Account Transfer** now follows the RFP/JE/CV pattern end to end:
  dedicated batch create form, per-transfer detail page (shell + timeline +
  workflow actions + audit trail), PDF/Excel/CSV exports, and search/status/
  from/to filters on the register (exports honour the filters).
- **Approval flow:** `requested → submitted → approved` with reject (note
  required) → revise → resubmit; the preparer submits, the head approves and
  the JE posts. New `ActionLog.DocType.TRANSFER` audit trail; the head's
  "My Approvals" inbox keys off `submitted`.
- **Per-line purpose:** transfer JE lines carry the entered purpose; data
  migration `cash/0018` backfills legacy placeholder descriptions.
- **FTV print/PDF:** header rebuilt to a true 14-column grid — the old
  rowspan overflow produced a 28-column table. `ACCOUNTING DEPARTMENT` plus
  the dynamic `VOUCHER REF # / DATE / TRANSFER TYPE / PREPARED BY` fields sit
  in the right rail; a regression test pins every row to 14 columns.
- Full suite: `pytest` → 707 passed, 3 skipped. See ADR-043 for the
  unification mandate this establishes.

## Recent changes (reversal, pending postings, reject-return)

- **Reversal (ADR-044):** posted entries are corrected by a maker-checker
  reversing entry — the preparer requests with a reason, the head approves
  (`PostingService.reverse` posts the mirror) or rejects (note required).
  Posted entries stay undeletable. `apps/posting/test_reversal*.py`.
- **Recompute:** `GL_EFFECTIVE_STATUSES = (POSTED, REVERSED)` is used by every
  balance reader so the original + mirror net to zero; PO balances exclude
  reversed RFPs, AR invoices re-open when a collection is reversed, and open
  cash cycles regenerate. Locked cycles are never restated.
- **Pending / Unposted tab:** the Journal Entries screen (and dashboard) surface
  approved RFP/CONSO/PCF documents that have no JE yet. `ui/services.py::pending_documents`.
- **Reject-return:** rejected RFP/PO/CV/Transfer stay trackable + revisable in
  their own list/detail; source-document JEs cannot be edited/submitted/
  approved/posted through the generic JE module (`_manual_je_guard`).
- **JE rejection note** now shows to the requester (detail + edit form + a
  "Returned" chip in the register).
- `ActionLog.DocType.JE` added — JE audit no longer collides with RFP history.
