# System-wide Export Unification — Master Plan

## Goal
Full export capability (downloadable PDF / XLSX / CSV) across documents, registers, and lists — powered by **two unified engines** instead of the current 5+ duplicated/broken code paths — with **zero destruction** of existing layouts.

## Hard guarantees (non-negotiable)
1. **Existing browser-print templates are NOT touched** (je_print, rfp_print, cv_print, pcf_replenishment_print, statement_print, trial_balance_print, coa_print) — they are the golden layout sources of truth.
2. **Existing export endpoints keep working**: same URLs, same filenames, same content-types (je list/GJ/TB/statement xlsx & csv; TB statement pdf).
3. **Voucher PDFs reproduce their printed forms faithfully** (RFP ACCTG-FOR-012, CV ACCTG-FOR-010, PCF workpaper) including quirks: RFP 4-signature chain, CV disclaimer row + 5-signatory strip, PCF A4-landscape 23-col table with Total under the Cr. column.
4. **JE voucher PDF unchanged** (already shipped) — only refactored to sit on the shared primitives, byte-shape guarded by tests.
5. No DB changes. No API/serializer changes. Business logic stays in services.

---

## Architecture

### Engine A — generic table exports
New module `apps/core/exports.py`:

```python
class Column(label, width_cm, align='LEFT'|'RIGHT'|'CENTER', wrap=False)
class TableSpec(title, company=True, columns, preamble=list[list],   # meta label/value rows
                rows, totals_row, notes=list[str])
def table_export(request_or_ctx, spec, fmt: 'xlsx|csv|pdf', filename_stem) -> HttpResponse
```
- **XLSX**: promoted copy of `_table_workbook` — *fix*: numbers stay numeric (Debit/Credit as floats with #,##0.00 format), column widths from spec.
- **CSV**: delegates to existing `reporting.exports.csv_response` (unchanged output shape for old callers).
- **PDF**: promoted, fixed `_wide_pdf_response` — per-spec column widths (kills the 4+ column overflow), landscape LETTER by default, `repeatRows=1`, `break-inside` row integrity, money right-aligned tabular.
- Single `attachment()` response wrapper (Content-Disposition + types).
- **Back-compat**: `reporting.exports.csv_response/pdf_response` re-implemented as thin wrappers over Engine A with identical signatures → every existing caller keeps working; `views._table_workbook/_wide_pdf_response` deleted after call-site migration.

### Engine B — voucher/workpaper PDF
Refactor `apps/ui/pdf.py` internals into `apps/core/voucher_pdf.py` primitives:
`form_header(logo, title, doc_no, effective, revision, grid)` · `band(text)` · `info_grid(rows)` · `charges_table(cols spec)` · `coa_section()` · `disclaimer(text)` · `signature_strip([(label, name, role), ...])` · `totals_row()`
- `?paper=a4|a5` query support (defaults today: RFP/CV print forms are A5 → voucher PDFs default **A5** for them; JE stays **A4** to not change its current download; both overridable).
- Per-form builders in `apps/ui/pdf.py` (keeps ui app as the view-layer owner): `build_journal_voucher_pdf` (rewired, same output), `build_rfp_pdf(rfp, ctx)`, `build_cv_pdf(cv, ctx)`, `build_pcf_pdf(replen, rows, ctx→ workpaper, landscape)`.
- Signatory/date data resolved exactly like print views do today (`signatory_name`/role_assignee, position/address fallbacks) — one helper `form_context(obj)` feeding both HTML print view and PDF builder so they can never drift.

### Toolbar partial
`ui/partials/export_buttons.html` (NEW, reusable):
- Renders `[Export PDF][Export Excel][Export CSV]` as direct GET links to `?fmt=` on the document export URLs
- `report_toolbar.html` extended with `export_url` param + JS: `select[data-format-redirect]` prefers `export_url` when present, falls back to current path+format (cash-flow keeps working untouched).

---

## Phases

### Phase 0 — Fix the broken paths (small, unblock tests)
1. **IS export 404**: add `("STATEMENT-OF-INCOME", build_income_statement)` to `statement_export` builders dict.
2. **Cash-flow print 500**: view body is a TB copy-paste + template missing → rewrite `cash_flow_print` to actually render a print-optimized cash-flow page (new `cash/cash_flow_print.html` mirroring `cash_flow.html` layout with @page CSS). 
3. **Cash-flow XLSX unlinked**: point the screen's Export at `cash_flow_export?format=xlsx`.
4. **TB / statement toolbar buttons dead**: give `report_toolbar` include an `export_url` (uses the pattern from §toolbar).
5. (optional, ask) shadowed duplicate `month_end_close` view removal.

### Phase 1 — Engine A + migrate existing exports
- Create `apps/core/exports.py`; convert `reporting.exports` wrappers; migrate to Engine A: `je_list_export`, `general_journal_export`, `trial_balance_export`, `statement_export` (csv/pdf), `cash_flow_export`, `je_csv_export` (block layout preserved via `preamble`+`rows`+`postamble`), `je_xlsx_export` (fixed numeric cells now).
- **Guard tests first**: snapshot-test current CSV lines / xlsx sheet titles before refactor, assert equality after.

### Phase 2 — Document exports (the user's "reproduce" ask)
Per document: add `/<app>/<docs>/<pk>/{pdf,xlsx,csv}/` + detail-page buttons.
| Doc | PDF | XLSX/CSV | Notes |
|---|---|---|---|
| **RFP** | Engine B — mirror rfp_print.html 1:1 (Payee Info incl. POSITION/VENDOR NO/DEPT/AP NO, Distribution Charges, Chart of Accounts incl. VAT "0.00" + Net Invoice rows, 4-name signature strip w/ roles) | spec from rfp_detail + dr_lines incl. cost_center | |
| **CV** | Engine B — mirror cv_print.html (payee, distribution charges, TOTAL AMOUNT, disclaimer row, 5-signatory strip with exact sub-labels) | + GROSS/WHT/NET fields | |
| **PCF replenishment** | workpaper layout — **A4 landscape, 23-col table, Total under Cr.**, blank legacy cells preserved | detail-screen columns (8) | |
| **CONSO batch** | table-PDF (Engine A): batch header + member RFP rows (it has no printed form) | same spec | |
| **Asset card** | table-PDF: stat blocks + depreciation schedule + NBV (no printed form exists) | same spec | |
| **AR receipt** | **No receipt detail/print exists** → Engine-A table-PDF of one receipt + add Export buttons on the **receipt list** (register spec: AR#,Date,Customer,Segment,Method,Check No,Amount). Detail page optional. | list-level | flag below |

### Phase 3 — Register/list exports (Engine A + buttons)
Add `format=xlsx|csv|pdf` export routes reusing each page's own service context (`aging_context`, `list_entries`, `list_cycles`, `list_recons`, `list_cash_shorts`, `daily_collections`, `collectibles`, `advances_context`, `conso_context`, coa_rows, `list_assets`, `list_customers`, `list_suppliers`, fleet fuel, tax vat/wht/provision/calendar, month-end close steps, cash/cycle lists). One descriptor function per screen (~15–30 lines each): columns+rows from the data already rendered → guarantees **PDF rows == screen rows == CSV rows**.

### Phase 4 — Final sweep
- All export buttons via `export_buttons.html` / extended `report_toolbar` → visual consistency
- New Tailwind classes (if any) → `npm run build`
- README/UI.md export section update

### Phase 5 — Test matrix (always-on regression)
`tests/test_exports_matrix.py`:
- Parameterized **every export URL × every format**: login fixture; per-family DB fixture (posted JE incl. the existing NULL-segment edge case; RFP thru `fin_approved`; CV thru `CVPaymentService`; PCF replenishment w/ expenses; assets; aging rows; recon; cash short; collections; COA).
- Assert: 200 · correct `Content-Type` · `attachment` filename · magic bytes (`%PDF`, zip `PK`, `text/csv`) · PDFs > 800 B · CSV has expected header row · **xlsx numbers are numeric cells**.
- Null-safety: the entry 151 regression (`segment=None` lines) extended to RFP/CV/PCF PDF specs.
- Full existing suite stays green (baseline: 432 tests).

## Acceptance checklist
- [x] JE list/GJ/TB/statements/cash-flow exports work and match pre-refactor output (csv) / improve where broken (pdf widths, xlsx numerics)
- [x] IS export no longer 404s; cash-flow print no longer 500s; TB/statement/cash-flow export buttons actually export
- [x] RFP/CV/PCF: downloadable PDF (form-faithful) + XLSX + CSV from detail pages; `?paper=` honored
- [x] CONSO/asset/AR-receipt: CSV/XLSX/PDF working; screens get export links
- [x] Every register/list in §3 has PDF/XLSX/CSV
- [x] No print template file is modified (git diff = 0 on *_print.html except cash_flow_print NEW creation)
- [x] Matrix tests green; full suite green; `manage.py check` clean

## Open questions (confirm before Phase 2)
1. **AR receipts**: no receipt document view exists at all. OK to (a) add exports to the *list* + a table-style per-receipt PDF, or (b) also build a new ACCTG-FOR-005 receipt form? (b) is extra scope.
2. **PCF CSV columns**: 8-column detail-screen set (recommended) vs full 23-col workpaper?
3. Order OK? Phase 0+1 (safe) → Phase 2 (voucher PDFs) → Phase 3 → 4 → 5.

## Effort estimate
P0 ≈ 0.5 day · P1 ≈ 1.5 days · P2 ≈ 2–3 days (RFP≈1, CV≈0.5, PC≈0.75, CONSO/asset/receipt≈0.75) · P3 ≈ 2 days · P4–5 ≈ 1 day. Total ~7–8 working days, each phase independently shippable and tested.