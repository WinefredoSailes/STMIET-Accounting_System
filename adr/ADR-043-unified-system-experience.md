# ADR-043: Unified System Experience

**Status:** Accepted
**Date:** 2026-09-19
**Deciders:** Architecture Team

**References:**
- [ADR-006: Document-Centric Model](./ADR-006-document-centric.md) — documents as first-class
- [ADR-008: Approval Hierarchy](./ADR-008-approval-hierarchy.md) — the approval matrix
- [ADR-018: RFP Document Model](./ADR-018-rfp-document-model.md) — the reference AP flow
- [ADR-030: Cash Short & Inter-Account Borrowing](./ADR-030-cash-short-inter-account-borrowing.md) — transfers
- [ADR-032: Voucher Format Specification](./ADR-032-voucher-format-specification.md) — printed forms
- [ADR-036: UI Frontend Decision](./ADR-036-ui-frontend.md) — server-rendered UI + HTMX
- [ADR-039: Folder Structure & Template Partials](./ADR-039-folder-structure-and-template-partials.md) — shared partials

---

## Context

The system grew module by module. Each new document (RFP, PO, Check Voucher,
Journal Entry, Petty Cash, Inter-Account Transfer, AR receipt…) was built when
it was needed, and frequently invented its own shape:

- some documents had a dedicated detail page, others linked straight to the
  generic JE page;
- some had submit/approve/reject/revise, others only approve;
- some had an audit trail, others had none;
- some list screens had search/filters, others did not;
- print layouts used inconsistent grids (a shipped FTV header even produced a
  28-column table because its rowspans did not fit the declared 14-column
  grid);
- dropdowns were sometimes plain `<select>`, sometimes type-ahead;
- exports existed for some documents and not others.

The result is a system that works, but where the *experience* — and the code —
differs from screen to screen for no business reason. Users must relearn each
screen, and every new module pays the cost again.

## Decision

Adopt **unification as the default engineering mindset**: where a concern is
shared across the system, there is **one canonical way to do it**, and new work
copies that way. This ADR records the mandate; it does not require a big-bang
migration.

### 1. One document shape

Every approval-tracked document follows the same lifecycle and code shape:

```
requested/prepared → submitted → approved (the only GL-post gate)
                            └── rejected → revise → resubmit
```

and is assembled from the same parts:

| Concern | Canonical implementation |
|---|---|
| Service | `apps/<ctx>/services.py` — `create` / `submit` / `approve` / `reject` / `revise` |
| Audit | `apps.ap.models.ActionLog` entry on every transition (`DocType.*`) |
| Inbox | `*_queue()` in `apps.core.approvals` → "My Approvals" |
| Detail | `ui/partials/document_shell.html` + `*_timeline()` + `workflow_actions.html` + `audit_trail.html` |
| Actions | one `ui/partials/workflow/<type>_actions.html` (the only status → button branch) |
| Exports | per-document PDF/XLSX/CSV via `apps.core.exports.table_export` |
| Lists | `apps.ui.filter_specs` + `filter_bar.html`; exports honour active filters |
| Print | fixed-column voucher grid; every row's spans fit the grid exactly |

### 2. One experience vocabulary

Consistent across screens: forms, detail/voucher layouts, print payouts,
dropdown search, filters/search, date-range filters, approval actions, status
badges, timeline, audit trail, export set, and empty-state text.

### 3. Maintainable by construction

Prefer shared partials, the shared filter/export engines, and the shared
service shape over per-screen one-offs. Comments explain *why*, tests pin
behaviour. No duplicated logic when an engine already exists.

### 4. Converge incrementally, keep the suite green

Not everything is unified today. We converge a screen **when it is next
touched** (or when the divergence causes real pain). Every unification change
must keep the full test suite green (`pytest`), and must not regress an
already-unified flow. Divergences that remain are acknowledged, not hidden.

## Consequences

### Positive
- Users learn one flow and one layout; new staff onboarding is faster.
- New modules are cheaper and less error-prone (copy the pattern).
- Fewer one-off bugs (e.g. the FTV column-overflow class of defect is caught
  by a shared invariant test).
- Tests and code review get a checklist: does it match the canonical shape?

### Negative
- Converging existing screens is rework that competes with feature work.
- The canonical shape must itself evolve carefully; changing it touches many
  screens at once.
- Some documented divergences will remain for a while.

### Neutral
- The mandate is directional: "unify as needed", not "pause all work to
  refactor". The current reference implementation for a non-AP document is
  Inter-Account Transfer (ADR-030), which now mirrors RFP/JE/CV end to end.
- Future ADRs may refine individual targets (e.g. a date-range filter standard)
  without changing this mandate.

---

## Status of unification (snapshot, 2026-09-19)

Reference: **Inter-Account Transfer** was brought to full parity — dedicated
batch form, detail shell + timeline + workflow actions + audit trail,
PDF/XLSX/CSV exports, search + status/from/to filters, submit/approve/reject/
revise, and a corrected 14-column FTV print/PDF grid (regression-tested). Full
suite: 707 passed, 3 skipped.

Known remaining divergences to converge opportunistically: plain vs.
type-ahead dropdowns, presence/absence of date-range filters on some registers,
and a handful of list screens still without the shared filter bar. Each is
tracked informally and addressed when the screen is next modified.