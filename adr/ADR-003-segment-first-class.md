# ADR-003: Segment as First-Class Dimension

**Status**: Accepted
**Date**: 2026-07-18
**Last Updated**: 2026-07-27
**Decision**: Segment (DHPP, DMIE, OPS, STPC) is a first-class dimension on every accounting transaction.

## Context
The COA uses segments as part of account codes (suffix 00/03/06 for DHPP/DMIE/OPS). AP shadow and workshop reveal a fourth distinct segment:

| Segment | COA Suffix | Business | Status |
|---------|-----------|----------|--------|
| DHPP | 00 | Distribution & Hauling of Petroleum Products | ✅ Active |
| DMIE | 03 | Industrial Equipment / Machinery | ✅ Active |
| OPS | 06 | Operations / Services | ✅ Active |
| STPC | (none) | Seven-Trent Petroleum Corp. (sister company) | ⚠️ No dedicated suffix |

**Gap identified:** STPC has no dedicated COA suffix. Transactions use accounts within DHPP range (e.g., 15500 Due from Other Cos. - DHPP). This works for intercompany but prevents STPC from having its own P&L in the current COA structure.

Transactions can belong to multiple segments (e.g., salary allocated across DHPP, DMIE, OPS). Segments cannot change after posting.

## Decision
Every journal entry line, general ledger balance, and financial report is segment-aware. Multi-segment transactions use a separate allocation mechanism. Segment is immutable after posting.

**On STPC:** STPC is a cross-segment entity — it acts as both a customer (fuel purchases from DHPP) and an intercompany counterparty. Rather than requiring a separate COA suffix, STPC transactions are modeled as intercompany within the DHPP segment, using dedicated GL accounts (15500 Due from, 25500 Due to). If STPC requires independent P&L reporting in the future, a suffix (e.g., 09) can be added to the COA structure.

## Consequences
- 4x (effectively 3 operational + 1 intercompany) GL record dimensions per period
- Reporting requires segment roll-up, drill-down, and intercompany elimination
- Allocation rules needed for shared expenses (salaries, rent, utilities)
- STPC intercompany accounts must reconcile separately
