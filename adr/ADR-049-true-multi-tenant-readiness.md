# ADR-049: True Multi-Tenant Readiness (Company-as-Tenant)

**Status:** Proposed
**Date:** 2026-09-29
**Deciders:** Architecture Team

**References:**
- [ADR-037: Multitenant SaaS Architecture](./ADR-037-multitenant-saas-architecture.md) — direction (shared-DB row-level); this ADR makes it executable
- [ADR-003: Segment as First-Class Dimension](./ADR-003-segment-first-class.md) — segment suffix rule, STPC gap
- [ADR-011: Multi-Segment Data Architecture](./ADR-011-multi-segment-architecture.md) — segment-level tenant-awareness (predecessor)
- [ADR-013: Cycle-Based Ledger](./ADR-013-cycle-based-ledger.md) — per-company cash cycle (already `Company.cash_cycle`)
- [ADR-019: AP Numbering Convention](./ADR-019-ap-numbering-convention.md) — RFP `A####` vs observed variants
- [ADR-020: AP Approval Matrix](./ADR-020-ap-approval-matrix.md) — 4-level chain, CNR threshold
- [ADR-022: P2,500 Threshold Rule](./ADR-022-p2,500-threshold-rule.md) — RFP vs PCV gate
- [ADR-032: Voucher Format Specification](./ADR-032-voucher-format-specification.md) — `ACCTG-FOR-010/002` revisions (seed source for Tenant-1)
- [ADR-018: RFP Document Model](./ADR-018-rfp-document-model.md) — `ACCTG-FOR-012 Rev 00 eff 11.16.2024` (seed source)
- [ADR-033: Payroll GL Feed](./ADR-033-payroll-gl-feed.md) — feed + WHT path (rate-free by design)
- [ADR-040: Deployment on Render](./ADR-040-deployment-render.md) — single container, `MEDIA_ROOT=/var/data/media`
- [ADR-043: Unified System Experience](./ADR-043-unified-system-experience.md) — one canonical shape per concern (this ADR follows that mandate)
- [ADR-047: Per-User Screen Access](./ADR-047-per-user-screen-access.md) — screen gate (tenant membership builds on it)
- [ADR-048: My Profile](./ADR-048-my-profile.md) — avatars in `media/avatars/`, per-user theme (tenant branding builds on it)
- [docs/04-multi-tenant-architecture.md](../docs/04-multi-tenant-architecture.md) — segment-level business doc

---

## Context

ADR-037 (Accepted 2026-09-04) chose shared-database, row-level multi-tenancy
and declared segments a sub-tenant dimension. `PROJECT-CONTEXT.md §10.3`
records it honestly: **"ADR-037 exists, not built."**

A repo-wide audit (2026-09-29, read-only, three parallel sweeps over
`backend/apps/**`, templates, PDF/Excel builders, settings, ADRs) then
established that Tenant-2 as **an entirely different company** (own logo,
name/address/TIN/RDO, CoA, segments-or-none, numbering, form revisions,
fiscal/tax rules, users) is blocked by hardcodings in every layer:

1. **Branding/identity.** `stmiet-trans-logo.png` in 10 print templates
   (`je_print:57`, `ftv_print:57`, `rfp_print:55`, `cv_print:55`,
   `po_print:48`, `si_print:53`, `receipt_print:53`, both ledgers +
   advances) + `ui/pdf.py:61-66 _logo_path()` + 5 PDF call sites;
   `COMPANY_FALLBACK` (`pdf.py:30`), `COMPANY_NAME`
   (`reporting/excel_export.py:33`), `|default:"SEVEN-TRENT…"`
   (`je_print:60`, `ftv_print:60`), fully hardcoded PO blocks
   (`po_print:54-56`, `po_form:24`, `po_detail:144`);
   `E. Bagatua` proprietor in Excel + reporting services;
   `IPPC/STPC/STMIET` column headers in Excel;
   `Company.tin/address/rdo_code` exist but are rendered in **zero**
   templates. `Company` has **no** `logo/phone/proprietor` field.
2. **Form control.** `ACCTG-FOR-012 Rev 00 eff 11.16.2024`,
   `-010 Rev 02 eff 08.18.2022`, `-002 Rev 00 eff 09.24.2024`, `-005`
   are string literals in `pdf.py:31-33,321-325,881,1017,1080`,
   print templates, and form chrome. No `FormRevision` table exists.
   (Incidental bugs found: JE PDF reuses the CV revision; AR receipt
   misuses `transaction_date` as Effective Date.)
3. **Numbering.** `DocumentSequence(company, form_code, year, cost_center)`
   (`sequences/models.py:35`) is correctly scoped and is the reference
   pattern — but callers pass inline `pattern=` inconsistently (RFP callers
   pass **no** pattern, yielding `{YYYY}-SEQ` instead of the documented
   `A####`; `test_e2e:68` seeds `A{SEQ:04d}`, diverging from prod), and
   ~20 `f"…"` fallbacks bypass the registry entirely
   (`CV-{count}`, `RFP-{ap}`, `TRF-{id}`, `PCF-REP-{id}`, `BI-{billing_no}`
   double-prefix, `CLR-/CLE-/APP-/REV-/DEP-/DIS-/PAY-/INV-/ITX-`).
   Every document number (`entry_no`, `ap_number`, `po_number`,
   `batch_no`, `cv_number`, `receipt_no`, `invoice_no`, `billing_no`,
   `asset_no`) is `unique=True` **globally**, so Tenant-2 cannot restart
   at 1. `PCF/FTV voucher_no` are the opposite defect: not unique at all.
4. **Context.** `Company.objects.first()` in ~15 sites
   (`ui/views.py:514,537,1345,1413,1497,1542,3582,3655,4836,4919,5822…`,
   `ui/services.py:86,378,468,2134,2181`, `payroll/services.py:56`,
   seed commands) silently picks Tenant-1. Filtering is manual
   `?company=` (`cash/views.py:241`, `reporting/views.py:33`,
   `ui/views.py:533`). No middleware, auto-filter manager, membership,
   picker, or RLS.
5. **Domain rules.** STMIET CoA maps in code
   (`ar/services.py:46-65` unearned/cash/sales,
   `billing 15550/60`, `12070` advances, `20000/21100` AP,
   `100*` cash picker, inventory prefixes, `64600+0/3/6` tax,
   `30000/30003/30006` capital, reporting `400/410/420…` families);
   `SEGMENT_CHOICES=[DHPP,DMIE,OPS,ALL]` + `segment_for_code 0/3/6` +
   `00/03/06` suffix; `ENTITY STMIET/STPC/IPPC/ALL`;
   thresholds (`CNR 100k`, `JE 100k`, `RFP min 2500` vs tests' `2000`,
   `advance 20000`, `PCF 85%`); `VAT 12%`, `CIT 20% placeholder`;
   `Tue→Mon WD 1/0` (incl. hardcoded JS `je_form:242-243`);
   `PHP/₱`, `Asia/Manila`; 12-bank list; `Dohinob/San Pedro/Office`
   (no `Warehouse` model — spec-only); `AG/OS/TL/HRAC` cost centers
   (**no** `company FK` — cross-tenant leak). Full file:line inventory
   is in the 2026-09-29 audit record (three sweeps); this ADR is the
   normative cut distilled from it.

Two product facts constrain the decision:

- **Media stays on the Render disk** (`MEDIA_ROOT=/var/data/media`,
  `render.yaml:34-35`, `base.py:182-185`). No S3 in this ADR.
- **Each company brings its own form series + revisions.** STMIET's
  `ACCTG-FOR-*` values become Tenant-1 seed rows, never system defaults.

---

## Decision

**`Company` is the Tenant.** The term `Tenant` in ADR-037 binds to the
existing `foundation.Company` model — no parallel `Tenant` table, no
rename. Every later diff cites `ADR-049 §2.x`. Any new code introducing a
hardcoded company artifact fails review. Dual-tenant onboarding (same
document number valid in both tenants, correct logo/name/revision per
tenant) is the acceptance test.

### 2.1 Identity — `Company` becomes a complete tenant profile

Extend `foundation.Company` with: `slug`, `display_name`,
`proprietor` (seed `E. Bagatua` for Tenant-1 only),
`phone/contact_no`, `currency` (default `PHP`), `timezone`
(default `Asia/Manila`), `vat_rate` + `income_tax_rate`,
`rfp_min_amount` (default resolves the 2500-vs-2000 drift),
`cnr_threshold` (default `100000`), `logo`
(`ImageField(upload_to="company_logos/<company_id>/")`),
`favicon` (optional; falls back to logo), `is_active`.

Replace every `COMPANY_FALLBACK`, `COMPANY_NAME`,
`|default:"SEVEN-TRENT…"`, and fully hardcoded name/address blocks
(`pdf.py:30,279,543,877,954,1069`; `excel_export.py:33,102,403,495,588`;
`je_print:60`; `ftv_print:60`; `po_print:54-56,156`;
`po_form:24`; `po_detail:144`) with `company.*`. Fail closed on null
company — never fall back to another tenant's name. Replace every
`E.Bagatua` title (`excel_export:251-252,304,308-309`;
`reporting/services:311,313,504,512,514`) with
`company.proprietor`. Replace `IPPC/STPC/STMIET` Excel headers with a
`Segment.objects.filter(company=company)` loop. Move `STMIET-WSS`
footer and API title/description to settings/env, never per-tenant
constants.

### 2.2 Branding — one dynamic header everywhere

One `form_context(company, form_code)` helper feeds HTML print, ReportLab
PDF, form chrome, sidebar, login, and favicon. All 10
`stmiet-trans-logo.png` templates + `pdf._logo_path()` + 5 PDF call
sites switch to `company.logo` (static `img/logo.svg` remains only as
the pre-login/empty-logo fallback). `Company.tin/address/rdo_code`
(plus new `phone`) render in **every** voucher header — today they are
defined but displayed nowhere. Sidebar/login/favicon show
`company.logo + company.name`; `base.py` API title becomes env-driven.

### 2.3 Media — same disk, tenant-prefixed, auth-checked

Keep `MEDIA_ROOT=/var/data/media`. New layout:
`company_logos/<company_id>/`, `avatars/<company_id>/`
(ADR-048's Pillow pipeline and 256×256 JPEG rule unchanged, path only).
`config/urls.py` media serve gains a tenant-ownership check so Tenant-2
files are never enumerable from Tenant-1. No new disk, no S3, no
`static/`-hosted tenant logos (gitignored `media/` stays).

### 2.4 Forms — per-company series + revisions (no global defaults)

New `CompanyFormRevision(company, form_code, document_no,
effective_date, revision_no, is_active)` with
`UniqueConstraint(company, form_code)`. Seed Tenant-1 from the
authoritative sources (ADR-032 for `-010/-002`, ADR-018 for `-012`,
observed `-005 v3`); Tenant-2 starts **empty** and defines its own —
there is no system-wide fallback revision. `form_context()` resolves
`(doc_no, effective, revision)` per `(company, form_code)` for print,
PDF (`_form_header` + all builders), and form chrome. Fixes the two
incidental bugs as part of the migration (JE revision, AR effective
date).

### 2.5 Numbering — one registry, one pattern source, scoped uniques

New `CompanyNumberPattern(company, form_code, pattern)` with
`form_code` choices (`JE/RFP/PO/CV/CONSO/AR/SI/BD/BILL/PCV/FTV/SU/FA`);
it replaces every inline `pattern=` argument. All allocation goes
through `DocumentSequence.next_number(company, …)` — the ~20 `f"…"`
fallbacks (`ap/views:279`, `ap/services:1117`, `cash/services:403,548`,
`billing/services:260` double-prefix, `CLR-/CLE-/APP-/REV-/DEP-/DIS-/
PAY-/INV-/ITX-`, inbox/export display fallbacks) are deleted, including
in tests (`posting/tests.py:25` helper).
`unique=True` on every document number and on
`Supplier/Customer/Product/Account/BankAccount(code,account_number)/
PettyCashFund/Segment/Asset/CostCenter/PayrollFeed/InventoryEvent`
becomes `UniqueConstraint(company, …)` (via `segment.company` where a
document carries no direct `company FK`). `Company.code` itself stays
global. `PCF/FTV voucher_no` gain per-company uniqueness (reverse fix).
`cost_center` 4th sequence segment stays reserved; no caller passes it
yet.

### 2.6 Masters — per-company data, seeded per tenant

`Segment(code)` → `(company, code)` (Tenant-2 may have 0/N segments or
different names — no `DHPP` default). `CostCenter` gains `company FK`
(leak fix). `Customer/Supplier/Product/Account/Warehouse/BankAccount`
scope to `(company, code)`. All STMIET CoA maps in code
(§Context-5) move to `SegmentAccountMap` + per-tenant
`import_coa --company` (whose `role_codes` seed stays but is namespaced
per tenant). `ENTITY STMIET/STPC/IPPC/ALL` and the suffix rule
`00/03/06` + `segment_for_code` become per-company config/seed, not
code. Importers (`coa/suppliers/customers/banks/cost_centers`) require
explicit `--company` (remove `default="STMIET"`); `import_fixed_assets`
`STMIET` fallback is deleted.

### 2.7 Config — per-company knobs, global workflow keys

`Company` carries `cash_cycle + weekdays` (already), plus
`currency/timezone/vat_rate/income_tax_rate/rfp_min/cnr_threshold`.
`DOMAIN` env values remain as **installation** defaults only.
Role keys `staff/head/coo` stay global (labels configurable per voucher);
person names (Alywin/CNR/custodians) stay seed/demo data, never code.
`core/money.py` 2dp-HALF_UP, `Dr==Cr` (ADR-002), immutable JE + reversal
(ADR-005), BIR form list (PH-only SaaS), and the approval state machine
stay global. The hardcoded JS weekdays (`je_form:242-243`) and `₱`
format helpers read `company` instead.

### 2.8 Request context — kill `objects.first()`, gate by membership

New `UserCompanyMembership(user, company, role, is_default)` +
session `company_id` + `get_active_company(request)` (explicit
`company_id` → membership check → 404 otherwise). Every
`Company.objects.first()` site (§Context-4) migrates to
`request.company` / `segment.company` / explicit arg. List views, admin
changelists, services, and management commands scope by the active
company; login picks the sole company or shows a picker. Super-admin
cross-tenant access is explicit and audited. PostgreSQL RLS is
**deferred** to pre-SaaS (named here so the deferral is deliberate, per
ADR-037's "second layer" note) — middleware + manager + membership are
the enforcing layer in this ADR.

### 2.9 Tenant-boundary rules (resolves 003/011 vs 037 tension)

- **STPC** stays an intercompany counterparty *inside* Tenant-1
  (15500/25500, no suffix) unless/until it is onboarded as its own
  `Company` — promotion is a data migration, never a code branch.
- **Segments consolidate; tenants never do.** The MONITORING-style
  unified view is a *segment* feature inside one company. No
  cross-tenant report, export, close, or sequence exists.

---

## Consequences

### Positive
- Tenant-2 onboarding is data + membership, not a rewrite: create
  `Company`, import its CoA/masters, set its `FormRevision` +
  `NumberPattern` rows, invite users — numbering restarts at 1, prints
  show its brand, its thresholds/tax/cycle apply.
- One canonical dynamic per concern (`form_context`,
  `CompanyNumberPattern`, `get_active_company`) per ADR-043 — new
  modules copy the pattern instead of inventing literals.
- `Company.objects.first()` and cross-tenant fallback names disappear
  as a bug class; dual-tenant test pins it.
- ADR-037's deferred-vs-now line becomes reviewable: anything in §2 is
  "now", anything in §6 is "deferred by name".

### Negative
- One-time migration cost: backfill `company` on all existing rows to
  Tenant-1 (STMIET), alter ~15 unique constraints, re-seed
  `FormRevision`/`NumberPattern`, convert 10+ templates + 5 PDF sites +
  Excel headers, re-point ~15 `first()` sites and ~20 number fallbacks,
  re-parameterize tests asserting `SEVEN-TRENT/stmiet-trans-logo`.
- Per-company CoA/segments mean per-tenant imports and a longer
  Tenant-2 onboarding checklist than "just add a user".
- Tenant-prefixed media + auth-checked serve adds a small per-request
  check; `company_logos/` on the shared disk means disk-full is still a
  shared fate (accepted — §6).

### Neutral
- Single Render container, single Postgres, `MEDIA_ROOT` unchanged
  (ADR-040 untouched). No schema-per-tenant, no DB-per-tenant, no
  per-tenant deploy, no provisioning API, no SaaS billing in this ADR.
- `Company.code` stays globally unique (human key); everything else
  scopes under it.
- BIR form list, 2dp money, immutable journal, role keys stay global —
  Tenant-2 is assumed PH; a country pack is a future ADR if ever needed.

---

## Options Considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **This ADR: Company-as-Tenant + dynamic profile/forms/numbering + scoped uniques + membership context (selected)** | Tenant-2 = different company with zero code change at onboard; single deploy; reversible; reviewable checklist | One-time migration across many tables/templates/tests | **Selected** |
| Schema-per-tenant (django-tenants) | Stronger isolation, per-tenant migrations | Ops complexity, third-party friction, overkill for 1–2 tenants | Deferred (as in 037) |
| DB-per-tenant | Strongest isolation, independent backup | Cost, migration/backup fan-out, unjustified at this scale | Rejected |
| Separate instance per customer | Zero code change now | No shared updates, duplicate ops, kills SaaS path | Rejected (as in 037) |
| Global CoA + per-company map (keep `Account.code` global) | Smaller migration | Permanent STMIET-code tax; Tenant-2 can never own `111`; reporting prefixes stay conditional | Rejected — true per-company rows (§2.6) |
| Parallel `Tenant` table alongside `Company` | ADR-037 literalism | Two tenant concepts, FK sprawl, rename churn | Rejected — bind `Tenant == Company` (§2) |
| RLS now as the enforcing layer | Defense in depth immediately | Policy-per-table rollout before the app layer is clean; masks `first()` bugs instead of killing them | Deferred by name (§2.8) |

---

## Implementation Checklist (build order; no code in this ADR)

- [ ] `Company` fields: `slug/display_name/proprietor/phone/currency/timezone/vat_rate/income_tax_rate/rfp_min/cnr_threshold/logo/favicon/is_active` + migration + admin
- [ ] `CompanyFormRevision` + `CompanyNumberPattern` + `form_context()` + `get_active_company()` + `UserCompanyMembership` + migrations
- [ ] Media: `company_logos/<id>/`, `avatars/<id>/`, auth-checked serve; migrate existing avatars; keep `MEDIA_ROOT`
- [ ] Backfill `company` → STMIET on all legacy rows; convert uniques to `(company, …)` (§2.5–2.6); `CostCenter.company FK`; `Warehouse` decision recorded (build minimal vs formal defer)
- [ ] Convert all print templates + PDF builders + Excel headers + sidebar/login/favicon + form chrome to `form_context`/`company.*`; delete `COMPANY_FALLBACK/COMPANY_NAME/DOCUMENT_*/|default:"SEVEN-…"` + `stmiet-trans-logo` refs (keep `logo.svg` pre-login fallback only)
- [ ] Route every number through `DocumentSequence` + `CompanyNumberPattern`; delete all `f"…"` fallbacks and inline patterns; fix `RFP A####` divergence; fix JE-revision and AR-effective-date bugs
- [ ] Replace every `Company.objects.first()` + bare `?company=` with membership-checked active company; scope views/services/commands/admin; login picker; remove `--company default="STMIET"`
- [ ] Per-company seed: `FormRevision` (from ADR-032/018), `NumberPattern`, segments, CoA/`SegmentAccountMap`, banks, cost centers, custodians — Tenant-1 re-seeded, Tenant-2 dummy onboarded
- [ ] Tests: dual-tenant test (same number in both tenants; per-tenant logo/name/revision asserts); re-parameterize all `SEVEN-TRENT/stmiet-trans-logo` asserts to `company.*`
- [ ] Docs: mark ADR-037 checklist items superseded-by-049 where applicable; close the 2500-vs-2000 and JE-revision drifts in their source ADRs/specs

**Do not build Tenant-2 features behind this ADR's back.** Until the
checklist is done, the system is single-tenant; §10.3 pricing ("not
built") remains the commercial truth.

---

## Open / Deferred (deliberately out of this ADR)

- PG RLS second layer, per-tenant quotas/backups, provisioning API, SaaS billing/metering, cross-tenant reporting — deferred to pre-SaaS, same line as ADR-037.
- S3 migration, Redis/Celery, per-tenant deploy/K8s — untouched.
- Country pack (non-PH Tenant-2), multi-currency revaluation, BIR form-PDF per tenant — future ADRs if ever needed.
- Ratification choices embedded as recommendations: per-company `Account` rows over global+map (§2.6), middleware+membership now with RLS deferred (§2.8), Tenant-1 seeds verbatim with Tenant-2 empty (§2.4). Flipping any of them amends this ADR, not the code first.
