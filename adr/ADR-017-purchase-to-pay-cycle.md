# ADR-017: Purchase-to-Pay Document Flow

**Status:** Accepted  
**Date:** 2026-07-27  
**Deciders:** Architecture Team  

**References:**
- [ADR-006: Document-Centric Architecture](./ADR-006-document-centric.md) — document lifecycle pattern
- [ADR-008: Multi-Level Approval](./ADR-008-approval-hierarchy.md) — approval chain per doc type
- [ADR-018: RFP Document Model](./ADR-018-rfp-document-model.md) — central AP document
- [ADR-022: P2,500 Threshold Rule](./ADR-022-p2,500-threshold-rule.md) — RFP vs PCF boundary

---

## Context

AP shadow (Days 4-6) revealed the complete Purchase-to-Pay document chain. Unlike AR (which has a short 3-step flow of Payment → AR → Ledger), AP involves an 8+ step chain spanning three departments (Procurement, AP, Treasury):

```
Requestor Dept                AP (Che)                 Treasury (Quibs)
    │                           │                           │
    ▼                           ▼                           ▼
  PR ──→ PO ──→ RR/Goods Received
                │
                ▼
          Supplier Invoice
                │
                ▼
         RFP Created (with JE)
                │
                ▼
         Checker (Alywin)
                │
                ▼
         Acctg Manager
                │
                ▼
         Finance Manager
                │
                ▼
         CONSO (Consolidation)
                │
                ▼
         Accounting Head Review ──────→ Check Voucher
                                              │
                                              ▼
                                         CNR Sign (if > threshold)
                                              │
                                              ▼
                                         Check Release / Payment
```

**Key observations from AP shadow:**
1. RFP is created by Che based on supplier invoices and supporting docs
2. RFP already contains the journal entry (JE is part of the RFP form)
3. After all approvals, RFPs are consolidated into a CONSO sheet
4. Accounting Head reviews the CONSO batch before forwarding to Treasury
5. Treasury (Quibs) creates the Check Voucher and processes payment
6. PCF (below P2,500) follows a separate, shorter path through Quibong

**Bottlenecks identified:**
- Inventory late submissions cause RFP creation delays
- Walk-in PCF without supporting docs creates categorization issues
- Manual CONSO consolidation is an extra step

---

## Decision

The Purchase-to-Pay cycle is modeled as a linear document pipeline with status tracking:

### Document States

| Document | States | Notes |
|----------|--------|-------|
| PR | Draft → Submitted → Approved → Closed | Originates from any dept |
| PO | Draft → Submitted → Approved (CNR) → Closed | One PO can have multiple RRs |
| RR | Draft → Submitted → Verified → Closed | Links to PO, triggers inventory |
| RFP | Draft → Submitted → Checked → Acctg Approved → Fin Approved → CONSO'd → Posted | Central AP document; carries JE |
| CONSO | Open → Submitted → Reviewed → Closed | Batches multiple RFPs |
| CV | Draft → Submitted → Approved (CNR) → Released → Cleared | Payment execution |

### Flow Rules

1. **RFP cannot be created without** at minimum a supplier invoice or supporting docs
2. **CONSO is a batch** — multiple RFPs are grouped for Accounting Head review
3. **Check Voucher references** the RFP/CONSO it pays
4. **Payment clears** when bank statement confirms (Quibs domain)
5. **RFP and PCF are mutually exclusive** based on P2,500 threshold (see ADR-022)

### Segment Handling

RFP items can belong to different segments. Each RFP line specifies its segment. A single RFP can have mixed segments (e.g., DHPP fuel expense + OPS service expense).

---

## Consequences

### Positive
- Complete audit trail from request to payment
- Bottleneck visibility (which step has pending items)
- Automated CONSO consolidation from approved RFPs
- Clear handoff points between departments

### Negative
- 8+ step flow is complex — requires good UI/UX to prevent user frustration
- Status tracking must handle partial approvals and rejections at any step

### Neutral
- PCF path is a separate simplified flow (see ADR-022)
- CONSO is an internal document — may be absorbed into a "batch approval" feature

---

## Implementation scope & out-of-scope (UAT Sept 2026)

The full document chain above is the **target** design. For the September-2026
daily-cycle UAT the **wired UI ends at RFP → CONSO → CV**; the upstream
procurement documents are recorded for later consideration, not yet built:

| Document | Built in UI? | Notes |
|----------|:---:|-------|
| PR | No | Out of scope — dept requisition entry, not yet wired |
| PO | No | Out of scope — no purchase-order screen |
| RR / Goods Received | No | Out of scope — goods receipt, ties to inventory |
| Supplier Invoice | No | Out of scope — invoice data enters via the RFP form |
| RFP | **Yes** | Central AP doc; carries the JE and approval chain |
| CONSO | **Yes** | Batch approval/posting of approved RFPs |
| CV | **Yes** | created → signed (COO) → released (staff/treasury) → cleared (head) |

**Consideration for later:** add PR/PO/RR (and optionally Supplier Invoice)
screens to complete the procure-to-pay chain upstream of the RFP. This is
tracked as future work; it does not block the daily-cycle UAT.
