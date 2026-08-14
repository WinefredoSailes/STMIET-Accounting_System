# ADR-001: Accounting Architecture Vision

**Status**: Accepted
**Date**: 2026-07-18
**Decision**: Build an integrated Accounting Domain as part of a modular Enterprise Platform, not a standalone accounting application.

## Context
The discovery workshop confirmed the accounting team manages 4 business segments (DHPP, DMIE, OPS, corporate) across 392 accounts. Workflows span Inventory (separate system), Fleet, Payroll, Procurement, Sales, and Fixed Assets. A standalone accounting app would create data silos.

## Decision
The accounting domain will be built as a modular Django monolith with clear bounded contexts. Each operational module emits domain events consumed by the accounting engine. The engine applies posting rules to create journal entries, update the general ledger, and drive financial reports.

## Consequences
- Operational modules (Inventory, Fleet, etc.) must integrate via API/events
- Posting rules are centralized, not duplicated per module
- Future microservice extraction is possible per bounded context
