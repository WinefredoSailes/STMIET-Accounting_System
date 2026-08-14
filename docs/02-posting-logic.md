# Posting Logic & Journal Entry Patterns

## Overview

The accounting cycle follows a **"Collection First, Recognition Later"** model. Clients typically **prepay** for fuel (or have existing unearned revenue balances), and revenue is recognized only when fuel is delivered.

---

## Accounting Cycle Flow

```
 COLLECTION EVENT                     DELIVERY EVENT
 (Client pays)                        (Fuel delivered)
      │                                      │
      ▼                                      ▼
Dr: Bank Account                     Dr: Unearned Revenue
Cr: Unearned Revenue                 Cr: Sales - Fuel Hauling
      │                                      │
      │                                      │
      ▼                                      ▼
 Credit Balance (Liability)          Revenue Recognized (P&L)
 (Obligation to deliver)             (Liability extinguished)
```

---

## Bank Codes (From AR-BLUE CODE Sheet)

| Code | Bank Name | Type |
|------|-----------|------|
| BNC | BDO Network - CHECKING | Checking |
| CBS | China Bank - SAVINGS | Savings |
| EWC | EastWest - CHECKING | Checking |
| FVC | First Valley - CHECKING | Checking |
| KBS | Katipunan Bank - SAVINGS | Savings |
| MBC | Metrobank - CHECKING | Checking |
| PNC | PNB - CHECKING | Checking |
| PSC | PSBC - CHECKING | Checking |
| PSS | PSBC - SAVINGS | Savings |
| RCS | RCBC - SAVINGS | Savings |
| COH | Cash/Check on Hand | Physical cash |
| PNO | PNB - OPEX | Operating expense account |
| ARC | A/Receivables - CNR | Receivable (GCash) |

---

## Journal Entry Patterns (Real Examples from AR-BLUE 2026)

### 1. Standard Fuel Collection (Prepayment)

| Transaction | Dr | Cr | Amount |
|------------|-----|-----|--------|
| Gasoline payment via PSBC Savings | PSBC-SAVINGS (Bank) | Unearned Revenue - OPS (21016) | P 2,350 |
| Diesel payment via PNB Checking | PNB-CHECKING (Bank) | Unearned Revenue - DHPP (21000) | P 51,300 |

### 2. Service/Job Order Collection

| Transaction | Dr | Cr | Amount |
|------------|-----|-----|--------|
| Calibration fee via RCBC Savings | RCBC-SAVINGS (Bank) | Job Orders (43016) | P 1,500 |
| Recalibration via PSBC Savings | PSBC-SAVINGS (Bank) | Unearned Revenue - OPS (21016) | P 1,300 |

### 3. Machine Downpayment (DMIE Segment)

| Transaction | Dr | Cr | Amount |
|------------|-----|-----|--------|
| 5KL TSRO machine downpayment via EW Checking | EASTWEST-CHECKING (Bank) | Unearned Revenue - DMIE (21023) | P 400,000 |
| Full payment on 5KL machine via MB Checking | METROBANK-CHECKING (Bank) | Unearned Revenue - DMIE (21023) | P 173,500 |

### 4. Intercompany (STPC) Transactions

| Transaction | Dr | Cr | Amount |
|------------|-----|-----|--------|
| Collection of STPC receivables via PNB Checking | PNB-CHECKING (Bank) | Due from STPC - DHPP (15000) | P 30,378.29 |
| Short-term loan from STPC via MB Checking | METROBANK-CHECKING (Bank) | Other Payables - Current - DHPP (25500) | P 500,000 |
| Repayment of short-term loan via MB Checking | METROBANK-CHECKING (Bank) | Other Payables - Current - DHPP (25500) | P 93,900 |

### 5. Miscellaneous / Others

| Transaction | Dr | Cr | Amount |
|------------|-----|-----|--------|
| GCash deposit (receivable from CNR) | A/Receivables - CNR (ARC) | Unearned Revenue - OPS | P 1,500 |
| Fuel assistance income (E.Tan) via MB Checking | METROBANK-CHECKING (Bank) | Miscellaneous Income - DHPP (43060) | P 50,000 |
| Cancelled transaction (full reversal) | EASTWEST-CHECKING (Bank) | Unearned Revenue - DMIE | P 457,200 (reversal) |
| COC processing service via FV Checking | FIRST VALLEY-CHECKING (Bank) | Service Income (43026) | P 18,890 |

---

## Accounting Department's Weekly JEs

### PAYMENT RECEIPTS Sheet Pattern

At end of each cycle, accounting posts **aggregate JEs per bank**:

```
Dr: Cash in Bank_PNB-DHPP (10040)
Dr: Cash in Bank_MBTC-DHPP (10080)
Dr: Cash in Bank_FVB-DHPP (10030)
Dr: Cash in Bank_PSBC CHECKING-DHPP (10110)
Dr: Cash on Hand-DHPP (10010)
Dr: A/Receivables - Other Current (for GCash)
   Cr: A/Receivables - Fuel Clients (collections of previous cycle AR)
   Cr: Unearned Revenue - DHPP (net payables set up)
```

### UPON DELIVERY Sheet Pattern

When fuel is delivered:

```
Dr: Unearned Revenue - DHPP (21000)
   Cr: Sales - Fuel Hauling (40000)
```

Additional adjustments for overpayments:

```
Dr: A/Receivables - Fuel Clients (12030)    [if overpayment detected]
   Cr: Sales - Fuel Hauling (40000)
```

---

## Chart of Accounts (DHPP Segment)

| GL No. | Account Name | Type |
|--------|-------------|------|
| **10000-15500** | **ASSETS** | |
| 10010 | Cash on Hand - DHPP | Asset |
| 10020 | Cash in Bank_EW - DHPP | Asset |
| 10030 | Cash in Bank_1VB - DHPP | Asset |
| 10040 | Cash in Bank_PNB - DHPP | Asset |
| 10050 | Cash in Bank_PSBC - DHPP | Asset |
| 10060 | Cash in Bank_KB - DHPP | Asset |
| 10070 | Cash in Bank_BDO Unibank - DHPP | Asset |
| 10080 | Cash in Bank_MBTC - DHPP | Asset |
| 10110 | Cash in Bank_PSBC CHECKING - DHPP | Asset |
| 12020 | A/Receivables - Other Current - DHPP | Asset |
| 12030 | A/Receivables - Fuel Clients | Asset |
| 12040 | Advances to Suppliers - DHPP | Asset |
| 15500 | Due from Other Cos. - DHPP | Asset |
| 13000-13020 | **INVENTORIES** | |
| 13000 | Fuel Inventory | Asset |
| 13010 | Fuel Inventory at Dohinob | Asset |
| 13020 | Fuel Inventory at Office | Asset |
| **20000-25500** | **LIABILITIES** | |
| 20000 | A/Payables - Current - DHPP | Liability |
| 21000 | Unearned Revenue - DHPP | Liability |
| **40000-4300** | **REVENUE** | |
| 40000 | Sales - Fuel Hauling | Revenue |
| 43016 | Job Orders | Revenue |
| 43026 | Service Income | Revenue |
| 43060 | Miscellaneous Income - DHPP | Revenue |
| **50000-5403** | **COGS** | |
| 50000 | COGS - Fuel Purchase | Expense |
| 50020 | COGS - Gasoline Expenses | Expense |
| **6000-6190** | **OPERATING EXPENSES** | |
| 6100 | EXP - Salaries | Expense |
| 6110 | EXP - Administration | Expense |
| 6120 | EXP - Electricity, Water, Phone | Expense |
| 6130 | EXP - Rent | Expense |
| 6140 | EXP - Insurance | Expense |
| 6150 | EXP - Repair and Maintenance | Expense |
| 6160 | EXP - Office Supplies | Expense |
| 6170 | EXP - Depreciation Equipment | Expense |
| 6180 | EXP - Depreciation Vehicles | Expense |
| 6190 | EXP - Gasoline Expenses | Expense |
| **7000-8200** | **OTHER INCOME/EXPENSES** | |
| 7100 | Finance Charge Income | Income |
| 8100 | EXP - Interests | Expense |
| 8200 | EXP - Bank Charges | Expense |

---

## Product Codes & Pricing Structure

### Product Categories

| Code Range | Category | Segment |
|-----------|----------|---------|
| 111-151 | Fuel Products (Gasoline, Diesel, Jet Fuel, LPG, Kerosene) | DHPP |
| 211-212 | Tanks & Containers | DMIE |
| 2211-2220 | Fuel Dispensers (TSRO Machines) | DMIE |
| 2221-2227 | Fuel Dispenser Parts | DMIE |
| 2231-2232 | Lubricants | DHPP |
| 2241-2249 | Gauges & Accessories | DMIE |
| 711-731 | Services (Job Orders, Recalibration, COC Processing) | OPS |
| 751-761 | Other Services | OPS |

### Three-Tier Pricing Structure (From Collection System Macro)

| Price Tier | Description |
|------------|-------------|
| **Regular Price** | Standard price per liter |
| **Patron Price** | Discounted price for regular customers |
| **Volume Price** | Wholesale/volume discount price |

### Per-Product Variable Pricing

Prices change almost every cycle. The macro tracks separate prices for:
- **Premium (XCS)** — Gasoline premium
- **Regular (REG)** — Gasoline regular
- **Diesel (ADO)** — Automotive diesel oil

Each has its own Regular, Patron, and Volume price per cycle.
