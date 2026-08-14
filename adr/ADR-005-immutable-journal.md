# ADR-005: Immutable Journal Entries

**Status**: Accepted
**Date**: 2026-07-18
**Decision**: Posted Journal Entries are immutable. Corrections require reversal.

## Context
Audit trail integrity is critical. The accounting head (Alywin) validates all entries. Edits after posting would destroy auditability. Current practice already uses reversal entries for corrections.

## Decision
Once a JE is posted, no field can be edited. Corrections require a reversal entry (linked to the original) then a new correct entry. System maintains the full audit chain.

## Consequences
- Clear audit trail from original → reversal → correction
- Slightly more work for corrections, but audit-proof
- Reversal entries are clearly marked and reportable
