# ADR-019: AP Numbering Convention

**Status:** Accepted  
**Date:** 2026-07-27  
**Deciders:** Architecture Team  

**References:**
- [ADR-015: Acknowledgment Receipt Sequence](./ADR-015-acknowledgment-receipt-sequence.md) — AR numbering (YYYY-SEQ with gap tracking)
- [ADR-018: RFP Document Model](./ADR-018-rfp-document-model.md) — RFP uses A#### numbers

---

## Context

AP shadow and RFP Templates revealed two numbering systems in AP:

### Current AP Numbering

**Format:** `A####` (e.g., A0001, A0002, A0003...)

The "A" prefix distinguishes AP documents from AR documents (AR# on Acknowledgment Receipts).

### Gap Tracking via "LAST AP"

Every RFP template includes a **"LAST AP"** field showing the previous RFP number for that vendor:

| Vendor | Current RFP | LAST AP | Gap |
|--------|------------|---------|-----|
| PLDT | A0025 | A0018 | A0019-A0024 used by other vendors |
| ZANECO | A0019 | A0012 | A0013-A0018 used by other vendors |
| Motorpool | A0028 | A0020 | A0021-A0027 used by other vendors |

The "LAST AP" is a **per-vendor** tracking mechanism. Since AP numbers are sequential across all vendors (not per-vendor), the LAST AP helps a user find the previous payment to the same vendor.

### Current Pain Points

1. Manual tracking — "LAST AP" is typed manually on each new RFP
2. No system enforcement — gaps could exist unnoticed
3. No per-vendor sequence visibility without scanning all RFPs
4. Paper-based AR forms (Acknowledgment Receipts) are pre-numbered differently from RFP forms

### Contrast with AR Numbering

AR (ADR-015): `YYYY-SEQ` (yearly reset, year prefix, gap tracking)
AP (this ADR): `A####` (sequential, no year prefix, per-vendor gap tracking via LAST AP)

---

## Decision

AP numbering retains the current `A####` format but adds system-enforced gap tracking.

### Numbering Rules

1. **Format:** `A` followed by 4-digit zero-padded sequence (A0001, A0002, ..., A9999)
2. **Scope:** System-wide sequential (not per-vendor, not per-segment)
3. **Reset:** No automatic reset — continues indefinitely. A9999 wraps to A0000 with a warning.
4. **Gap policy:** Gaps are allowed (for voided/cancelled RFPs). System tracks gaps in a `NumberGap` table.
5. **LAST AP:** System automatically tracks the last RFP# per vendor. No manual entry needed.

### Gap Tracking Model

```python
class NumberGap:
    prefix: str              # "A"
    skipped_number: str      # e.g., "A0017"
    reason: str              # "Voided", "Cancelled", "Manual gap"
    created_by: User
    created_at: datetime
    filled_by: str           # Later RFP that fills this gap (if any)
```

### System Behavior

- On RFP creation: system assigns next available `A####`
- If no gaps: increment from last used number
- If gaps exist: prompt user "Use next available (A####) or fill gap (A####)?"
- Gap-filling RFPs have a "gap fill" flag
- Reports show gaps in the sequence for audit purposes

### Comparison with AR Numbering

| Feature | AR (ADR-015) | AP (this ADR) |
|---------|-------------|---------------|
| Format | YYYY-SEQ | A#### |
| Prefix | Year (2026-) | A |
| Length | Variable | 5 chars |
| Reset | Yearly | None |
| Gap tracking | Yes (auto-detect) | Yes (auto + manual) |
| Per-vendor tracking | No | Yes (LAST AP) |
| Pre-numbered forms | Yes (paper AR) | No (system-generated) |

---

## Consequences

### Positive
- Automatic numbering — no manual "LAST AP" tracking
- Gap visibility — system shows all gaps and their reasons
- Consistent with existing practice (A#### format retained)
- Per-vendor history automatically maintained

### Negative
- A9999 wrap-around is an edge case requiring handling
- Gap-filling introduces complexity (has to link to original voided RFP if applicable)

### Neutral
- Different format from AR (YYYY-SEQ) — intentional, as AR and AP are separate domains
- Gap reporting becomes an audit feature rather than a manual lookup
