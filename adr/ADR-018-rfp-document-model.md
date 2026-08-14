# ADR-018: RFP Document Model (ACCTG-FOR-012)

**Status:** Accepted  
**Date:** 2026-07-27  
**Deciders:** Architecture Team  

**References:**
- [ADR-017: Purchase-to-Pay Document Flow](./ADR-017-purchase-to-pay-cycle.md) — where RFP fits in the chain
- [ADR-019: AP Numbering Convention](./ADR-019-ap-numbering-convention.md) — A#### numbering
- [ADR-020: AP Approval Matrix](./ADR-020-ap-approval-matrix.md) — who signs each RFP
- [ADR-021: Advances to Employees Lifecycle](./ADR-021-advances-to-employees-lifecycle.md) — standing Cr entry

---

## Context

The RFP (Request for Payment) is the central AP document. It is defined by form **ACCTG-FOR-012 (Rev 00, effective 11.16.2024)**. AP shadow revealed 38 distinct RFP templates in `RFP TEMPLATES (UPDATED).xlsx`, each pre-configured for a specific vendor/purpose.

### RFP Form Structure (from actual templates)

| Field | Description |
|-------|-------------|
| **RFP Date** | Date of preparation |
| **RFP No.** | A#### sequential |
| **LAST AP** | Previous RFP# for this vendor (gap tracking) |
| **Charge to** | COA account code + name (e.g., 6100-00 EXP - Salaries) |
| **Payee** | Vendor/Supplier/Employee name |
| **Particulars** | Description of payment |
| **Amount** | Total amount in words and figures |
| **Amount in Figures** | Numeric total |
| **Purpose** | Category of payment |
| **Segment** | DHPP/DMIE/OPS/STPC |
| **Supporting Docs** | Attachments (invoice, PO, RR, etc.) |

### Standard Journal Entry Pattern (from every RFP) — canonical balancing formula

```
Dr: [Expense / Inventory / Asset Account]    P TOTAL.XX      (total voucher amount)
    Cr: Advances to Employees - Current           P 20,000.00  (standing offset)
    Cr: Accounts Payable - [Vendor]               P (TOTAL − 20,000).XX
```

The Advances to Employees line (P20,000) appears on **every RFP** as a standing credit. This is a clearing mechanism — see ADR-021. The entry always balances: `TOTAL = 20,000 + (TOTAL − 20,000)`. (Prior drafts of this ADR and ADR-023/POSTING_RULES showed non-balancing variants — superseded by this formula; see REVIEW-ISSUES-RESOLUTIONS.md #5.)

### RFP Types (from 38 templates)

| Category | Examples | COA Account Pattern |
|----------|----------|-------------------|
| **Salaries & Wages** | CNR Short Term Loan, Salary RFPs | 6100-00 EXP - Salaries |
| **Fuel & Operations** | STPC Fuel, Motorpool, Shandong Fuel | 50000-00 COGS / various expenses |
| **Utilities** | PLDT, ZANECO, Water District | 6120-00 EXP - Utilities |
| **Equipment & Leasing** | ORIX, Shandong Equipment | Various asset/expense accounts |
| **Office & Admin** | Office supplies, rent, insurance | 6130-00 to 6160-00 |
| **Contractors** | Bulilit, construction, service providers | Various |
| **Advances** | Employee advances, supplier advances | Advances accounts |

---

## Decision

The RFP is modeled as a dual-purpose document:

1. **Approval document** — carries the payment request through the approval chain
2. **JE template** — carries the journal entry that will be posted upon approval

### RFP Data Model

```python
class RFP:
    id: str                          # A####
    date: date
    last_ap: str                     # Previous A#### for this vendor (gap tracking)
    payee: str                       # Vendor/Supplier/Employee
    particulars: str
    amount: Decimal
    purpose: str
    segment: Segment                 # DHPP/DMIE/OPS/STPC
    charge_to_account: Account       # COA account code
    status: RFPSatus                 # Draft → Submitted → Checked → AcctgApproved → FinApproved → CONSOd → Posted
    
    # JE Lines
    debit_lines: List[JELine]        # Typically 1 debit (expense/asset)
    credit_lines: List[JELine]       # Advances to Employees (P20,000) + AP (balance)
    
    # Supporting Documents
    attachments: List[Document]       # Supplier invoice, PO, RR, etc.
    
    # CONSO Reference
    conso_batch: CONSO               # Parent consolidation batch
    
    # Metadata
    created_by: User                 # Che (AP Clerk)
    checked_by: User                 # Alywin (Dept Head)
    approved_by_acctg: User          # Accounting Manager
    approved_by_fin: User            # Finance Manager
```

### JE Posting Behavior

- RFP in "CONSO'd" status → JE is posted to General Ledger
- The system generates the JE automatically from the RFP's debit/credit lines
- Advances to Employees (P20,000) is auto-added as standing credit on every RFP
- Manual override of the Advances to Employees amount is allowed (for non-standard cases)

### Supporting Documents

Each RFP must have at minimum one supporting document attached. Common attachments:
- Supplier Invoice/Billing Statement
- Purchase Order (PO)
- Receiving Report (RR)
- Proof of Payment (for reimbursements)
- Contract/Agreement

---

## Consequences

### Positive
- Single form covers all AP payment types (salaries, vendors, contractors, advances)
- JE is embedded in the RFP — no separate JE creation step
- Standing Advances to Employees entry is auto-applied, reducing manual error
- "LAST AP" field enables automated gap tracking

### Negative
- RFP form has 10+ fields — requires complete data before submission
- Standing Advances entry may confuse new users (why P20,000 on every RFP?)
- 38 template variants mean significant setup data entry

### Neutral
- RFP is cross-departmental — touches Procurement, AP, Treasury
- Supporting docs may include scanned copies → file storage requirement
