# ADR-025: Build vs. Buy Decision for the Accounting Domain

**Status:** Superseded — replaced by **Accepted: Build (Option C)** via [ADR-033](./ADR-033-payroll-gl-feed.md), 2026-08-14. Management gate released: observation complete (Mich ✅, Che ✅, Quibs ✅; Alywin shadow window open — payroll/HR isolated by ADR-033), live POC not required; per the decisive question in §"The Decisive Question", no commercial option can be the engine for the self-built inventory platform without custom-coded extensions, so custom build is confirmed.
**Date:** 2026-07-27
**Deciders:** Architecture Team, Management (COO)
**Stakeholders:** Management — expressed willingness to invest in Intuit QuickBooks

**References:**
- [ADR-010: Framework Decision](./ADR-010-framework-decision.md) — original Django rationale
- [ADR-001: Architecture Vision](./ADR-001-architecture-vision.md) — modular platform vision
- [PAIN-POINTS-CONSOLIDATED.md](../PAIN-POINTS-CONSOLIDATED.md) — evidence for this decision

---

## Context

Management asked whether **Intuit QuickBooks** could address Seven-Trent's accounting needs and indicated willingness to invest in a commercial product. This ADR records the evaluation framework and the gate for the final decision.

### The Two Questions

1. **"Can QuickBooks do accounting?"** — Almost certainly yes for standard GL/AR/AP/FS.
2. **"Can QuickBooks be the accounting engine for Seven-Trent's enterprise platform?"** — Must be validated against documented reality, not assumed.

### Documented Reality Bearing on the Decision

| Area | Finding | Source |
|------|---------|--------|
| COA | 10-digit codes with segment suffixes (00/03/06) + STPC gap | COA-STMIET-2026.xlsx |
| Cash cycle | **Weekly (Wed-Tue)** cycle, not monthly | SUMMARY OF CASH JANUARY 2026.xlsx |
| Revenue model | Prepayment-first; **no Official Receipts** — Acknowledgment Receipts only | Mich shadow |
| Pricing | Three-tier (Regular/Patron/Volume) re-snapshotted per cycle | Collection System macro |
| Customer ledger | Cycle-based "Over/(Short)" cumulative balance model | Collection System macro |
| Posting rules | 14 families incl. fuel 5-step, machinery, consignment, installment+freebies, Bulilit contractor | Acctg-Entry-finance-and-acctg.xlsx |
| AP flow | RFP (ACCTG-FOR-012) → 4-level approval → CONSO → Check Voucher | AP shadow, RFP Templates |
| AP JE | Standing Cr Advances to Employees (P20,000) on every RFP | RFP Templates |
| Bank accounts | 12 accounts / 9 banks, per-bank ADB maintaining balances | Cashflow folder |
| PCF | **3 funds** (Leaslyn-general, Maintenance-treasury, Technical-Alywin); **85% replenishment trigger** | Quibong shadow |
| Inventory | **Live Django platform 120+ days**, ~60%→3% discrepancy improvement | Project record |
| Integration need | Inventory JEs must flow to accounting **without manual re-entry** (staff request) | Inventory interview |

---

## Decision

**RESOLVED 2026-08-14: BUILD (Option C).** Custom Django accounting domain per ADR-001..024 + ADR-026..033. Rationale recorded below (original gate content preserved for the record).

1. **Do not decide today.** The two-week observation must complete first (Quibs ✅ done, Alywin shadow scheduled this week; Sir Aaron/Mam Anne deferred — see note below).

2. **Run a live Proof-of-Concept** for top commercial candidates using real STMIET workflows — not generic demos. QB is the priority candidate per management interest.

3. **Evaluation matrix below is the objective criteria.** Score each option; total weighted score decides.

4. **Provisional position:** Unless a commercial product covers the *Critical* criteria rows without custom-coded extensions, **Option C (custom)** remains the recommended path — because the hardest engineering problem (operational events → GL without manual re-entry) must be built regardless of which option is chosen.

5. **De-scoped observation:** Sir Aaron (tariff) and Mam Anne (fuel ordering) workflows are **deferred**. Their documents (driver settlements, fuel POs) are captured at handoff boundaries in the AP/Treasury modules. If the matrix result is "custom," their detailed workflows may be revisited during module 2 implementation.

---

## Options Considered

| Option | Description |
|--------|-------------|
| **A: Intuit QuickBooks** (Online/Advanced) | Subscription; QB owns GL/AR/AP/FS + PH BIR forms |
| **B: ERPNext** | Open-source ERP; customize accounting + ops modules |
| **C: Custom Django Accounting Domain** | Continue ADR-001..024; integrate via event bus with live inventory platform |

---

## Evaluation Matrix

| # | Criteria | Weight | QB | ERPNext | Custom | Evidence Notes |
|---|----------|--------|-----|---------|--------|----------------|
| 1 | General Ledger (immutable JE, no force balance — ADR-002/005) | High | Strong | Good | Full control | Team explicitly prohibits force balance |
| 2 | **Weekly cash cycle (Wed-Tue)** | Critical | Weak | Custom | Native | Not a monthly-period concept |
| 3 | **Per-cycle three-tier pricing snapshots** | High | Weak | Custom | Native | Prices change every cycle |
| 4 | **Customer ledger Over/(Short) cumulative model** | High | Weak | Custom | Native | Total Payments − Amount Payable |
| 5 | Accounts Receivable / Payable / FS (monthly) | High | Strong | Good | Native | All 6 FS templates exist |
| 6 | Multi-segment COA (00/03/06 + STPC) | High | Weak | Good | Native | QB Classes ≠ segment-suffixed accounts |
| 7 | **Event-driven posting from inventory (no re-entry)** | Critical | Integration layer | Integration layer | Native | Staff explicitly requested this |
| 8 | Custom posting rules (14 families) | Critical | Add-ons | Code needed | Native | Fuel 5-step, Bulilit, consignment |
| 9 | RFP 4-level approval workflow | High | Add-ons | Good | Native | Requestor → Alywin → Acctg → Finance |
| 10 | RFP JE model (standing Advances P20,000) | High | Weak | Good | Native | Clearing-account convention |
| 11 | API availability for programmatic transactions | Critical | QB API + mapping | Available | Native | POST transactions from Django |
| 12 | Fixed Assets (depr, disposal) | Medium | Medium | Good | Good | — |
| 13 | BIR compliance (VAT/WHT/EWT/2307/2306) | High | Medium (PH ed.) | Weak | Build required | PH-specific forms |
| 14 | PH Payroll (SSS/PHIC/HDMF, 13th month, 2316) | High | Weak | Weak | Build required | Needed regardless; QB won't solve |
| 15 | Integration with **live inventory platform** | Critical | Mapping built | Migration risk | Native | ERPNext = rebuild 120-day-live system |
| 16 | Licensing / cost | — | Monthly fee | Free + hosting | Dev time | QB ≈ ongoing subscription |
| 17 | Implementation time | High | Fast core | Migrate first | ~8-10 wks foundation | ADR-010 estimate |
| 18 | Long-term flexibility / vendor lock-in | High | Lock-in | Migrate | Owned | Single-dev + AI orchestration team |

---

## Preliminary Expectations (to validate, not assume)

| Option | Expected Outcome |
|--------|-----------------|
| QuickBooks | Strong core GL/AR/FS; **fails weekly cycle, pricing snapshots, custom posting rules, RFP approval flow**; integration still requires a built mapping layer |
| ERPNext | Broadest ERP; **fails on live-system migration cost** — would abandon the working Django inventory platform |
| Custom | Best fit structurally; cost = development time (already low incremental); risk = tax/audit correctness — mitigated by posting rules + approval gates |

---

## The Decisive Question

> **Can the candidate be the accounting engine for Seven-Trent's self-built inventory platform — not merely do accounting?**

If no commercial option scores ≥ 80% weighted + passes all *Critical* rows without custom extensions, **custom** is the defensible answer to management.

---

## Consequences

### If Buy (Option A or B)
- QB/ERPNext becomes GL/FS engine; original ADR-001 vision of integrated domain is superseded (ADR-001 would be amended)
- Still must build: inventory↔QB integration mapper, posting-rule logic as add-ons, weekly cycle reporting, BIR/payroll gap
- Data duplication risk between operational system and QB
- Monthly licensing added to cost base

### If Build (Option C)
- Proceed with existing ADR plan; accounting domain integrates natively with inventory via event bus
- Payroll + BIR modules in scope of custom build
- Requires continued AI-orchestrated development capacity (proven 120+ days live)

### Neutral
- Either path requires the operational-event→GL mapping work; buying does not eliminate it
- Alywin shadow (this week) may surface additional criteria for the matrix

---

## ADR Amendment Note

**RESOLVED 2026-08-14 — this ADR is superseded.** Per its own amendment rule: "If 'Build' is confirmed after evaluation, this ADR is superseded by the original ADR-001 vision (status → Superseded)." Evaluation complete; custom build confirmed; see [ADR-033](./ADR-033-payroll-gl-feed.md) and the Build Staging Plan (BUILD-PLAN.md) for the execution order.