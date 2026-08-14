# ADR-024: Supplier/Vendor Master

**Status:** Accepted  
**Date:** 2026-07-27  
**Deciders:** Architecture Team  

**References:**
- [ADR-007: Centralized Customer Master](./ADR-007-centralized-customer.md) — analogous ADR for customer data
- [ADR-018: RFP Document Model](./ADR-018-rfp-document-model.md) — RFP references payee
- [ADR-023: Multi-Segment AP Allocation](./ADR-023-multi-segment-ap-allocation.md) — vendor expenses by segment

---

## Context

The RFP Templates (38 sheets) reveal a diverse set of vendors/suppliers. AP shadow confirmed these are tracked informally — no centralized vendor master exists.

### Known Vendors (from RFP Templates)

| Category | Vendors | Typical Amount | Segment |
|----------|---------|---------------|---------|
| **Fuel Supply** | Shandong, STPC, various depots | Varies | DHPP |
| **Utilities** | PLDT, ZANECO, Water District | Monthly fixed | All segments |
| **Leasing** | ORIX | Monthly amortization | DMIE |
| **Personnel** | CNR (COO loan), Employees | Recurring | All segments |
| **Contractors** | Bulilit, construction | Per project | OPS |
| **Equipment** | Suppliers (machinery, parts) | Per purchase | DMIE |
| **Office/Admin** | Various office suppliers | As needed | DHPP |
| **Insurance** | Insurance providers | Annual/quarterly | All segments |
| **Government** | BIR, SSS, PHIC, HDMF | Monthly | All segments |

### Current Pain Points

1. No centralized vendor list — payee names are typed free-text on each RFP
2. No vendor tax information tracking (TIN, BIR registration)
3. No payment terms tracking (due dates, discount periods)
4. Duplicate vendor entries possible
5. No vendor aging or history view per vendor
6. "LAST AP" tracking is manual — system should automate this

---

## Decision

A centralized Supplier/Vendor Master is established, analogous to the Customer Master (ADR-007).

### Data Model

```python
class Supplier:
    id: str                         # Auto-generated
    code: str                       # Short code (e.g., VEND-001)
    name: str                       # Legal/business name
    tin: str                        # Tax Identification Number
    address: str
    contact_person: str
    contact_number: str
    email: str
    payment_terms: str              # e.g., "30 days", "Upon receipt"
    category: str                   # Fuel/Utility/Leasing/Contractor/Govt/etc.
    segments: List[Segment]         # Which segments transact with this vendor
    is_active: bool
    bank_accounts: List[BankAccount]  # For payment
    
    # Computed
    last_rfp_number: str           # LAST AP (auto-tracked per vendor)
    total_paid_ytd: Decimal
    total_outstanding: Decimal
```

### Source Data

Initial vendor list will be populated from:
1. 38 RFP templates — vendor names and typical purposes
2. PO template — vendor names
3. AP shadow notes — known suppliers and depots
4. Supplier Invoice files — if available

Estimated initial count: 50-100 suppliers including:
- ~15 fuel depots (DOHINOB, SAN PEDRO, and others)
- ~10 utilities and government agencies
- ~10 equipment/machinery suppliers
- ~5 leasing companies
- ~5 contractors
- ~5 insurance providers
- ~10 office/admin suppliers
- Various one-off vendors

### Behavioral Rules

1. **Vendor selection** — RFP creation requires selecting from vendor master (not free-text)
2. **New vendor request** — if vendor doesn't exist, user can request addition (requires Alywin approval)
3. **LAST AP auto-tracked** — system records the last RFP number per vendor
4. **Vendor aging** — report of outstanding AP per vendor with aging buckets
5. **Duplicate detection** — similar names flagged on creation

### Integration with Other Modules

| Module | Relationship |
|--------|-------------|
| AP | RFP references Supplier for payee |
| Inventory | Supplier PO references vendor |
| Treasury | Check Voucher references Supplier bank account |
| COA | Supplier can have default expense account per segment |

---

## Consequences

### Positive
- Eliminates free-text payee entries and duplicates
- "LAST AP" tracking becomes automatic
- Vendor aging reports possible
- Tax info enables automated BIR forms (2307, 2306)

### Negative
- Initial data entry of 50-100 suppliers required
- Existing RFPs with free-text payee names need migration
- New vendor request adds a step to RFP creation

### Neutral
- Vendor master is a separate bounded context — shared across AP, Inventory, Treasury
- Can be extended to include contracts, price lists, and purchase history
- Similar pattern to Customer Master (ADR-007) — consistent approach
