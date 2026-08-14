# ADR-032: Voucher Format Specification (Check Voucher + Petty Cash Voucher)

**Status:** Accepted
**Date:** 2026-08-14
**Deciders:** Architecture Team

**References:**
- [VOUCHER FORMS - CASH AND CHECK (1).xlsx](../observation-outputs/Cashflow-output-folder/VOUCHER%20FORMS%20-%20CASH%20AND%20CHECK%20(1).xlsx) — authoritative workbook (source of this ADR)
- [ADR-017: Purchase-to-Pay Cycle](./ADR-017-purchase-to-pay-cycle.md) — voucher documents in flow
- [ADR-018: RFP Document Model](./ADR-018-rfp-document-model.md) — ACCTG-FOR document numbering
- [ADR-022: P2,500 Threshold Rule](./ADR-022-p2,500-threshold-rule.md) — when each form is used

---

## Context

The system will PRINT two physical voucher forms that currently exist only as Excel templates:
1. **CHECK VOUCHER** — ACCTG-FOR-010, Effective Date 08.18.2022, Revision 02
2. **PETTY CASH VOUCHER** — ACCTG-FOR-002, Effective Date 09.24.2024, Revision 00

The user requires that **printed output from the system matches the uploaded workbook exactly**. This ADR is the pixel-level specification for reproducing both forms, plus the official fill-out guidelines (GUIDELINES sheet).

Source workbook sheets: `CHECK V (2)` (blank template, 2 forms/page), `Sheet1` (identical layout, sample data), `PETTY CASH V` (blank template, 2 forms/page), `PCF TEMP` (single-form layout variant), `GASPAY`/`RON`/`LEITOURGOS`/`VILLANUEVA`/`CARTRACK`/`CELESTIAL`/`SAILES`/`BAGATUA`/`salary`/`PCF` (filled sample check vouchers), `GUIDELINES`.

---

## Decision

Reproduce both forms exactly per the specifications below. The workbook is the master; any ambiguity resolves to the workbook, not to this summary.

---

## 1. CHECK VOUCHER — ACCTG-FOR-010 (Rev 02, eff 08.18.2022)

### Page Setup
- Portrait, paper size **A4** (Excel paperSize 9)
- **Two forms stacked per page** (rows 1-28 = form 1, rows 31-54 = form 2)
- Column widths (chars): A=14.6, B=6.0, C=14.7, D=15.3, E=27.9, F=13.1, I=14.9, J=12.6, K=14.3, L=11.6, M=14.3, N=11.3, O=9.3
- Row heights: header block rows 2-5 and section rows = **18.8**; row 5 = 38.2 (revision block); title row 1 = 12.8; line-item rows 12-22 = 18.8 (rows 18-22 = 19.5); row 11 (column headers) = 25.5; TOTAL AMOUNT row 23 = 29.2; disclaimer row 24 = 18.8; signature rows 25-28 = 18.8; blank rows 29-30 = 38.2/12.8

### Header Block (rows 1-6)
- Row 1: empty
- Row 2: **"CHECK VOUCHER"** — Arial **36 pt bold**, merged **E2:I5** (title spans columns E-I). Right side (J2): "ACCOUNTING DEPARTMENT"
- Row 3-5 (right-aligned, Arial 7-9pt): "Document No.: **ACCTG-FOR-010**" / "Effective Date: **08.18.2022**" / "Revision No.: **02**"
- Row 6: "SN:" (left, under title)

### Payee Information (row 7-10)
- Row 7: "PAYEE INFORMATION" (Arial 9 bold) — merged **B8:G8** for the name value
- Row 8: "NAME:" → payee name (uppercase, e.g., "WINEFREDO S. SAILES C/O CNR"); "DATE OF REQUEST:" (H8) → value in J8 (right block, merged J9:K9 for check info)
- Row 9: "POSITION:" → e.g., "IT", "FINANCE AND ACCTG HEAD"; "CHECK ISSUED & NO:" (H9) → **do NOT fill out — Finance/Acctg only** (examples: "PNB 2000001121", "EW 101870", "ONLINE / MBTC 1244198460")
- Row 10: "DISTRIBUTION CHARGES:" (label; value space)

### Purpose of Payment Table (rows 11-22)
Row 11 (Arial 9 bold, row height 25.5):
| A-E (merged A11:E11) | F11 | G11 | H11 | I11 | J11 |
|---|---|---|---|---|---|
| PURPOSE OF PAYMENT | ENTITY | SEGMENT | COST CENTER | GL ACCOUNT | AMOUNT |

Line-item rows (12-22, 18.8pt):
- **A**: item description / purpose (merged F12:F22, G12:H22, J11:K11 for amounts)
- **D**: quantity (e.g., "4.0") | **E**: unit price (e.g., "335.0") — unit-price format supports multi-item vouchers
- **F**: ENTITY (STMIET / STPC / IPPC / ALL — may be "STMIET/STPC")
- **G**: SEGMENT (DHPP / DMIE / OPS / ALL)
- **H**: COST CENTER (code from GUIDELINES, e.g., OS, AS, AG)
- **I**: GL ACCOUNT description (e.g., "PF", "Tax", "VRM", "Subscription", "AP / Cash")
- **K**: line amount (= qty × unit price; "TOTAL AMOUNT" of form 1 sums to J23)

Multiple purpose lines allowed (see GASPAY sample: 3 lines — Bookkeeping Services 4,500.00 + VAT 1,491.93 + Income Tax 250.00 = 6,241.93).

### Total & Disclaimer (rows 23-24)
- Row 23: "OTHER REMARKS:" (left, merged C23:G23 in Sheet1); "**TOTAL AMOUNT**" (I23, Arial 11 bold) → value J23
- Row 24 (Arial 8): "Each check issued shall be supported with sufficient documentation. Failure to do so shall constitute  neglect  to the requester and/or the department"

### Signature Block (rows 25-28)
Five columns (A/C/E/G/I), each: label row (25) + name row (26-27) + role row (28):

| REQUESTED BY | NOTED BY | CHECKED BY / RECOMMENDING APPROVAL | APPROVED BY | PAYMENT RECEIVED BY |
|---|---|---|---|---|
| (requester name, e.g., "WINEFREDO S. SAILES") | (department head) | (Finance & Acctg head — "Alwyn D. Baje") | (COO — "Clyde N. Rebollos") | (signature over printed name) |
| Print Name/Sign/Date | DEPARTMENT HEAD | FINANCE & ACCTG HEAD | COO | SIGNATURE OVER PRINTED NAME |

- Name rows merged: A27:B27, C27:D27, E28:F28 (role), G27:H27 (COO name), I28:K28 (role)
- In practice: requester and payee names written in full; approvers often initial ("A. BAJE", "CNR")

---

## 2. PETTY CASH VOUCHER — ACCTG-FOR-002 (Rev 00, eff 09.24.2024)

### Page Setup
- Portrait, **A4**, two forms per page (rows 1-28 form 1, rows 30-56 form 2; row 29 = 12.8 separator)
- Column widths: A=13.7, B=14.1, C=13.7, F=11.7, I=15.7, J=12.7, K=13.0, L=11.6, M=14.3, N=11.3, O=9.3

### Differences from Check Voucher
1. Title: **"PETTY CASH VOUCHER"** Arial 36 bold, merged **D2:I5**; header block same (rows 2-5)
2. Row 9 right label is **"REFERENCE:"** (not "CHECK ISSUED & NO:")
3. Table headers identical (row 11, merged A11:E11 = PURPOSE OF PAYMENT)
4. Line items: same structure; description may be multi-row merged (A12 + B13 description continuation in samples)
5. Row 20: disclaimer (Arial 8): "Petty cash voucher shall be submitted with sufficient supporting documents. Failure to do so shall constitute neglect by the requester and/or the depa…"; "**TOTAL AMOUNT**" (I20, Arial 11 bold) → J20
6. **Liquidation rows 22-24** (Arial 8 bold labels):
   - Row 22: "TOTAL LIQUIDATED EXPENSES:" → amount (C22, merged C22 with value)
   - Row 23: "TOTAL CASH RETURNED:"
   - Row 24: "TOTAL UNLIQUIDATED EXPENSES:"
7. Signature block (rows 26-28) — THREE columns:

| REQUESTED BY | APPROVING OFFICERS | PAYMENT RECEIVED BY |
|---|---|---|
| (requester) | DEPARTMENT HEAD + COO (C26:G26 merged; C27=dept head, E27=COO "Clyde N. Rebollos") | SIGNATURE OVER PRINTED NAME (H26:K26) |
| Print Name/Sign/Date | (roles row 28: C28=DEPARTMENT HEAD, E28=COO) | (H28) |

---

## 3. PCF TEMP — Single-Form Layout (variant)

`PCF TEMP` + the filled payee sheets (GASPAY, RON, LEITOURGOS, VILLANUEVA, CARTRACK, CELESTIAL, SAILES, BAGATUA, salary, PCF) use a **one-form-per-page** layout, shifted right:
- Title "CHECK VOUCHER" merged **F2:J5**; "ACCOUNTING DEPARTMENT" at K2; doc no. block K3-L5 (Arial 8)
- Payee info at B7 (label bold 9pt), NAME value merged **C8:H8**, position merged C9:H9
- Table: B11 = PURPOSE OF PAYMENT (merged B11:F11); G11=ENTITY, H11=SEGMENT, I11=COST CENTER, J11=GL ACCOUNT, K11=AMOUNT (headers row 11)
- Line items: B=description, G=entity, H=segment, I=cost center, J=GL account, K=amount
- Row 20: "OTHER REMARKS:" (B20) + "TOTAL AMOUNT" (J20) → K20
- Row 21: check disclaimer (Arial 8)
- Signature rows 22-25: REQUESTED BY / NOTED BY (DEPARTMENT HEAD) / CHECKED BY / RECOMMENDING APPROVAL (FINANCE & ACCTG HEAD) / APPROVED BY (COO) / PAYMENT RECEIVED BY

> **Note:** Column N in these sheets contains non-form helper values (e.g., 351.0) used for print sizing — not part of the visible form.

---

## 4. GUIDELINES (fill-out rules — must be enforced by the system)

| Field | Rule |
|---|---|
| NAME | Required |
| POSITION | Required |
| DATE OF REQUEST | Required |
| CHECK ISSUED AND NO | **Do not fill out** (Finance/Acctg fills after issuance) |
| PURPOSE OF PAYMENT | Must fill out the form |
| ENTITY | One of: **STMIET, IPPC, STPC, ALL** |
| SEGMENT | One of: **DHPP, DMIE, OPS, ALL** |
| COST CENTER | One of the codes below |

### Cost Center Codes (department → code)

| Department | Code | Meaning |
|---|---|---|
| ANNELYN | DH | Distribution and Hauling |
| ANNELYN | SS | Sales |
| ANNELYN | MG | Marketing |
| LIRA | HR | Human Resources |
| LIRA | LS | Logistics |
| LIRA | WG | Warehousing |
| LIRA | AK | Audit Clerk (Monitoring for Tanker) |
| ERMIE | TL | Technical |
| ALYWIN | AG | Accounting |
| ALYWIN | FE | Finance |
| N/A | IT | Information Technology |
| N/A | EO | Executive Officer |
| NA/A | AT | Audit |

---

## 5. Data Conventions Observed in Samples

- Payee names: **uppercase**, often with "C/O" + approver initials ("WINEFREDO S. SAILES C/O CNR")
- Multi-entity vouchers: one line per entity allocation (salary sample lists STPC / IPPC / STMIET on separate lines)
- Multi-item vouchers: qty (D) × unit price (E) per line, amount in K
- GL ACCOUNT column uses account *description* shorthand ("PF", "Tax", "VRM", "Subscription", "Cash in Bank", "AP / Cash", "PREPAID EXP."), not COA numbers
- Payment history may be annotated under the purpose (SAILES: "Previous Payments: 8000.0 11/05/2024"; BAGATUA: N16-N19 running totals) — free-form, no system dependency
- TOTAL AMOUNT = Σ line amounts; system must auto-sum and match to the CV

---

## Consequences

### Positive
- Printed vouchers are byte-identical to the current physical forms — zero staff retraining
- Cost-center code master (GUIDELINES) becomes the system's dropdown source
- CHECK ISSUED & NO remains a post-issuance Finance/Acctg field → printed form leaves it blank
- Two-per-page layout halves paper usage for check vouchers

### Negative
- Fixed column widths mean long descriptions wrap (rows must auto-grow while keeping borders)
- Exact reproduction requires print CSS/grid matching Excel metrics (row heights 18.8/25.5/29.2/38.2, A4 portrait)

### Neutral
- PCF TEMP variant is legacy; new prints should use the standard two-per-page layout, but the single-page layout is preserved for check-size paper use
- GUIDELINES sheet is a controlled document; changes must be mirrored in the system master data
