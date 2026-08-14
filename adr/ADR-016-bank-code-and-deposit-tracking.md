# ADR-016: Bank Code & Deposit Tracking

**Status:** Accepted  
**Date:** 2026-07-23  
**Deciders:** Architecture Team, Cashier Lead  

**References:**
- [ADR-003: Segment as First-Class Dimension](./ADR-003-segment-first-class.md) — bank-to-GL mappings may differ per segment
- [ADR-017: Purchase-to-Pay Document Flow](./ADR-017-purchase-to-pay-cycle.md) — AP check voucher references bank accounts for payment disbursement
- The bank code master supports segment-specific GL account overrides and is shared between AR collections (deposits) and AP disbursements (payments).

---

## Context

Collections come through **13 different bank accounts** (plus cash), each with a 3-letter code used consistently across all tracking sheets:

| Code | Bank | Type | GL Account |
|------|------|------|-----------|
| BNC | BDO Network | Checking | 10070 |
| CBS | China Bank | Savings | — |
| EWC | EastWest | Checking | 10020 |
| FVC | First Valley | Checking | 10030 |
| KBS | Katipunan Bank | Savings | 10060 |
| MBC | Metrobank | Checking | 10080 |
| PNC | PNB | Checking | 10040 |
| PSC | PSBC | Checking | 10110 |
| PSS | PSBC | Savings | 10050 |
| RCS | RCBC | Savings | — |
| COH | Cash/Check on Hand | — | 10010 |
| PNO | PNB - OPEX | — | — |
| ARC | A/Receivables - CNR | Receivable | 12020 |

Additionally, Mich performs **bank deposit monitoring** — she tracks which bank a cash payment should be deposited into and ensures the deposit happens.

From the shadow notes:
- "Bank deposit monitoring for cash payments (she monitors and assists in directing which bank to deposit)"
- She tracks which cash payments go to which bank account

---

## Decision

**Model bank codes as a master reference with associated GL accounts, and add deposit tracking for cash collections.**

### Rules

1. **Bank codes are a system master:**
   - 3-letter code is the primary key (matches existing convention)
   - Each bank code maps to one GL account (for DHPP segment)
   - Bank codes can be shared across segments or have segment-specific GL mappings

2. **Dr account auto-fill:**
   - When Mich selects the bank code during collection entry, the Dr account (Cash in Bank / Cash on Hand) is auto-filled
   - She verifies but does not re-type the account name

3. **Cash deposit tracking (COH):**
   - When payment type is COH (Cash on Hand), the system prompts for:
     - Intended deposit bank (where the cash should go)
     - Deposit status: "Pending", "Deposited", "Skipped"
     - Date deposited and reference number
   - This replaces Mich's manual monitoring

4. **Non-bank payment types:**
   - ARC (A/Receivables - CNR): Used for GCash payments that need recognition as receivable first
   - PNO (PNB - OPEX): Operating expense bank account
   - These do not follow the same deposit workflow

5. **Weekly bank summary:**
   - The system generates the weekly collection JE summary grouped by bank (matching the existing PAYMENT RECEIPTS sheet)
   - Total Dr per bank account = sum of all collections through that bank for the cycle

---

## Consequences

### Positive
- Eliminates manual bank code lookup and GL account typing
- Deposit tracking for cash reduces monitoring overhead
- Weekly JE summary by bank is auto-generated
- Consistent bank codes across all segments

### Negative
- Cash deposit tracking adds an extra step for COH transactions
- Bank-to-GL mapping must be maintained per segment
- GCash payments (ARC) need special handling — they are not immediately deposited

### Neutral
- 13 codes is manageable for a dropdown
- Existing code structure is stable (no evidence of frequent changes)

---

## Data Model

```python
class BankCode:
    code: str                     # "RCS", "MBC", etc.
    bank_name: str                # "RCBC - SAVINGS"
    account_type: str             # "Checking", "Savings", "Cash", "Receivable"
    gl_account_default: str       # Default GL for DHPP segment
    requires_deposit_tracking: bool  # True for COH

class DepositTracking:
    transaction_id: str
    amount: Decimal
    source: str                   # "COH"
    intended_deposit_bank: BankCode
    deposit_status: str           # "Pending", "Deposited", "Skipped"
    deposited_date: date
    deposit_reference: str        # Bank reference/confirmation #
    deposited_by: str
```
