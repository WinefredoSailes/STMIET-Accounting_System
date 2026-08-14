# Cashier (Mich) — Complete Workflow Analysis

## Role Overview
- **Person:** Mich
- **Role:** Cash, Collections, AR, Client Accounts, Official Receipts
- **Department:** Accounting — AR & Collections
- **Company:** Seven-Trent Machineries Industrial Equipment Trading
- **Location:** Dipolog City, Zamboanga del Norte 7100
- **Document Control:** ACCTG-FOR-005 v3 (Acknowledgment Receipt Form)

---

## Daily Routine (In Order)

### 1. Morning Startup
1. Open Excel files (AR-BLUE, Collection System macro)
2. Open Facebook Messenger (for Proofs of Payment from clients)
3. Print POPs received
4. Open customer ledger (per-client macro)

### 2. Transaction Processing
1. Client sends POP via Messenger **or** walks into cash office
2. Verify: **PO#** → **Price** → **Proof of Payment**
3. Issue **Acknowledgment Receipt** (pre-numbered blue form)
4. Enter into **customer ledger** (the "macro" — per-client tracking sheet)
5. Enter into **MONITORING sheet** (AR-BLUE 2026.xlsx)
6. Update **collections summary** (passed to accounting at cycle end)

### 3. End-of-Week/End-of-Cycle
- Generate Collection Journal Entry Summary for the cycle
- Attach Proofs of Payment per client per cycle
- Pass to accounting department for posting

---

## Trigger: How She Knows a Client Paid

| Channel | Description |
|---------|-------------|
| **Facebook Messenger** | Client posts Proof of Payment in group chat |
| **Cash Office Walk-in** | Client pays cash/check in person |
| **Manual Reconciliation** | If no POP sent, she must manually trace the payment |

---

## Verification Before Posting

| Item | Why |
|------|-----|
| PO# | Match payment to the correct order |
| Price | Prices change daily — biggest bottleneck |
| Proof of Payment | Confirms amount and bank of deposit |

---

## Documents Handled

| Document | Format | Purpose | Source |
|----------|--------|---------|--------|
| Acknowledgment Receipt | Pre-numbered blue form (AR#) | Acts as OR — no official receipts exist | Issued by Mich |
| Sales Invoice | Excel/Printed | Lubricant sales only | Issued by Mich |
| Billing Invoice | Excel/Printed | For billed customers | Issued by Mich |
| Customer Ledger | Excel per-client (macro) | Per-client cycle tracking | Maintained by Mich |
| AR Aging Report | Excel manual | Tracks overdue customers | Finance Head |
| Client Statement of Account | Excel | Monthly statement per client | Depende / Mich |
| Proof of Payment (POP) | Screenshot/Image | Evidence of bank deposit | Client via Messenger |
| Collection Summary | Excel | Weekly cycle totals by bank | Mich → Accounting |

---

## Pain Points & Bottlenecks

| Problem | Impact | Root Cause |
|---------|--------|------------|
| **Pricing Delays** | Cannot process payment until price confirmed | Prices change daily; must wait for viber/FB notification | There are for adjustments in the case that the client pays, but some payments are either more or less
| **Late POP Submissions** | Delays entry; requires manual follow-up | Customers wait for price notification before sending |
| **No Unified System** | Redundant entries across departments | Each dept maintains own Excel files (OneDrive) |
| **Manual Excel Entry** | Error-prone, inconsistent | No validation; free-text entry |
| **Monthly JE Deadline** | Must finish all journal entries monthly | Manual aggregation per cycle |
| **POP Attachment per Cycle** | Extra administrative overhead | Printing and attaching POPs per client per cycle |
| **AR Tracking** | Manual paper lists; FB group chat follow-ups | No automated AR aging or reminders |
| **STPC Monitoring (~4 stations)** | Sister company stations need separate tracking | Intercompany reconciliation |
| **Bank Deposit Monitoring** | Cash payments need deposit tracking | She monitors and directs which bank to deposit to |
| **AR Reconciliation Accuracy (~70%)** | Inconsistent due to pricing changes | No system-enforced pricing |
| **Acknowledgement Receipt Tracking** | Serial numbers tracked but "unorganized" | No automated AR# sequence tracking |

---

## Current Metrics vs. Targets

| Metric | Current State | Target |
|--------|--------------|--------|
| Payment-to-record match time | Not fixed — pricing dependent | < 5 min |
| AR Aging report generation | 2-3 hours | < 1 min |
| Customer lookup time | 30 sec (Excel search) | < 10 sec |
| Acknowledgment Receipt issuance | 2-3 min (if price is fixed) | < 2 min |
| AR reconciliation accuracy | ~70% | 100% |
| Customer records count | ~200+ (2-5 new/month) | Complete |

---

## System Flow Diagram

```
Client sends POP (Messenger) or walks in
        │
        ▼
Mich opens Messenger/email
        │
        ▼
Verifies: PO# → Price (viber/FB) → POP
        │
        ▼
Issues Acknowledgment Receipt (pre-numbered AR#)
        │
        ▼
Enters in Customer Ledger (macro per-client)
        │
        ▼
Enters in MONITORING Sheet (AR-BLUE 2026)
        │
        ▼
End of Cycle → Generates Collection JE Summary
        │
        ▼
Forwards to Accounting → they post aggregate weekly JEs
```

---

## Data Sources (Excel Files)

| File | Purpose |
|------|---------|
| `AR -BLUE 2026.xlsx` | Daily monitoring sheet — 1M+ rows of collections |
| `COLLECTION SYSTEM- DHPP - macro (5).xlsm` | Per-client cycle ledger with 120+ individual client sheets |
| `DAILY COLLECTION JOURNAL ENTRIES SUMMARY.xlsx` | Weekly JE summaries for accounting |
| `General_Journal_DHPP TRANSACTIONS.xlsx` | Full general journal with chart of accounts, payment receipts, delivery recognition |
| `ACKNOWLEDGMENT- FUEL.xlsm` | Acknowledgment receipt template (ACCTG-FOR-005 v3) |
