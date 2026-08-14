# Customer Ledger System (The "Macro")

## Overview

The **COLLECTION SYSTEM- DHPP - macro (5).xlsm** is the per-client cycle ledger that Mich uses to track each customer's orders, payments, and running balances. This is the most detailed operational document showing exactly how DHPP fuel transactions are tracked.

---

## Workbook Structure

### DASHBOARD Sheet (Row 1 = Client Summary)

| Column | Content | Example |
|--------|---------|---------|
| No. | Sequential number | 1 |
| CDC | Client Designated Code | DH1000 |
| Coding (from Operations) | Operations code name | Bacong Bulilit |
| Registered Business Name | Legal business name | HI-LAND FUEL REFILLING STATION |
| Supplier's Name | Owner/contact person | SITTI MAIRA LANGAN ANDAL |
| Business Address | Full address | BRGY. BACONG, SALUG, ZAMBONGA DEL NORTE |
| Unpaid Balances (AR, Dr.) | Amount client owes | (blank) |
| Overpayments (Unearned, Cr.) | Amount in excess credit | P 5.00 |
| Last Updated On | Timestamp | 2025-11-11 15:31:28 |
| Summary | Net balance | P 5.00 |

### CDC Code Pattern

All DHPP clients use prefix **DH** followed by a 4-digit sequential number:
- DH1000 — Bacong Bulilit
- DH1002 — Aseniero
- DH1004 — Bacong Pamil
- ...through ~DH1300+ range

---

## Per-Client Sheet Structure

Each of the 120+ client sheets follows an identical 46-column format:

### Header Block

```
OPERATIONS CODE:    [Client short name]
BUSINESS NAME:      [Registered business name]
OWNER:              [Owner/operator name]
ADDRESS:            [Full address]
CONTACT NOS:        [Phone numbers]
CDC:                [DHxxxx code]
UPDATE AS OF:       [Timestamp]
SUMMARY OF ACCOUNT: [Running balance] [Status text]
```

### Cycle Tracking Columns

| Section | Columns | Description |
|---------|---------|-------------|
| **FUEL ORDER (a)** | X, R, D | Quantity ordered: Premium, Regular, Diesel (in liters) |
| **PRICES** | | Three price tiers per product |
| | Regular Price (b) | X, R, D — Standard price per liter |
| | Patron Price (c) | X, R, D — Discounted price |
| | Volume Price (d) | X, R, D — Volume discount price |
| | | |
| **AMOUNTS PAYABLE** | X-Amount (e), R-Amount (f), D-Amount (g) | Computed: Qty × Price |
| **TOTAL ACTUAL PAYMENTS** | | |
| | Premium (h) | PO# and amount paid for Premium |
| | Regular (i) | PO# and amount paid for Regular |
| | Diesel (j) | PO# and amount paid for Diesel |
| | Payment of Previous Balances (k) | Catch-up payments |
| | Offset Overpayment (l) | Using excess credits |
| | Total Payments | Sum of all payments this cycle |
| | | |
| **OVERPAYMENT (+)** | X, R, D | Payment > Amount Payable (per product) |
| **COLLECTIBLES (-)** | X, R, D | Amount Payable > Payment (per product) |
| **CUMULATIVE BALANCE** | | Running total across cycles |
| **DISCLOSURE** | Payment references | Bank + AR# + amount per payment (up to 5 entries) |
| **STATUS** | | Order status |

---

## Cycle Naming Convention

Cycles run **Wednesday to Tuesday** weekly:

| Cycle | Dates |
|-------|-------|
| FEBRUARY 4-10, 2025 | Week 1 |
| FEBRUARY 11-17, 2025 | Week 2 |
| FEBRUARY 18-24, 2025 | Week 3 |
| FEBRUARY 25-MARCH 3, 2025 | Week 4 |
| MARCH 4-10, 2025 | Week 5 |
| ...continues weekly | |

---

## Real Transaction Example (Villahermosa — Row 62)

```
Cycle:               DEC. 16-22, 2025
Fuel Order:          X=1, R=0, D=0  (1 unit Premium)
Prices (Reg/Pat/Vol): X=92.05/54.75/52.20
X-Amount Payable:    52,200
PO#:                 12C 3125
Payment Amount:      51,500 (Premium)
Overpayment/(Deficit): -700 (collectible)
Cumulative Balance:   -700
Payment Reference:   AR 52733 12/19/2025 = 51,500.00
```

Another entry for same client in same cycle:
```
Fuel Order:          X=0, R=0, D=0.5 (0.5 Diesel)
R-Amount Payable:    0
D-Amount Payable:    25,550
PO#:                 12D 3221
Payment Amount:      25,550 (Diesel)
Overpayment/(Deficit): 0
```

---

## Business Rules Embedded in the Macro

1. **Overpayment Handling:** If payment exceeds computed amount payable, the excess carries forward as a credit balance (Unearned Revenue) for the next cycle.

2. **Collectibles Handling:** If payment is less than amount payable, the deficit carries forward as an accounts receivable (collectible).

3. **Offset Logic:** Previous cumulative balances are automatically factored into the next cycle's computation.

4. **Multiple PO# per Cycle:** A client may pay for multiple PO#s within the same cycle, each tracked separately.

5. **Payment Splitting by Product:** A single payment can be split across Premium, Regular, and Diesel within the same cycle (each with its own PO# and amount).

---

## Supplier Codes (120+ Active Codes)

The system tracks **121 supplier codes** in the General Journal, including:

| Code Type | Examples |
|-----------|----------|
| Internal | MTHSI, INVTY, INVTY-DOH, INVTY-OFFICE |
| Client codes | Aseniero, Bacong Bulilit, Bacong Pamil... |
| - | All 120+ DH-coded clients from the Dashboard |

These correspond to the CDC codes from the Collection System. The "SUPPLIER CODE" sheet in the General Journal uses a simplified naming convention (location names only, without the DH prefix or full business name).
