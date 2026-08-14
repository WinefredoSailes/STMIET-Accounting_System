# ADR-004: Event-Driven Posting Engine

**Status**: Accepted
**Date**: 2026-07-18
**Decision**: Posting to the General Ledger is event-driven, not screen-driven.

## Context
Every accounting entry originates from a business event: a sale, a purchase, a payroll run, a fuel delivery, a collection. The Acctg-Entry-finance-and-acctg.xlsx already documents the exact event-to-JE mapping. Manual posting causes typo errors and delays.

## Decision
Operational modules emit domain events. The Posting Engine listens, matches events to PostingRules, and creates Journal Entries automatically. Manual JEs are still possible (for adjustments) but require accounting-head approval.

## Consequences
- Reduces manual data entry errors
- Requires well-defined PostingRules (already documented)
- Event schema must be agreed across modules
