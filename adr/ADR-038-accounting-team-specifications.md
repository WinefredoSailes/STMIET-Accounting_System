# ADR-038: Accounting Team Specifications & System Extensions

**Status:** Draft (pending UAT validation)  
**Date:** 2026-09-05  
**Deciders:** Accounting Team + Architecture Team  

---

## Context

The accounting team has provided extensive specifications covering multiple modules that are either missing or need enhancement in the current STMIET Accounting System. These specifications arise from UAT feedback (Sept 4-6, 2026) and represent the gap between the current wired UI (RFP → CONSO → CV) and the full desired accounting system functionality.

**Current wired UI scope** (per ADR-017): RFP → CONSO → CV (tested and functional).  
**Desired system scope** (per accounting team): Full GL, AR, AP, Fixed Assets, COA, Supplier, Petty Cash integrations.

This ADR documents the specifications, decisions, and implementation plan for extending the system beyond the current UAT scope.

---

## 📋 Specifications Received from Accounting Team

### **1. General Ledger (MISSING MODULE)**

**Statement**: "No General Ledger yet in the system."

**Required**: Once the RFP is approved by the Accounting Head, the debit and credit entries should reflect in the trial balance. Upon approval of check vouchers, the same should happen.

**Decision**: Create a General Ledger module that:
- Connects all business cycles (JE → Approval → Report) to Trial Balance
- Ensures RFP approval by Accounting Head triggers GL entries → Trial Balance
- Ensures Check voucher approval (sign/release/clear) triggers GL entries → Trial Balance
- Integrates with existing posting module (`apps.posting`)

**Implementation scope**:
- GL entries generation from RFP approval (per ADR-018: RFP carries JE)
- GL entries generation from CV lifecycle (created → signed → released → cleared)
- Trial Balance service already exists (`TrialBalanceService.rows()`) — needs GL integration
- Journal Entry creation auto-flow from approved documents

---

### **2. AR Cash-In Flow**

**Path**: Acknowledgment Receipts → Aging → Collections Summary

**Required**: AR module connecting acknowledgment receipts through aging to collections summary.

**Current state**: Acknowledgment receipts (`ACCTG-FOR-005`) exist but lack full flow to aging and collections summary.

**Decision**: Implement AR cash-in flow:
- Acknowledgment Receipt creation (already partially implemented in `apps.ar.views`)
- Aging report generation for AR
- Collections summary dashboard
- Integration with customer master data

**References**: `apps.ar.models.Customer`, `apps.ar.services.CollectionService`

---

### **3. AP Cash-Out Flow (Through CV Part Only)**

**Path**: RFP → 4-step approval → CONSO → CV → sign → release → clear

**Testing scope**: Through CV part only (stopping before further steps).

**Current wired flow** (per ADR-017): RFP → CONSO → CV (tested, 242 tests pass).

**Required full flow**:
- RFP created → 4-step approval chain (per ADR-020: Prepared → Checked → Acctg Approved → Fin Approved)
- CONSO batch generation from approved RFPs
- Check Voucher creation from CONSO/RFP
- CV sign (COO only): `created → signed`
- CV release (Staff/Treasury): `signed → released`
- CV Clear (Head): `released → cleared`
- All entries reflect in GL → Trial Balance

**Key constraint**: User specified "testing until CV part only" — confirm if full AP flow beyond CV is in or out of UAT scope.

---

### **4. Fixed Assets Module**

**a. Filter/Category Data**
- **Required**: Option to categorize/filter Fixed Asset data (not only detailed listings)
- **Decision**: Add filter/categorize capability in asset listing screens
- **Location**: `apps.assets.views` + `apps.assets/templates/`

**b. Automated Depreciation (Month-End)**
- **Required**: Depreciation automated every month-end; no manual user action
- **Entries**: Should reflect in general journal → trial balance
- **Decision**: Implement `MonthEndCloseService.depreciate_all()` or similar service
- **Automation**: Trigger from `month_end_close` view or separate management command
- **Posting**: Depreciation entries via `PostingService.post()` to auto-create JE lines → Trial Balance

**c. Overstated Asset Reversal**
- **Required**: User can reverse if fixed assets upon booking are overstated
- **Effect**: Prospective/moving forward only (not retroactive)
- **Decision**: Implement reversal entry with date-effective mechanism; entries post prospectively from reversal date
- **Audit trail**: Track reversal entries separate from original depreciation

---

### **5. Chart of Accounts (COA) Enhancements**

**a. Add/link additional columns for other categories**
- **Decision**: Extend `Account` model with additional classification columns
- **Location**: `apps.foundation.models.Account`

**b. COA for Accumulated Depreciations — normal balance is CREDIT**
- **Current**: Need to verify/fix `normal_balance` field values
- **Decision**: Set `normal_balance` = `CREDIT` for Accumulated Depreciation accounts
- **Reference**: Existing `money` filter and `normal_balance` logic in posting module

**c. Sales Discount has DEBIT Normal balance**
- **Decision**: Set `normal_balance` = `DEBIT` for Sales Discount accounts

**d. E. Bagatua, Drawing — Normal Balance is DEBIT**
- **Decision**: Set `normal_balance` = `DEBIT` for Drawing/Dividend accounts

**e. COA available for renaming/addition**
- **Decision**: Allow COA account renaming via UI; add new accounts with code validation
- **Implementation**: `Account` model `code` uniqueness + `name` edit capability

**f. Printout for documentation**
- **Decision**: Add Print button/feature for COA listing/report
- **Location**: Report templates + view function

---

### **6. Supplier Module Enhancements**

**a. Auto-generated code for new suppliers**
- **Required**: Auto-code on supplier create (pattern: S001, S002, or type-based)
- **Current**: `Supplier.code` = `CharField(max_length=32, unique=True)` — no auto-generation
- **Decision**: Implement auto-code generation on create, mirroring RFP A#### pattern
- **Implementation**: `DocumentSequence.next_number(form_code="SU")` or similar

**b. More entries for contact persons & contact numbers**
- **Current**: `contact_person` + `position` fields exist on Supplier
- **Decision**: Allow multiple contact persons per supplier; add `contact_number` field
- **Implementation**: Separate `SupplierContact` model or extend existing fields

**c. Link Suppliers data to Request for Payment**
- **Current**: Supplier ↔ RFP relationship exists (`RFPDocument.payee = ForeignKey(Supplier)`)
- **Decision**: Ensure bidirectional link: Supplier shows last AP/active RFPs; RFP shows payee supplier details
- **Implementation**: Already partially implemented; enhance UI display

---

### **7. Petty Cash Replenishment Integration**

**a. Auto GL Account Name when GL Account Number entered/searched**
- **Current**: `pcf_replenish` view manually selects accounts
- **Decision**: Add autocomplete/search for GL Account code → auto-display account name
- **Implementation**: HTMX/Django autocomplete in `pcf_replenish` form

**b. Add columns for customer names or who requested the petty cash**
- **Current**: `pcf_replenish` model has expense accounts, segments, cost centers
- **Decision**: Add `requested_by` field (User ForeignKey) + `customer_name` or `client_name` field
- **Implementation**: `PCFReplenishment` model extension

**c. Once submitted and approved, automatically recorded in Conso without manual re-entry**
- **Current**: Manual re-entry required from PCF replenishment to CONSO
- **Decision**: Auto-create CONSO batch entry when PCF replenishment is submitted + approved
- **Flow**: `PCFReplenishment approved` → `CONSOBatch created` with RFP-like lines
- **Implementation**: Service method `PCFService.to_conso()` or `CONSOService.from_pcf_replenishment()`

---

### **8. Cost Centers**

**a. DHPP — Distribution and Hauling of Petroleum Products**
**b. DMIE — Distribution of Machineries and Industrial Equipment**
**c. OPS — Other Products and Services**

**d. Shorten the box space for display**
- **Current**: Cost centers display fully in UI
- **Decision**: Truncate/shorten display to reasonable width (e.g., "AG" instead of "AG-Accounting"; "OS" instead of "OS-Operations")
- **Implementation**: Template display logic + possible `cost_center_code` shortcut field

**e. Cost centers: AG-Accounting; OS-Operations; TL-Technical Services; HRAC-HR/Audit/Compliance**

**f. Peso values with commas: 2,500.00; 10,000.00; 50,000.00 and etc**
- **Current**: `money` filter already formats with thousand separators + 2dp
- **Verification**: Ensure consistent display across all screens (list cards, tables, reports)
- **Reference**: `apps.ui.filters.money` — `f"{Decimal(value):,.2f}"`

---

### **9. UI/UX Usability Specifications**

**a. Supplier box & COA: type name, choices provided (auto-complete)**
- **Current**: Standard dropdown select
- **Decision**: Add type-ahead/autocomplete search functionality
- **Implementation**: Django HTMX + vanilla JS autocomplete, or django-select2 widget

**b. COA: when user enters or searches for a COA number or COA description, the corresponding COA account should automatically appear/display directly**
- **Current**: Search/filter via queryset; no auto-display
- **Decision**: Implement auto-display on search/filter
- **Implementation**: Query logic in view + template render showing account code/name when matched

**c. RFP AMOUNT — minimum amount: ₱2,000 and above, not ₱2,500**
- **Current**: Threshold check logic exists (per ADR-022: P2,500 threshold rule)
- **Decision**: Change minimum from ₱2,500 to ₱2,000
- **Implementation**: Update `RFPService.create_rfp()` threshold validation; `ADR-022-p2,500-threshold-rule.md` consideration

**d. Revised RFP from leaslyn cannot be approved by Accounting Head/Finance, cannot be forwarded to Ellen for Check voucher issuance**
- **Decision**: Enforce approval gates on revised RFPs
- **Mechanism**: 
  - Revised RFP status tracking (`revision_count`)
  - Finance Head can add notes for Ellen (specific user/role)
  - Blocked from Head/Finance approval until notes added

**e. Finance Head can put notes for Ellen**
- **Decision**: Add notes/audit trail field on RFP for Finance Head → Ellen communication
- **Implementation**: `rejection_note`/`finance_notes` field on `RFPDocument`; UI textarea in `rfp_form.html`

**f. For Petty Cash REPLENISHMENT: corresponding GL Account Name should automatically appear when the GL Account Number is entered or searched**
- **See section 7a above**

**g. Petty Cash Replenishment Integration: Once submitted and approved, automatically recorded in Conso without requiring manual re-entry**
- **See section 7c above**

---

### **10. PR and PO Rules**

**Required**: Purchase Request from Inventory/Warehouse Department → routes to Accounting for Purchase Order.

**Rules**:
- Requests entered in Inventory System/inventoriable → make PR and PO
- Requests that are expensive outright → no longer made a PR and PO
- Requests to be used immediately → no longer made a PR and PO
- Requests that are not inventoriable → no longer made a PR and PO

**Decision**: Implement PR/PO workflow logic:
- PR creation view with inventoriable/non-inventoriable flag
- Routing logic: Inventory Dept → Accounting for PO approval
- PO creation view with RFP generation capability (or linkage)
- Skip PR/PO for immediate/expense-type requests

**Out of UAT scope** (per ADR-017): "Consideration for later — add PR/PO/RR screens to complete procure-to-pay chain upstream of RFP."

---

## ✅ SPECIFICATIONS SUMMARY TABLE

| # | Module | Spec | Priority | Status |
|---|--------|------|----------|--------|
| 1 | GL | GL entries → Trial Balance (RFP + CV) | Critical | ⬆ New |
| 2 | AR | AR cash-in: Receipts → Aging → Collections | High | ⬆ New |
| 3 | AP | Full CV flow: RFP → CONSO → CV sign/release/clear | High | ⬆ New (through CV only) |
| 4 | Fixed Assets | Filter/categorize + automated depreciation + reversal | Medium | ⬆ New |
| 5 | COA | Normal balance corrections + rename/add + printout | High | ⬆ New |
| 6 | Supplier | Auto-code + contact persons + link to RFP | Medium | ⬆ New |
| 7 | PCF | Auto GL name + customer name + Conso integration | Medium | ⬆ New |
| 8 | Cost Centers | DHPP/DMIE/OPS + shorten display + comma formatting | Medium | ⬆ New (reiteration) |
| 8 | UI/UX | Type-ahead Supplier/COA + auto-display + printout | Medium | ⬆ New |
| 9 | RFP | Minimum ₱2,000 (not ₱2,500) + revision audit + Finance notes for Ellen | High | ⬆ Reiteration |
| 10 | PR/PO | Inventory Dept → Accounting routing rules | Low | ⬇ Post-UAT (per ADR-017) |

---

## 📦 IMPLEMENTATION PRIORITY ROADMAP

### **Phase 1: Critical (UAT Extension)**
- [ ] GL module: RFP approval → GL entries → Trial Balance
- [ ] CV flow: Complete sign/release/clear chain with head approval
- [ ] RFP minimum amount: ₱2,000 threshold update
- [ ] RFP revision audit trail + Finance Head notes

### **Phase 2: High (Accounting Specifications)**
- [ ] COA: Normal balance corrections (Accumulated Dep=CREDIT, etc.)
- [ ] Supplier: Auto-generated code + contact persons
- [ ] COA: Type-ahead search + auto-display
- [ ] Peso formatting with commas verification

### **Phase 3: Medium (Usability + Integration)**
- [ ] Fixed Assets: Filter + automated depreciation
- [ ] PCF: Auto GL name + Conso integration
- [ ] Cost centers: DHPP/DMIE/OPS + shortened display
- [ ] AR: Aging + Collections summary

### **Phase 4: Post-UAT (Per ADR-017)**
- [ ] PR/PO: Inventory Dept → Accounting routing
- [ ] RR/Goods Received: Inventory tie-in
- [ ] Supplier Invoice: Full invoice data entry

---

## 🔍 OPEN QUESTIONS (Require User Confirmation)

1. **GL integration scope**: Should GL entries auto-create from RFP approval ONLY, or also from CONSO approval, CV sign/release/clear, and PCF activities?

2. **CV full flow**: User said "testing until CV part only" — should the AP flow beyond CV (cleared → bank payment → reconciliation) be included in this patch or is it post-UAT?

3. **PR/PO workflow**: Per ADR-017, this is "consideration for later." Should we implement any PR/PO logic now, or strictly post-UAT?

4. **Fixed Assets depreciation**: Should depreciation be automatic every month-end close, or triggered manually via management command? What about existing assets (re-calculate?)

5. ** Petty Cash Conso integration**: When PCF replenishment is approved, should it auto-create ONE CONSO entry, or multiple entries per expense account segment?

6. **Cost center display**: Should we add `cost_center_code` shortcuts (AG, OS, TL, HRAC) alongside full names (AG-Accounting, OS-Operations)?

7. **Ellen identification**: Who is "Ellen" in the system? Is she a User role? What approval role? This affects the RFP revision note flow.

8. **AR flow depth**: Aging → Collections Summary — should this include automatic dunning notices or just reporting?

---

## 📄 REFERENCES (Existing ADRs & Code)

- **ADR-009**: Modular apps — thin UI over services
- **ADR-017**: Purchase-to-Pay cycle — RFP → CONSO → CV wired; PR/PO/RR out of scope
- **ADR-018**: RFP Document model — JE embedded in RFP
- **ADR-022**: P2,500 threshold rule — PCF vs RFP boundary
- **ADR-036**: Approval roles — staff/head/coo model
- **ADR-020**: Reject/revise cycle — RFP reject + revise
- **ADR-027**: Petty Cash Funds — PCF trigger 85%
- **Code**: `apps.ap.models.RFPDocument`, `apps.ap.services.RFPService`, `apps.ap.models.CheckVoucher`, `apps.cash.models.PettyCashFund`, `apps.foundation.models.Account`

---

## 📌 NOTES FOR EXECUTION AGENT

- This ADR supplements (does not replace) ADR-017
- Critical path: GL integration + RFP amount threshold + CV head approval
- UI changes needed: type-ahead search, form validations, print buttons
- Model changes: `Account.normal_balance`, `Supplier.code` generation, `PCFReplenishment` extensions
- Test impact: Pytest suite (currently 97/98 pass); new modules will need additional tests
- Live DB state: Clean (55 posted opening JEs, 4 PCF funds at 85% trigger, etc.)

---

**End of ADR-038**