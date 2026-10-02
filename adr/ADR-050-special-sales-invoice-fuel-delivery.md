# ADR-050: Special Sales Invoice — Fuel Delivery (SSI)

**Status:** Accepted
**Date:** 2026-10-02
**Deciders:** Finance Head (requestor), Architecture Team

**References:**
- [ADR-002: No Force-Balance](./ADR-002-no-force-balance.md) — unbalanced entries surface the difference, never auto-adjust
- [ADR-004: Event-Driven Posting](./ADR-004-event-driven-posting.md) — posting rules in DB; document-carried JEs where the document IS the entry
- [ADR-005: Immutable Journal](./ADR-005-immutable-journal.md) — corrections via reversals only
- [ADR-008: Approval Workflow](./ADR-008-approval-workflow.md) — signature authority
- [ADR-018: RFP Document Model](./ADR-018-rfp-document-model.md) — distribution-line Dr/Cr grid precedent
- [ADR-020: AP Approval Matrix](./ADR-020-ap-approval-matrix.md) — the disbursement chain SSI deliberately does NOT copy
- [ADR-032: Voucher Format Specification](./ADR-032-voucher-format-specification.md) — numbering + form control
- [ADR-033: JE Approval Gate](./ADR-033-je-approval-gate.md) — threshold gate SSI posts through
- [ADR-047: Per-User Screen Access](./ADR-047-per-user-screen-access.md) — screen gate + grant editor
- [BUSINESS-EVENT-CATALOG.md](./BUSINESS-EVENT-CATALOG.md) — §1b events S1–S4

---

## Context

The Finance Head requested a **Special Sales Invoice intended for Fuel Delivery
only**, with four line items:

1. Customer
2. Sales Invoice (generated)
3. Delivery Receipt No.
4. Account Distribution (COA, Account Name, Default Segment, Cost Center,
   Description, Debit, Credit)

plus three behaviors: (a) every user entry goes to the Accounting Head for
approval, (b) the user can print / export Excel / PDF, (c) approved entries
flow to the General Journal, Ledger, Trial Balance, etc.

The existing Sales Invoice (`ARInvoice`) cannot carry this: its lines are
product/quantity/price rows with a fixed 2-line revenue JE (Dr AR/Unearned |
Cr Sales), it has no delivery-receipt reference, and no manual distribution.
The existing distribution-grid documents (RFP, AR receipt, Billing) each serve
a different domain (disbursement, collection, intercompany).

## Decision

A new standalone document, the **Special Sales Invoice (SSI)**, owned by the
`ar` bounded context (fuel delivery is a sale to a customer):

- **Header:** auto-generated `SSI-{YYYY}-{SEQ:05d}` number (own
  `DocumentSequence` `form_code="SSI"`, so `JournalEntry.entry_no` — which is
  the invoice number — can never collide with an `SI-` number), `Customer` FK
  (approved customers only, via the existing `require_approved` gate),
  free-text **Delivery Receipt No.** (the driver's paper number; non-unique,
  never routed through the sequence registry — same rationale as the receipt's
  `ref_po_no`), date, segment, notes.
- **Lines:** an explicit Dr/Cr **Account Distribution grid** shaped exactly
  like `AcknowledgmentReceiptLine` (account → COA code + name, per-line
  default segment, cost center, description, debit XOR credit). The posted JE
  is built **exactly from the lines as entered** (the RFP/CONSO rule,
  ADR-018).
- **Lifecycle (simple Head-approval family, same as SI / AR receipt / JE /
  Billing / Assets):** `draft → submitted → posted`, rejection with mandatory
  note returns to `draft`. The 4-level RFP/PO chain (ADR-020) is a
  *disbursement* control and does not apply to a sales document.
- **Posting:** on Head approval the JE (`source_doc_type="SSI"`,
  pre-set `APPROVED` so the ADR-033 threshold gate passes) is built from the
  lines and posted via `PostingService.post`, which projects `GeneralLedger`
  rows — General Journal, Ledger, Trial Balance, and statements follow with
  no further step (all GL-derived).
- **Invariants:** Dr total must equal Cr total at create/edit/submit/approve
  (ADR-002, surfaced never adjusted); only the preparer may submit; only
  drafts are editable (preparer or Head); approval requires the `head` role;
  the document never creates an `ARInvoice` and never enters aging or the
  receipt apply-to picker.
- **Outputs:** `ssi_print.html` + ReportLab builder (`ACCTG-FOR-SSI Rev 00`)
  + `TableSpec` xlsx/csv export — requirement (b).
- **Access (ADR-047):** screen `ssi_list` under Receivables (AR), `ssi_`
  prefix, `ssi_approve`/`ssi_reject` inbox actions, `special-invoices` API
  slug, nav entry, `ssi_queue` in the approvals inbox. The user-management
  grant editor picks the screen up with zero template changes (registry-driven).

## VAT trajectory (deferred, designed for)

Output VAT is entered today as an ordinary **credit distribution line** (the
same way RFP carries WHT). Automatic VAT extraction (the `tax.si.extracted
→ VATComputation` path) is a likely follow-up; it was deliberately NOT built
now. The hook is documented: `VATComputation.invoice` is currently a
`OneToOne` to `ARInvoice`, so auto-extraction for SSI will need either a
nullable `ssi` OneToOne or a generic `(content_type, object_id)` source — a
small, isolated migration when the Finance Head asks for it. The SSI `total`
and its lines stay separate from the JE precisely so extraction never has to
unpick a posted entry.

## Consequences

- Fuel-delivery sales no longer masquerade as regular SIs or manual JEs; the
  DR number is captured at source instead of living on paper only.
- One more register in Receivables (AR); staff training is one screen because
  every behavior mirrors the SI/receipt flow.
- The Phase-0 audit bundled with this change also repaired four pre-existing
  RBAC gaps (supplier/asset inbox actions, the `analytics` orphan screen, the
  root-mounted assets API path) and added reverse-completeness guard tests so
  future screens cannot ship unregistered.
