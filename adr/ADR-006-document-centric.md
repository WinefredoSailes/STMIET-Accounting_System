# ADR-006: Document-Centric Architecture

**Status**: Accepted
**Date**: 2026-07-18
**Last Updated**: 2026-07-27
**Decision**: The system architecture revolves around business documents, not accounting screens.

## Context
The workshop confirmed accounting doesn't start with accounting — it starts with documents. AP shadow detailed the complete document chain:

```
Purchase Request (PR) → Purchase Order (PO) → Receiving Report (RR)
    → Supplier Invoice → RFP (ACCTG-FOR-012) → CONSO (Consolidation Sheet)
    → Accounting Head Review → Check Voucher → Payment
```

Key document types identified:

| Document | Form Ref | Domain | Key Field |
|----------|----------|--------|-----------|
| Purchase Request | Internal | Procurement | PR# |
| Purchase Order | Internal | Procurement | PO#, Vendor |
| Receiving Report | Internal | Inventory | RR#, Qty Received |
| Supplier Invoice | External | AP | Invoice#, Amount |
| **RFP** | **ACCTG-FOR-012** | **AP** | **RFP#, A####, Purpose** |
| **CONSO** | Internal Sheet | **AP** | **Consolidated RFP batch** |
| Check Voucher | Bank Form | Treasury | CV#, Payee, Amount |
| Acknowledgment Receipt | ACCTG-FOR-005 v3 | AR | AR# (YYYY-SEQ) |

Every workflow traces through documents. The RFP is the central AP document — it carries the JE, the approval signatures, the supporting attachments, and the "LAST AP" number for gap tracking.

**P2,500 threshold:** Below P2,500 uses Petty Cash Voucher (PCF handled by Quibong). P2,500 and above uses RFP (ACCTG-FOR-012). This threshold determines which document type initiates the payment workflow.

## Decision
Each operational module implements the full document lifecycle (Draft → Submitted → Approved → Posted → Closed). Documents are the source of truth. The accounting engine observes document state changes and generates JEs.

The document flow has two primary paths:

### Path A: RFP (P2,500 and above)
```
RFP Draft → Submitted → Checker (Alywin) → Acctg Manager → Finance Manager
    → CONSO → Accounting Head → Treasury (Quibs) → Check Voucher → Payment
```

### Path B: Petty Cash Voucher (below P2,500)
```
PCV → Approval → Quibong (Custodian) → PCF Disbursement → Replenishment
```

### Path C: Acknowledgment Receipt (Collection)
```
Payment Received → AR Issued → Customer Ledger → MONITORING Sheet
    → Cycle End → Collection JE Summary → Accounting
```

## Consequences
- UI is organized around document types (RFP screen, PCV screen, AR screen)
- Approval workflow is document-based with doc-type-specific chains
- Document status drives what actions are available
- RFP carries dual nature: it is both approval document AND JE template
- P2,500 threshold is a configurable system parameter, not hardcoded
