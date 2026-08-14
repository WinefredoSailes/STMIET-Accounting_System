# ADR-007: Centralized Customer Master

**Status**: Accepted
**Date**: 2026-07-18
**Decision**: Customer master data lives in the accounting system, not the inventory system.

## Context
The current inventory system has a partial customer list. Accounting needs a complete customer ledger for AR tracking, aging, and reporting. The workshop confirmed this is a major pain point.

## Decision
The accounting system maintains the authoritative Customer master. The inventory system (and any other operational system) references customers via API. A one-time migration/cleanup will populate the initial customer list.

## Consequences
- Customer data is consistent across systems
- AR module has complete customer context
- Requires API contract between accounting and inventory systems
- Initial data cleanup effort needed
