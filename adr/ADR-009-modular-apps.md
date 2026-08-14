# ADR-009: Modular Django Apps per Bounded Context

**Status**: Accepted
**Date**: 2026-07-18
**Decision**: Each accounting bounded context is a separate Django app.

## Context
The workshop naturally revealed these bounded contexts: Foundation (COA/JE/GL), AR, AP, Cash, Inventory, Fleet, Payroll, Fixed Assets, Tax, Reporting.

## Decision
Each context is a Django app with its own models, services, serializers, and tests. Shared kernel (Company, Segment, Account, PostingRule) lives in a `core` app. Apps communicate via service calls or domain events.

## Consequences
- Clear module boundaries
- Teams can work in parallel
- Apps can be extracted to microservices if needed
- Requires disciplined management of cross-app dependencies
