# Multi-Tenant Architecture

## Overview

The business operates across **multiple segments (tenants)** that share the same cashier (Mich) but have separate accounting treatment. Each segment has its own chart of accounts, revenue recognition rules, and intercompany relationships.

---

## Business Segments

| Segment | Full Name | GL Prefix | Primary Business |
|---------|-----------|-----------|-----------------|
| **DHPP** | Distribution and Hauling of Petroleum Products | 10000-50000 | Fuel hauling, diesel/gasoline delivery to gas stations |
| **DMIE** | (Industrial Equipment / Machinery) | 21023 range | TSRO machine sales, dispensers, tanks, parts |
| **OPS** | Operations / Services | 21016 range | Calibration, recalibration, COC processing, job orders |
| **STPC** | Seven-Trent Petroleum Corp. | 15500 | Sister company; intercompany transactions |

---

## Separate Unearned Revenue Accounts

Each segment has its **own liability account** for unearned revenue:

| Segment | GL Account | Account Name |
|---------|-----------|-------------|
| DHPP | 21000 | Unearned Revenue - DHPP |
| DMIE | 21023 | Unearned Revenue - DMIE |
| OPS | 21016 | Unearned Revenue - OPS |

This is the key multi-tenant indicator: when Mich posts a collection, she needs to know **which segment** the payment belongs to so she credits the correct Unearned Revenue account.

---

## Segment-Specific Revenue Recognition

| Segment | When Revenue is Recognized | Typical Dr | Typical Cr |
|---------|---------------------------|------------|------------|
| DHPP | Upon fuel delivery to client | Unearned Revenue - DHPP (21000) | Sales - Fuel Hauling (40000) |
| DMIE | Upon machine installation/delivery | Unearned Revenue - DMIE (21023) | (Machine Sales Revenue) |
| OPS | Upon service completion (calibration, etc.) | Unearned Revenue - OPS (21016) or direct to revenue | Service Income (43026) / Job Orders (43016) |

---

## Segment-Specific Product Codes

### DHPP Products (Fuel)

| Code | Product | Subcategory |
|------|---------|-------------|
| 111 | Premium (RON95) | Gasoline |
| 112 | Regular (RON91) | Gasoline |
| 121 | Diesel (Krudo) | Diesel |
| 131 | Jet Fuel | Aviation |
| 141-144 | LPG | Liquefied Petroleum |
| 151 | Kerosene | Kerosene |

### DMIE Products (Machinery & Equipment)

| Code | Product | Category |
|------|---------|----------|
| 211 | Storage tanks | Tanks & Containers |
| 212 | Barrels / Drums | Tanks & Containers |
| 2211 | 1.5 KL TSRO Standard Machine | Fuel Dispensers |
| 2212 | 1.5 KL TSRO Standing Machine | Fuel Dispensers |
| 2213 | 2.0 KL TSRO Standard Machine | Fuel Dispensers |
| 2214 | 2.0 KL TSRO Standing Machine | Fuel Dispensers |
| 2215 | 3.0 KL TSRO Standard Machine | Fuel Dispensers |
| 2216 | 3.0 KL TSRO Standing Machine | Fuel Dispensers |
| 2217 | 5.0 KL TSRO Standard Machine | Fuel Dispensers |
| 2218 | 5.0 KL TSRO Standing Machine | Fuel Dispensers |
| 2219 | 6.0 KL TSRO Standard Machine | Fuel Dispensers |
| 2220 | 6.0 KL TSRO Standing Machine | Fuel Dispensers |
| 2221 | Transfer Pump | Parts |
| 2222 | Hose | Parts |
| 2223 | Nozzle | Parts |
| 2224 | Coupling | Parts |
| 2225 | Strainer | Parts |
| 2226 | Pump | Parts |
| 2227 | Meter | Parts |
| 2231 | 2T Oil | Lubricants |
| 2232 | Deomax 15W-40 Oil | Lubricants |
| 2241-2249 | Various gauges & accessories | Accessories |

### OPS Products (Services)

| Code | Service | Category |
|------|---------|----------|
| 711 | National (service area) | National Services |
| 712 | Sea-Oil (service area) | Sea-Oil Services |
| 721 | Job Order | Job Orders |
| 731 | Other OPS (Pls. Specify) | Other Operations |
| 751 | Other Services (Pls. Specify) | Other Services |
| 761 | Others (Pls. Specify) | Miscellaneous |

---

## Intercompany (STPC) Relationship

**STPC** (Seven-Trent Petroleum Corp.) is a sister company whose gas stations (~4 locations) are managed separately. Transactions include:

| Transaction Type | Account | Direction |
|-----------------|---------|-----------|
| Collection of STPC receivables | Due from STPC - DHPP (15500) | Client → STPC → DHPP |
| Short-term loans to STPC | Other Payables - Current (25500) | DHPP → STPC |
| Fuel assistance income | Miscellaneous Income - DHPP (43060) | DHPP Income |

The STPC-San Pedro client code appears frequently in the monitoring sheet as both a **customer** (fuel purchases) and **intercompany debtor** (receivables collection).

---

## Segment Detection Rule

When posting a transaction, Mich determines the segment from:

1. **Product/Service Code** — The first digit of the product code often indicates the segment:
   - 1xx → Fuel → DHPP
   - 2xxx → Equipment → DMIE
   - 7xx → Service → OPS

2. **CR Account Selected** — The Unearned Revenue account chosen indicates the segment:
   - 21000 → DHPP
   - 21023 → DMIE
   - 21016 → OPS

3. **Customer Profile** — Some customers are exclusively DHPP, others are DMIE or mixed.

---

## Implications for System Design

| Requirement | Impact |
|------------|--------|
| **Per-segment chart of accounts** | System must support separate CoA per tenant |
| **Segment-aware posting** | User must select segment; system auto-suggests correct GL accounts |
| **Separate revenue reporting** | P&L must be filterable by segment |
| **Intercompany reconciliation** | Need to track due-to/due-from between DHPP and STPC |
| **Unearned Revenue by segment** | Cannot use a single Unearned Revenue account; must split by segment |
| **Per-segment product catalog** | Products must be assigned to a segment at setup |

---

## Data Distribution

| File | Covers |
|------|--------|
| AR -BLUE 2026.xlsx (MONITORING) | All segments (DHPP, DMIE, OPS) in one sheet |
| COLLECTION SYSTEM - DHPP - macro (5).xlsm | DHPP only (per-client ledger) |
| General_Journal_DHPP TRANSACTIONS.xlsx | DHPP only (full GL) |
| Cashier shadow notes | All segments (mentions DMIE and OPS examples) |
