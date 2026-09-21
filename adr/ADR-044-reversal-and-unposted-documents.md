# ADR-044: Reversal Workflow & Unposted Documents

**Status:** Accepted
**Date:** 2026-09-19
**Deciders:** Architecture Team

**References:**
- [ADR-004: Immutable Journal](./ADR-004-event-driven-posting.md) — append-only, corrections by reversing entry
- [ADR-005: GL derivation](./ADR-005-immutable-journal.md) — balances are derived from the GL projection
- [ADR-013: Cycle-based ledger](./ADR-013-cycle-based-ledger.md) — entries belong to a Tue–Mon cycle
- [ADR-043: Unified System Experience](./ADR-043-unified-system-experience.md) — one document shape

---

## Context

Two gaps confused users and risked the books:

1. **Posted entries could not be corrected end to end.** `PostingService.reverse`
   existed and was unit-tested, but the UI action was a stub, it allocated the
   reversal to the *next* cycle even when the current period was open, and GL
   readers filtered `entry__status="posted"` — so a REVERSED original dropped
   out of the balance and the contra double-counted instead of netting to zero.
   Nothing propagated to the source document (RFP/CV/AR/Transfer/…) or to
   stored summaries (PO balances, AR invoice status, cash cycles).

2. **Unposted documents were invisible.** Approved RFPs / open CONSO batches /
   approved PCF replenishments have no `JournalEntry` until they post, so they
   never appeared on the Journal Entries register. Users could not tell where a
   document "went". Separately, a rejected CV/RFP could be corrected through the
   generic JE editor, bypassing the document's own approval flow.

## Decision

### 1. Corrections are maker-checker reversals — never deletes

A posted entry is corrected by a **reversing entry**:

```
requested  (preparer/accounting user, reason required)
   ↓ head approves                     ↓ head rejects (note required)
approved  → mirror REV- entry posted    entry stays POSTED
```

- Modelled by `posting.ReversalRequest`; audited as `ActionLog.DocType.JE`.
- The original is marked `REVERSED`; both entries keep their GL rows.
- Posted entries remain physically undeletable (PROTECT FKs, admin no-delete,
  no API destroy).

### 2. Reversal posts to the current open cycle

The reversing entry is dated to the current open cycle; it advances to the
first day of the next cycle **only when the current cycle is locked**. This
keeps the cycle-based ledger (ADR-013) netting in the open period without
restating a locked one.

### 3. GL readers sum POSTED **and** REVERSED

`GL_EFFECTIVE_STATUSES = (POSTED, REVERSED)` is the single source of truth for
every balance reader (trial balance, ledger, book balance, statements, cash
cycle, PCF trigger). The original (+X) and its mirror (−X) therefore net to
zero automatically.

### 4. Reversal propagates to the source document + derived data

On approval, `mark_source_reversed`:

- **Document ledgers exclude reversed documents** — a reversed RFP drops out of
  the PO `billed_amount`/`available_amount`, AP/supplier ledgers; a reversed AR
  collection drops out of the invoice's `amount_paid`, and the invoice is
  re-opened (`open`/`partially_paid`/`paid`).
- **Open cash cycles regenerate** so the contra is reflected; locked cycles are
  never touched.
- Source documents show a **"Reversed"** banner linking to the reversing entry.

### 5. Unposted documents are shown as a pipeline, not as fake JEs

The Journal Entries screen gains a **Pending / Unposted** tab (plus a dashboard
count) listing RFP / CONSO / PCF documents that have no JE yet, linking to the
owning module. (AP pipeline first; AR/payroll/depreciation follow the same
pattern.)

### 6. Rejected documents return to their own module

A rejected document stays trackable and revisable **in its own list and
detail** (RFP, PO, CV, Transfer): the register row and detail page show the
rejection note and a **Revise** action for the preparer. A JE that belongs to a
source document may **not** be edited, submitted, approved or posted through
the generic Journal Entries module — those views redirect to the owning
document. The generic JE editor is reserved for manual entries.

## Consequences

### Positive
- Posted history is preserved and corrections are auditable end to end.
- Balances net to zero automatically; no reader can silently drop a reversal.
- Users always find a document where they expect it (its own module / pending tab).
- The generic JE module can no longer bypass a document's approval flow.

### Negative / trade-offs
- Additional models/migrations (`ReversalRequest`, `ActionLog.DocType.JE`) and a
  maker-checker step for corrections.
- Document ledgers must keep excluding reversed documents as new ledgers appear
  (captured by the `*_reversed` checks and property).
- Stored report snapshots (cash flow statement, reconciliation) still refresh on
  their normal generation path; the underlying GL is always correct immediately.

### Neutral
- `PostingStatus.REVERSED` is now meaningful to every balance reader via the
  shared constant. Future readers must use `GL_EFFECTIVE_STATUSES`, not a bare
  `status="posted"` filter.

---

## Verification

Reversal/recompute is covered by `apps/posting/test_reversal.py` and
`apps/posting/test_reversal_recompute.py` (net-zero GL, cycle allocation,
maker-checker, PO balance restore, AR invoice re-open, cash-cycle regen); the
UI flow by `apps/ui/test_reversal_ui.py`; unposted visibility by
`apps/ui/test_pending_documents.py`; and reject-return by
`apps/ui/test_cv_reject_revise.py` and `apps/ui/test_reject_tracking.py`.