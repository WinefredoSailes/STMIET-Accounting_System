# ADR-002: No Force Balance

**Status**: Accepted
**Date**: 2026-07-18
**Decision**: The system shall never allow artificial balancing of journal entries.

## Context
During the workshop, the accounting team explicitly stated:
> "must not have a feature that allows FORCE BALANCE."
Their most common errors are wrong accounts and typos. A force-balance feature would silently hide these errors by adding compensating entries, making them invisible until reconciliation fails.

## Decision
Journal entries must always balance naturally. If debits ≠ credits, the entry is rejected with a clear error. No auto-balance, no force-balance, no rounding adjustments.

## Consequences
- Error detection is immediate, not deferred to month-end
- Requires proper training on double-entry accounting
- Slightly stricter entry workflow — but fewer silent errors
