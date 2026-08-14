# Two-Week Observation Plan (Updated: 2026-07-27)

## Objective

Validate documented workflows against actual day-to-day operations. Identify edge cases, undocumented steps, and pain points before building Phase 1.

## Schedule

| Day | Focus | Person | Duration |
|-----|-------|--------|----------|
| 1-2 | AR & Collections | Mich | 2 days |
| 3-4 | AP, Inventory, Financial Statements | Che | 2 days |
| **5** | **Driver Tariff & Volume** | **Sir Aaron (Operations)** | **1 day** |
| **6** | **Fuel Ordering / Hauling Operations** | **Mam Anne (Operations Head)** | **1 day** |
| 7-8 | Cash, Bank, Treasury | Quibs | 2 days |
| 9-10 | Tax, Payroll, Fixed Assets, JEs, Close | Alywin | 2 days |
| 11 | Cross-functional handoffs + document trace | All | 1 day |
| 12 | Follow-up, gaps, final questions | You | 1 day |

## Structure for Each Person

### Part A — Shadow (sit beside them, watch everything)

Do not ask questions for the first half-day. Just watch.
- What is the first thing they open in the morning?
- What documents arrive? In what order?
- What software/screens do they use?
- What do they write down on paper?
- What do they check/reconcile before posting?
- What causes them to stop and ask someone?
- What do they do when an error is found?

### Part B — Walk-through (second half)

Have them walk you through their complete workflow using **real documents from today**.

### Part C — Specific Questions (end of each person's block)

---

## 1. MICH (AR & Collections) — Days 1-2

### Role: Cash, Collections, AR, Client Accounts, Official Receipts

### Documents She Handles:
| Document | Format | Where does it come from? |
|----------|--------|------------------------|
| Sales Invoice | ? | |
| Collection Receipt | ? | |
| Official Receipt | ? | |
| Bank Deposit Slip | ? | |
| Customer List | ? | |
| AR Aging Report | ? | |
| Client Statement of Account | ? | |

### Observe Specifically:
1. **How does she know a client paid?**
   - Bank notification?
   - Client email?
   - Cashier handoff?
   - GCash/Bank transfer alert?

2. **How does she match payment to invoice?**
   - Is it manual look-up?
   - Does the client reference the invoice?
   - What happens when a client underpays or overpays?

3. **How does she handle the cash collection cycle?**
   - From client payment → deposit slip → JE → GL
   - How does the weekly COLLECTIBLES sheet get populated?
   - Who sends the data from Distribution Dept vs Finance & Accounting?

4. **Customer master pain points:**
   - Show me your current customer list.
   - How many customers do you track?
   - How often do you add a new customer?
   - What information is missing that you wish you had?
   - How do you track customer credit limits?

5. **Official Receipts:**
   - When do you issue an OR? Immediately or on request?
   - Do you have pre-numbered ORs?
   - How do you track used vs unused OR numbers?

6. **AR follow-up:**
   - How do you know which customers are overdue?
   - How do you follow up?
   - What's the worst AR problem you deal with right now?

### Success Metrics (measure before and after system):

| Metric | Current State | Target |
|--------|--------------|--------|
| Time to match payment to invoice | ? | < 5 min |
| Time to produce AR aging report | ? | < 1 min |
| Customer lookup time | ? | < 10 sec |
| OR issuance time | ? | < 2 min |
| AR reconciliation accuracy | ? | 100% |
| Number of customer records | ? | Complete |

### Documents to Collect:
- Copy of current customer list (if any)
- Sample Sales Invoice (blank and filled)
- Sample Official Receipt
- Sample Collection Receipt
- AR Aging if manually prepared

---

## 2. CHE (AP, Inventory, FS, Income Statement) — Days 3-4

### Role: Accounts Payable, Inventory, Financial Statements, Income Statement

### Documents She Handles:
| Document | Format | Where does it come from? |
|----------|--------|------------------------|
| Purchase Request | ? | |
| Purchase Order | ? | |
| Receiving Report | ? | |
| Supplier Invoice | ? | |
| Request for Payment (RFP) | ? | |
| Disbursement Voucher | ? | |
| Inventory Count Sheet | ? | |
| Income Statement | ? | |
| Journal Voucher | ? | |

### Observe Specifically:

1. **AP Workflow (end-to-end):**
   ```
   PR → PO → RR → Supplier Invoice → RFP → Voucher → JE
   ```
   Trace a real purchase from start to finish.
   - Who sends the PR?
   - How does it become a PO?
   - How does she know goods were received?
   - When does she book the supplier invoice? (Upon receipt or upon payment?)
   - How does she decide which account to code?

2. **Multi-segment transactions:**
   - Show me a purchase that spans DHPP, DMIE, and OPS.
   - How does she split the cost?
   - What documents support the split?

3. **Inventory connection:**
   - Does she talk to Adrian (warehouse) daily?
   - How does she know inventory was received?
   - How does she know inventory was sold (COGS)?
   - Show me the current inventory system. What data does it have?
   - What does the inventory system NOT have that accounting needs?

4. **Income Statement preparation:**
   - Walk me through how you produce the IS from scratch.
   - Where does each number come from? (Trace backward)
   - How long does it take?
   - What's the most error-prone part?
   - Show me last month's IS and explain one variance.

5. **Month-end closing:**
   - What's the first thing you do at month-end?
   - What's the last thing?
   - What takes the longest?
   - What requires help from others?

### Success Metrics:

| Metric | Current State | Target |
|--------|--------------|--------|
| Time to process one supplier invoice | ? | < 10 min |
| Time to produce IS | ? | < 5 min |
| PO-to-payment cycle time | ? | Trackable |
| Inventory variance identification | ? | Same day |
| IS accuracy (revisions needed) | ? | 0 revisions |

### Documents to Collect:
- Sample PR form
- Sample PO form
- Sample RR form
- Sample RFP form
- Sample DV form
- Current inventory system screenshot (data fields)
- Current customer list from inventory system
- Last 3 months IS (to understand patterns)

---

## 3. SIR AARON (Operations — Driver Tariff & Volume) — Day 5

### Role: Driver tariff computation, trip volume settlement, Operations

### Why This Matters for Accounting

Sir Aaron's tariff computation directly feeds:
- **AP (Che)** — driver pay RFP amounts
- **COGS - Trip Wages** (50030) — posting rule depends on tariff × volume
- **COGS - Fuel Purchase** (50000) — volume reconciled against collections
- **Treasury (Quibs)** — release of driver payments

### Documents He Handles:
| Document | Format | Where does it come from? |
|----------|--------|------------------------|
| Trip Sheet / Delivery Receipt | ? | Driver / Dispatcher |
| Volume Summary | ? | Mich's collections? Or direct from dispatcher? |
| Tariff Rate Sheet | ? | Who sets the rates? How often do they change? |
| Driver Settlement Sheet | ? | He produces this — where does it go? |
| Trip Settlement Summary | ? | Passed to Che for RFP? |

### Observe Specifically:

1. **How does he get volume data?**
   - From Mich's collection records?
   - From delivery receipts directly from drivers?
   - From dispatcher / substation reports?
   - Does he reconcile these sources against each other?

2. **How is the tariff computed?**
   - Formula: `volume_delivered × rate_per_unit`?
   - Is the rate per liter, per kilometer, or per trip?
   - Are there different rates for different routes? Products? Clients?
   - Does the rate change per cycle (like fuel prices)?
   - What happens when volume is disputed?

3. **What document does he produce?**
   - A "Driver Settlement" or "Trip Pay Sheet"?
   - What fields does it contain? (driver, trip#, vehicle, product, volume, rate, total amount, deductions?)
   - How often does he produce it? Per trip? Daily? Weekly (Wed-Tue cycle)?

4. **Where does his document go next?**
   - To Che (AP) — who creates the RFP for driver payment?
   - To Quibs (Treasury) — who releases payment directly?
   - To Alywin — for approval before payment?
   - To all of the above?

5. **Connection to CollECTIBLES sheet:**
   - Does his volume/tariff data appear in the COLLECTIBLES sheet?
   - How does the "Gross Mark-up" reconciliation relate to driver pay?

6. **Pain points:**
   - Volume discrepancies between delivery receipt and client confirmation?
   - Rate changes not communicated?
   - Late submissions causing AP backlog?
   - Drivers disputing settlements?
   - Manual computation errors?

### Success Metrics:

| Metric | Current State | Target |
|--------|--------------|--------|
| Time to compute one driver settlement | ? | < 5 min |
| Settlement frequency | ? | Per trip / daily |
| Volume discrepancy rate | ? | < 1% |
| Time from trip completion → settlement to Che | ? | Same day |
| Number of driver disputes per month | ? | 0 |

### Documents to Collect:
- Sample Trip Sheet / Delivery Receipt
- Sample Driver Settlement (blank and filled)
- Tariff rate sheet or pricing guide
- Volume summary report (if exists)
- Any reconciliation sheet he uses

---

## 4. MAM ANNE (Operations — Fuel Ordering & Hauling Ops Head) — Day 6

### Role: Fuel PO generation, depot ordering, hauling operations oversight

### Why This Matters for Accounting

Mam Anne's fuel ordering triggers:
- **Advances to Suppliers** (Dr when fuel ordered / paid)
- **Fuel Inventory** (when fuel picked up / received)
- **AP (Che)** — depot invoices matched against her POs
- **Quibs (Treasury)** — payment to depot based on orders

### Documents He Handles:
| Document | Format | Where does it come from? |
|----------|--------|------------------------|
| Fuel Purchase Order | ? | She creates this — what triggers it? |
| Depot Invoice / Billing | ? | From depot/supplier |
| Fuel Receipt / Pickup Slip | ? | From dispatcher / substation |
| Inventory Level Report | ? | From substations (Dohinob, San Pedro, Office) |

### Observe Specifically:

1. **What triggers a fuel PO?**
   - Client orders received by Mich?
   - Inventory level at substations reaching minimum?
   - Depot pricing / special offers?
   - Standing orders / recurring schedule?

2. **What does the PO look like?**
   - What fields? (depot name, product, volume, price, delivery date, terms)
   - Does it go to the depot, to Che (AP), or both?
   - Does the PO contain the price or is that on a separate pricing sheet?

3. **How does she decide how much to order?**
   - Per-client demand?
   - Substation inventory levels?
   - Tanker capacity?
   - Budget / cash availability?

4. **Connection to hauling operations:**
   - Does she coordinate with dispatchers on pickup/delivery scheduling?
   - Does she track which tanker picked up which order?
   - Does she receive delivery confirmation back from drivers/substations?

5. **Invoice matching:**
   - When depot invoice arrives, does she match it to her PO?
   - What happens when depot charges more/less than PO?
   - Does she approve the invoice before it goes to Che?

6. **Connection to Mich's collections:**
   - Does she see Mich's collection data to know what clients have paid?
   - Or does she order based on operations need regardless of collections?
   - How does the timing work? (Order first, then collect from clients?)

7. **Pain points:**
   - Depot price changes between PO and delivery?
   - Fuel availability / shortages?
   - Payment delays from treasury affecting future orders?
   - Volume discrepancies between PO, pickup, and delivery?

### Success Metrics:

| Metric | Current State | Target |
|--------|--------------|--------|
| PO-to-delivery cycle time | ? | Trackable |
| PO accuracy (qty vs actual) | ? | < 2% variance |
| Time from PO creation → Che/AP notification | ? | Same day |
| Number of depot invoice mismatches per month | ? | 0 |

### Documents to Collect:
- Sample Fuel Purchase Order (blank and filled)
- Sample Depot Invoice
- Sample Pickup Slip / Delivery Receipt
- Any inventory level report she uses
- Any pricing sheet / depot rate card

---

## 5. QUIDS (Cash, Bank, Treasury) — Days 7-8

### Documents She Handles:
| Document | Format | Where does it come from? |
|----------|--------|------------------------|
| Bank Statements (12 banks) | ? | |
| Bank Deposit Slips | ? | |
| Check Vouchers | ? | |
| Weekly Cash Flow Report | ? | |
| Bank Reconciliation | ? | |
| PCF Vouchers | ? | |
| Fuel Payment Records | ? | |

### Observe Specifically:

1. **Bank reconciliation — this is the most complex area:**
   - Walk me through reconciling ONE bank account.
   - How many bank accounts do you actively reconcile?
   - How long does it take per bank?
   - What tools do you use? Excel? Manual check-off?
   - What causes differences between book and bank?
   - Show me your bank reconciliation template.

2. **Weekly cash cycle:**
   - Walk me through the COLLECTIBLES sheet from start to finish.
   - Who sends the Distribution Dept data?
   - Who sends the Finance Dept data?
   - How do you compute the gross mark-up?
   - How do you track cash short/excess?
   - What happens when there's a variance?

3. **12 bank accounts:**
   - Please list all bank accounts and what each is used for.
   - Which accounts have maintaining balances/ADB?
   - Which accounts are active vs dormant?
   - How do you know the balance of each bank right now?
   - How often do you check?

4. **Petty Cash Fund:**
   - How many PCFs do you manage?
   - How does replenishment work?
   - Show me the last PCF replenishment request.
   - What kinds of expenses go through PCF?

5. **Fuel payments:**
   - How does fuel payment to depot work?
   - Who initiates the payment?
   - How do you track advances to depot vs actual consumption?

6. **Cash Flow Statement:**
   - Walk me through producing the weekly cash flow.
   - Where does each number come from?
   - How long does it take?
   - Who uses this report?

### Success Metrics:

| Metric | Current State | Target |
|--------|--------------|--------|
| Time to reconcile one bank account | ? | < 15 min |
| Time to produce weekly cash flow | ? | < 30 min |
| Bank reconciliation frequency | ? | Daily |
| Cash cycle settlement time | ? | Same day |
| Number of unreconciled differences | ? | 0 |
| Time to check all 12 bank balances | ? | < 5 min |

### Documents to Collect:
- Bank reconciliation template (Excel)
- Cash flow template (Excel)
- COLLECTIBLES sheet (blank and filled)
- CASH SHORT sheet
- PCF form
- Bank statement sample (1 bank)
- List of all 12 bank accounts with account numbers, maintaining balances

---

## 6. ALYWIN (Tax, Payroll, FA, JEs, BS, Equity, COA) — Days 9-10

### Role: Accounting Head — Tax, Payroll, Fixed Assets, Balance Sheet, Equity, COA maintenance, JE approval

### Documents He Handles:
| Document | Format | Where does it come from? |
|----------|--------|------------------------|
| Journal Vouchers | ? | |
| Payroll Summary | ? | |
| Tax Returns | ? | |
| Fixed Asset Schedule | ? | |
| Depreciation Schedule | ? | |
| Balance Sheet | ? | |
| Trial Balance | ? | |
| COA Changes | ? | |

### Observe Specifically:

1. **Journal Entry approval:**
   - Walk me through approving a JE.
   - What do you check? (Accounts? Amounts? Supporting docs?)
   - How many JEs do you approve per day/week?
   - What causes you to reject a JE?
   - Show me the most common error you catch.

2. **Trial Balance validation:**
   - How do you validate the TB?
   - What do you check first?
   - What happens when it doesn't balance?
   - How do you find the error?
   - Show me last month's TB and walk through your validation steps.

3. **Payroll process:**
   - Walk me through payroll from DTR to JE.
   - Who sends the DTR?
   - How is OT computed?
   - How are government contributions computed?
   - How do you split payroll across DHPP/DMIE/OPS?

4. **Fixed Assets:**
   - Show me your current asset register.
   - How do you track additions?
   - How do you compute depreciation?
   - How do you handle disposals?
   - How do you track assets that are fully depreciated but still in use?

5. **Tax:**
   - Show me how you prepare VAT return.
   - Show me how you prepare income tax.
   - What's estimated vs exact? (They mentioned "bana-bana")
   - Walk me through withholding tax.

6. **COA maintenance:**
   - When was the last time you added an account?
   - Show me the process.
   - Are there accounts no longer used?
   - What dimensions do you wish you had?

7. **Balance Sheet & Equity:**
   - Walk me through producing the BS.
   - How do you handle appropriations? (10% repairs, 10% tithing)
   - Show me the Statement of Changes in Equity.

### Success Metrics:

| Metric | Current State | Target |
|--------|--------------|--------|
| Time to validate TB | ? | < 30 min |
| Time to produce BS | ? | < 15 min |
| JE approval time (per JE) | ? | < 5 min |
| Payroll processing time | ? | < 1 day |
| Depreciation calculation time | ? | Automated |
| Tax filing accuracy | ? | 100% |
| COA change time | ? | < 1 min |

### Documents to Collect:
- Sample Journal Voucher (filled)
- Current Asset Register
- Depreciation Schedule
- Payroll Summary template
- Tax return samples (VAT, WHT, Income Tax)
- COA change log (if exists)

---

## 7. CROSS-FUNCTIONAL OBSERVATION — Day 11

### Document Trace Exercise

Pick **one real document** from today and trace it through all 6 people:

```
Example: Fuel Purchase (Full Chain)
Mam Anne (fuel PO to depot)
    → Dispatcher (pickup dispatch)
    → Driver (delivery to client/substation)
    → Mich (client payment + volume record)
    → Sir Aaron (volume reconciliation + tariff computation)
    → Che (RFP for driver pay + AP entry for depot invoice)
    → Quibs (payment release to depot + driver)
    → Alywin (JE posting, FS impact)
```

### Questions to answer:
- At each handoff, what information is lost or added?
- Who holds the document at each stage?
- How long does each stage take?
- Where are the bottlenecks?

### Trace 3 documents minimum:
1. A fuel sale (client payment → delivery → COGS)
2. An inventory purchase (PR → PO → RR → AP → Payment)
3. A payroll run (DTR → computation → disbursement → JEs)

---

## 8. SUCCESS METRICS SUMMARY

| Domain | Before System | After System (Target) |
|--------|-------------|---------------------|
| AR matching time | ? | < 5 min |
| AP invoice processing | ? | < 10 min |
| Bank reconciliation (per bank) | ? | < 15 min |
| TB validation | ? | < 30 min |
| IS production | ? | < 5 min |
| BS production | ? | < 15 min |
| Cash flow production | ? | < 30 min |
| JE approval | ? | < 5 min |
| Customer lookup | ? | < 10 sec |
| All 12 bank balances check | ? | < 5 min |
| Month-end close duration | ? | < 3 days |
| Error rate (wrong accounts/typos) | ? | 0 |
| Report accuracy | ? | 100% |

**Measure these BEFORE the system for baseline. Measure AGAIN 1 month after go-live.**

---

## 9. KEY QUESTIONS FOR THE OBSERVATION

Rank these by end of observation:

1. **What's the #1 thing to automate first?** (Must be unanimous across team)
2. **What workflow does NOT match what we documented?**
3. **What edge case would break our system?**
4. **Who should be the first power user / tester?**
5. **What data quality issues exist?** (Duplicate customers, wrong accounts, etc.)

---

## 10. DAILY LOG TEMPLATE

```
Day __ — Observing: ___________

Documents seen today:
- ___________________________
- ___________________________

Workflow steps discovered:
1.
2.
3.

Pain points observed:
- 
- 

Surprises / things not in workshop:
- 
- 

Questions for tomorrow:
- 
- 
```
