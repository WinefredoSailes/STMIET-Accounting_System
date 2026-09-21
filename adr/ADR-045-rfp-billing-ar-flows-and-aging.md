# ADR-045: Payables & Receivables Flows — RFP, Billing, AR Invoice & Independent Aging

**Status:** Proposed (pending Finance review)
**Date:** 2026-09-21
**Deciders:** Architecture Team + Finance Head (review)

**References:**
- [ADR-017: Purchase-to-Pay Cycle](./ADR-017-purchase-to-pay-cycle.md) — where RFP and CV sit in the payables chain
- [ADR-018: RFP Document Model](./ADR-018-rfp-document-model.md) — the central AP document
- [ADR-020: AP Approval Matrix](./ADR-020-ap-approval-matrix.md) — RFP approval signatures
- [ADR-015: Acknowledgment Receipt Sequence](./ADR-015-acknowledgment-receipt-sequence.md) — AR numbering
- [ADR-029: Collectibles Settlement](./ADR-029-collectibles-settlement.md) — how collections settle against what clients paid
- [ADR-044: Reversal & Unposted Documents](./ADR-044-reversal-and-unposted-documents.md) — corrections and pipeline visibility

---

## 60-second summary (for discussion)

1. There are **three separate document tracks** in the system — **Payables**, **Receivables**, and **Billings**. Each one posts its **own accounting entry** to the books.
2. The **Request for Payment (RFP)** is a Payables document. When approved and posted, it directly books the payable (`Dr Expense | Cr Accounts Payable`) — it does **not** pass through Billing.
3. **Billing (BI)** is a separate document for STPC/third-party receivables. It may *reference* an RFP for traceability, but that RFP is still paid through its own Payables path.
4. Each side has its **own aging schedule**: Payables aging reads RFPs (less checks paid); Receivables aging reads Sales Invoices (less collections applied). They are independent, and both reconcile to the balance sheet.
5. This ADR only *documents how it works today* — no system change. Two optional future items are logged at the end (Section 7).

---

## 1. The question that this ADR answers

During planning we had to confirm: **"Does the RFP go to our existing billing transaction?"**

The answer needs to be precise because it drives how finance reads the reports:

- If by "transaction" we mean the **accounting entry in the journal** → yes, every approved RFP creates its own entry.
- If by "billing transaction" we mean the **Billing module (BI)** → no. RFP and Billing are different documents that we link *only for reference*.

## 2. Track 1 — Payables (what the company owes)

| Document | Purpose | What it posts |
|---|---|---|
| **RFP** (Request for Payment) | Request and approval of an expense/payment | `Dr Expense | Cr Accounts Payable` — captures the payable |
| **Check Voucher (CV)** | Pays the payee later (after the RFP is posted) | `Dr AP | Cr Cash (+ withholding tax)` — settles the payable |

Flow:

```
RFP (prepared → approved) ──Posted (CONSO batch)──► Journal Entry "RFP" (payable booked)
                                                          │
                                                            ▼
                                              Check Voucher ──Cleared──► Journal Entry "CV" (AP settled, cash out)
```

- **Payables aging** = posted RFPs, less the checks already paid against them, bucketed by how old each RFP is (0-30 / 31-60 / 61-90 / 91-120 / 120+). It reconciles to the balance-sheet AP account.

## 3. Track 2 — Receivables (what customers owe the company)

| Document | Purpose | What it posts |
|---|---|---|
| **Sales Invoice (SI)** | Delivery/sales billing raised for a customer | The receivable (its balance = what the customer still owes) |
| **Acknowledgment Receipt (AR)** | Cash collection from the customer | `Dr Cash | Cr Accounts Receivable` — settles the invoice it is applied to |

Flow:

```
Sales Invoice (raised) ───────────────────────────────► balances feed Receivables aging
        ▲
        │ (collection applied to invoice)
Acknowledgment Receipt ──Posted──► Journal Entry "AR" (Dr Cash | Cr AR)  → invoice balance reduces
```

- **Receivables aging** = open sales invoices (not yet fully collected), each reduced by every receipt applied to it, bucketed by invoice age.
- A receipt may either be **applied to a specific invoice** (Cr AR) or **kept as unearned/advance** (Cr unearned revenue) when no invoice exists yet (ADR-029 / ADR-012 settlement).

## 4. Track 3 — Billings (STPC / third-party billing)

| Document | Purpose | What it posts |
|---|---|---|
| **Billing (BI)** | A manually prepared billing to an affiliate (STPC) or third party | A **Billing** entry (`Dr billed account | Cr revenue/unbilled`) |

- A Billing may be **based on an RFP** — e.g., an approved expense that is re-billed onward. In that case the system records the RFP number on the Billing entry *for traceability only*.
- **Important:** the underlying RFP still posts its own Payables entry and is paid via its own Check Voucher path. One RFP can therefore authorize two different economic events: a payable (we owe) and a billing (we charge back). They never merge.
- **Today the Billing entry appears on neither aging report** — it is not an unpaid RFP, and it does not create a Sales Invoice. Any amount still owed on a billing is visible through its document, not through aging. (Optional future item — see Section 7.)

## 5. Independent aging side by side

| | Payables (AP) | Receivables (AR) |
|---|---|---|
| Documents | RFP → Check Voucher | Sales Invoice → Acknowledgment Receipt |
| Aging reads | Posted RFPs (less checks paid) | Open SI balances (less receipts applied) |
| Bucket age from | RFP date | Invoice date |
| Reconciled against | AP account in the GL | AR account in the GL |

Two independent schedules by design — AP tells us what we owe; AR tells us what is owed to us.

## 6. Decision (this ADR)

The current system already implements the three-track model above. This ADR **confirms and documents** it as the agreed behavior:

1. RFP and Billing remain separate documents; the optional RFP→Billing link is traceability only.
2. Receipts "applied to invoice" settle the receivable and move AR aging; unapplied collections book to unearned revenue.
3. Payables and Receivables aging stay document-driven and independent.

## 7. Deferred (logged, not built)

- **Billing → Sales Invoice link (future):** posting a Billing could create a Sales Invoice so third-party/STPC billings age as receivables. Held for the SI source-of-truth discussion.
- **Due-date aging (future):** aging could switch from document date to a proper due date for days-past-due reporting. Needs a new field + migration.
- **Over-payment guard (future):** a Check Voucher larger than the RFP's payable is not currently blocked and could make an AP balance go negative.

## 8. Verification

No code changes accompany this ADR. The behavior it documents is enforced by existing tests: `apps/ui/tests.py::TestReceiptScreen` (apply-to-invoice), `apps/billing/tests.py` (BILL posting / RFP reference), `ap_aging_context` / `CycleLedgerService.aging` coverage, and the reversal/aging recompute tests in `apps/posting`.