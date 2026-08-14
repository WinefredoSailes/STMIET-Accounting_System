# ADR-033: Payroll as Independent System — GL Feed Contract

**Status:** Accepted
**Date:** 2026-08-14
**Deciders:** Architecture Team (per build-vs-buy gate, ADR-025)

**References:**
- [ADR-025: Build vs Buy Decision](./ADR-025-build-vs-buy-decision.md) — gated decision, now released to Build
- [ADR-004: Event-Driven Posting](./ADR-004-event-driven-posting.md) — all GL entries derive from events
- [ADR-005: Immutable Journal](./ADR-005-immutable-journal.md) — posted entries never mutate
- [ADR-009: Modular Apps](./ADR-009-modular-apps.md) — sealed module boundaries
- [BUSINESS-EVENT-CATALOG.md](./BUSINESS-EVENT-CATALOG.md) — Payroll events #63–70 (`payroll.dtr.submitted` … `payroll.govt_remittance.paid`)
- [POSTING_RULES.md](../POSTING_RULES.md) — Payroll JEs (§14, EE deduction lines, ER shares calendar)

---

## Context

STMIET runs a separate payroll/HR system (vendor-owned, still being developed). The accounting system must record payroll costs in the GL without owning payroll operations.

Two integration options considered:

| Option | Coupling | Failure blast radius | Reviewability | Vendor readiness |
|--------|----------|---------------------|---------------|------------------|
| Live API (REST) | Runtime dependency | Payroll outage blocks accounting cycle | Low (posts immediately) | Unknown (system still in development) |
| File-based batch feed | Contract-only dependency | Zero — payroll can be down, replaced, or rebuilt; accounting unaffected | High (review JE preview before posting) | Full — any system can emit a fixed file layout |

**Company philosophy (user):** "If it breaks, only that breaks." The accounting cycle (weekly Wed-Tue cycles, ADR-028) must never wait on, or be contaminated by, the payroll system.

---

## Decision

Adopt the **file-based batch GL feed** as the interface between the payroll system and the accounting system.

### 1. The Contract (defined by the Accounting System — consumer defines, producer conforms)

The payroll system must emit a **Payroll GL Feed File** (fixed schema). The accounting system is the single owner of the schema; the payroll side conforms to it — never the reverse. The contract intentionally mirrors the company's existing "system-defined feed" pattern (weekly cycle sheets, COLLECTIBLES — ADR-028/029).

**File format:** Excel workbook (.xlsx) or CSV — configurable, default XLSX (matches company practice). One feed file per payroll period.

**Required sheets/columns (two sheets):**

**Sheet 1 — SUMMARY (one row per payroll batch):**

| Field | Example | Notes |
|-------|---------|-------|
| Payroll Period | 2026-08-01 | Period start date |
| Period End | 2026-08-15 | Period end date (semi-monthly) |
| Entity | STMIET | STMIET / STPC / IPPC |
| Segment | ALL | DHPP / DMIE / OPS / ALL |
| Cost Center | AG | Per cost-center code master (ADR-032 §4) |
| Batch Reference | PR-2026-08-A | Payroll system's own batch ID |
| Net Pay Total | 110,264.54 | Σ net pay |
| ER Share Total | 18,000.00 | Σ employer contributions |
| Remittance Total | 9,500.00 | Σ taxes/SSS/PHIC/HDMF withheld for remittance |

**Sheet 2 — JE LINES (one row per debit/credit line; the accounting system validates and posts):**

| Field | Example | Notes |
|-------|---------|-------|
| Line No | 1 | Order within JE |
| Entity | STMIET | Mirrors ADR-003 segments |
| Segment | DHPP | 4th segment where applicable (ADR-011) |
| Cost Center | AG | Cost center code |
| GL Account Code | 63400 | COA 5-digit (ADR-003); payroll level codes 634xx |
| GL Account Description | SALARY EXPENSE | Reference only — code is authoritative |
| Debit | 110,264.54 | One of Debit/Credit must be zero |
| Credit | 0.00 | — |
| Remarks | Net pay — period 08/01-08/15 | Free text, printable |

**ER shares** must be delivered as **separate JE lines** in the same feed (not merged into net pay), matching POSTING_RULES §14 (EE deductions as detailed lines, ER shares as their own entries), so the accounting system applies its standard payroll JEs and contribution handling unchanged.

### 2. Import & Posting Flow (accounting side)

```
1. Payroll team uploads feed file (or drops it in the import folder)
2. System validates: schema, entity/segment/cost-center codes exist, GL codes exist,
   COA segment validity (ADR-011), Debit+Credit balance per batch, all amounts 2-dp
3. System builds the JE PREVIEW (rejected: no manual editing of lines;
   corrections go back to payroll system — single source of truth)
4. Reviewer (Che), per approval matrix (ADR-020), approves
5. System posts to Immutable Journal (ADR-005) with Batch Reference linkage
6. Posting creates subsidiary ledger entries: Payroll Liability ledger,
   SSS/PHIC/HDMF/Withholding Tax ledgers (SUBSIDIARY-LEDGERS §payroll)
7. Remittance payments clear via AP module (RFP ≥ P2,500) or PCV (< P2,500)
```

### 3. Failure Isolation Rules

- Payroll system downtime, data loss, or replacement **has no effect** on the accounting system — the last delivered feed remains posted; the next valid feed resumes the chain.
- Feed files are archived with the batch (immutability, ADR-005).
- If the payroll system is rebuilt/migrated, only the producer changes — the accounting import adapter (i.e., swap only the adapter) stays untouched.

### 4. Upgrade Path (not required now)

The contract is API-future-proof: the exact same schema becomes the payload of a REST endpoint (`POST /payroll-feed`) later. The accounting side's import adapter is the only component to change; the validation/posting pipeline is identical. **Decision: no API integration in v1** — revisit only if payroll volume or latency requirements change.

---

## Consequences

### Positive
- Zero runtime coupling — payroll can break without touching accounting (the company's core requirement)
- Human review gate before posting — payroll errors never silently hit the GL
- Vendor-agnostic: works regardless of which system wins the ongoing payroll build
- Matches existing cultural pattern (Excel feeds that the accounting team already reviews)
- Feed file doubles as an audit trial (who delivered what, when)

### Negative
- Batch latency: payroll costs enter the GL on delivery, not real-time (acceptable for semi-monthly payroll)
- Requires payroll side to implement the schema (may need a small mapping effort on their end)
- File transfer must be secured (shared drive / upload endpoint) — payroll is sensitive data

### Neutral
- The contract is owned and versioned by the accounting system; schema version embedded in file name (`PAYROLL-GL-FEED-v1-2026-08-15.xlsx`)
- Classification codes (entity/segment/cost center/GL) come from the accounting system's master data — payroll system must consume them from a drop-down/download, keeping one source of truth