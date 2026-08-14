ACCOUNTING DOMAIN DISCOVERY WORKSHOP
Building the Seven-Trent Enterprise Accounting Domain
Purpose
This workshop is not intended to gather software requirements or discuss user interface design.
Its purpose is to reverse engineer the Accounting Domain by tracing every financial report back to the business processes that generated it.
The goal is to understand:
Operational Department dhpp, dmie, ops
        ↓
Business Process
        ↓
Business Event
        ↓
Accounting Rules accrual 
        ↓
Journal Entries
        ↓
General Ledger
        ↓
Trial Balance
        ↓
Financial Statements
Once every layer is understood, we will have sufficient information to design the Enterprise Accounting Architecture.
ATTENDEES
Accounting Manager
Senior Accountant
Accounting Staff
Finance Representative
Systems Architect
Process Owner (optional)
WORKSHOP OBJECTIVES
By the end of this discovery workshop, we should understand:
Organization
Accounting organizational structure
Roles and responsibilities
Approval hierarchy
Companies / Business Units / Segments
Accounting Operations
End-to-end accounting workflow
Transaction lifecycle
Source documents
Accounting policies
Posting rules
Month-end closing process
Financial Structure
Chart of Accounts
Financial Statements
Trial Balance
General Ledger relationships
Enterprise Integration
Inventory integration
Procurement integration
Fleet integration
HR & Payroll integration
Maintenance integration
Sales integration
Future Architecture
Accounting Domain Model
Business Events
Integration Architecture
Automation opportunities
PHASE 1 — BUSINESS DISCOVERY
Goal
Understand WHO performs the work.
Questions
Organization
What are the responsibilities of the Accounting Department? Financial status feedback, track/transparency
How many accounting personnel are there? 4
What are each person's responsibilities? Mich - cash/collections, AR. Che - APayable, Inventory, FS, income statement. Quibs - Cashflow, cash in bank, monitoring sa fuel payment nga nagbayad sa bank, expenseses withdrawal, bank recon. Alywin - tax, payroll, fixed asset, balance, equity.
Who handles
Cash
Accounts Receivable
Accounts Payable
Payroll
Inventory
Tax
Financial Statements - 
Fixed Assets
Bank Reconciliation
Company Structure
How is work divided?
Company - stmiet
Business Unit - dhpp, dmie, ops
Branch - n/a
Department - hr, finance, fleet, ops(dis&haul), compliance, technical(truck, dispenser machine), IT
Function
Segments
Our Chart of Accounts contains Segments.
Examples:
DHPP - fuel ado, reg, xcs, distribution and hauling of petroleum products, tanker. Bills, utils
DMIE - machineries fuel dispensers, distribution of machineries and industrial equip
OPS - other products and servs. Compliance, lubs, JO, recalibration bucket.
Questions
What does each Segment represent? 
Can one transaction belong to multiple Segments? Yes, salary
Can Segments change after posting? No
Deliverable
Accounting Organization Map
PHASE 2 — ACCOUNTING PROCESS DISCOVERY
Goal
Understand HOW work moves.
For every transaction ask
Who starts it?
↓ departments, supporting docs, expense, PO, resibo
What document is created?
↓ approval ss, RFP(request for payment)
Who approves it?
↓ finance
Who records it?
↓ APayable - Accounting Clerk / Bookkeeper
Who verifies it?
↓ Accounting Head - alywin
Where does it go next? -> issue check, Treasury quibs(kayamanan), decide if naay budget and release. -> approve head, release of check/encashment. Check clearance bank, liquidate sa check Voucher. Reverse entry AP, from credit to debit. Voucher number, verify if properly liquidated - filing (Clerical part).  Journal ni che - must reflect sa Ledger, Trial balance,income statement, balance sheetJournal ni quibong must reflect sa Ledger, Trial balance, cash flow, balance sheetJournal mich - receive cash, acknowledged payment (AR), recording/ updating of clients account, deposits cash in bank, filing of AR, cash flow and balance sheetCreate FS - > close book.Accounting cycle
Continue asking
"Then what happens?"
until the transaction reaches the Financial Statements.
Daily Workflow
Walk us through today's activities.
From
8:00 AM
Until
5:00 PM
Questions
What arrives first?
Emails?
Purchase Orders?
Receipts?
Sales Invoices?
Fuel Receipts?
Transaction Types
Discuss every transaction processed.
Examples
Sales - order cust, PO, AR, delivered(anne/bong(paid/unpaid) -> sales mich -> alywin - income, cashflow and balance sheet
Purchases - departments, RFP, quib for release - income, cashflow,  balance sheet
Collections - mich/anne, pay thru bank or office - income, cashflow and balance sheet
Supplier Payments - tires, lubs, builtsafe, limdon, junvick - Adrian/inventory, PO, RFP, voucher, alywin , income, cashflow, balance sheet
Fuel Purchases - depot sir clyde, kamada, send to accounting for payment - RFP - alywin - income and balance sheet
Payroll - DTR, computation(OT, deductions, benefits) approval sir Boy, RFP, voucher, upload to PNB, approved by CNR, issue payslip(breakdown) - income, cashflow, balance sheet
Inventory - po, rfp, voucher, inc, cf, bs
Depreciation - inc, bs
Taxes - extract entries, (currently SI, mao ray i-declare), expense is bana-bana.. Income statement
Loans - RFP, voucher, inc, bs, cf
Adjustments - error entry, reversal of entries(cancelled) accrual entries, inc, bs, cf
Journal Entries - general journal, special journals, gi sendan na daw ko. bs
For each transaction ask
What starts it?
What source document is created?
Who prepares it?
Who approves it?
Who records it?
Who verifies it?
Which reports are affected?
Source Documents
Identify every accounting document.
Examples
Purchase Request
Purchase Order
Receiving Report
Sales Invoice
Official Receipt
Delivery Receipt
Journal Voucher
Disbursement Voucher
Payroll Summary
Fuel Receipt
Collection Receipt
Bank Deposit Slip
Inventory Count Sheet
For every document determine
Creator
Approver
Receiver
Storage Location
Paper / Excel / PDF / Email
Can corrections occur? yes
Deliverables
Business Process Maps
Source Document Register
Transaction Lifecycle Maps
PHASE 3 — REVERSE ENGINEER THE FINANCIAL REPORTS
Goal
Understand WHY each number appears on the Financial Statements.
Use the reports already collected:
Income Statement
Statement of Financial Position
Trial Balance
Statement of Cash Flows
Statement of Changes in Equity
Cost of Sales
Total Expenses
For each report ask
Where does this number come from?
Keep tracing backwards.
Example
Fuel Expense
↓
Journal Entry
↓
Fuel Receipt
↓
Fleet Operations
↓
Fuel Purchase
Repeat this exercise for every major account.
Trial Balance
Questions
How is it generated? Ledger journal
How often? Month end
Who validates it? alywin
What happens if it does not balance? Mis-input, review, debit, credit, pivot, extract bs to inc. mis-COA.
Chart of Accounts
Review every COA field.
COA Code
Account Title
Segment
Classification
Category
Major Account
Parent/Sub Account
Questions
Who maintains the COA? alywin
Who creates accounts? alywin
Can account structures change? If have new dep’t
How are Major Accounts mapped to Financial Statements? By category
Future Dimensions
Will accounting eventually need
Vehicles yes, already have
Projects yes
Departments yes, already have
Cost Centers yes
Warehouses yes
Branches yes
Customers yes, already have many customers, i think we need a proper customer ledger for this, as it is very difficult to track customers, but our existing inventory system has a customer list, but it is not complete, how do you propose we solve this)
Suppliers yes already have
Deliverables
COA Analysis
Financial Statement Traceability Matrix
Accounting Traceability Matrix
PHASE 4 — ACCOUNTING RULES & CONTROLS
Goal
Discover the business rules that produce Journal Entries.
Questions
When a transaction occurs
Which accounts are affected? Income accounts
How is the account determined? Manual, sometimes can cause errors and can cause dis balance
Is posting automatic or manual? manual
Are entries recurring? yes
Are adjustments required? some
Can one transaction create multiple Journal Entries? some
Month-End Closing
Walk through the month-end.
Questions
First activity
Final activity
Biggest bottleneck - hauling(sales), PO
Most time-consuming task A/Receivables (PAYMENT & PRICING)
Most common errors- WRONG ACCOUNTS / TYPO , must not have a feature that allows FORCE BALANCE.
Approval Workflow
Who approves
Purchases CNR - Clyde N. Rebollos (COO)
Payments alywin, cnr
Journal Entries alywin
Asset Purchases cnr
Inventory Adjustments cherry, james, alywin
Write-offs - management, bad debts cnr
Manual Adjustments - alywin(journal)
Deliverables
Posting Rules Specification - ihave a new excel file posted (Acctg-Entry-finance-and-acctg.) excel file
Approval Matrix
Month-End Closing Workflow
Accounting Rules Catalog
PHASE 5 — ENTERPRISE INTEGRATION DISCOVERY
Goal
Understand how Accounting integrates with every operational domain.
For each department ask
Inventory
What business events reach Accounting? Inventory value, stock in and outs - (we have separate system for this, i think we will integrate that to this accounting system we will build)
What document begins the process? Request Slip of parts, then Withdrawal Slip, then stock out or stock in have PO, receive i think, i think what we have below in the scenario is the a proper process. Then update the inventory system. 
What reports are affected? Income statement, balance sheet, cash flow
Procurement
Purchase Requests - must have
Purchase Orders - must have
Receiving- must have
Supplier Invoices- must have
Fleet
Fuel Purchases- must have
Vehicle Expenses- must have
GPS / Cartrack- must have
Maintenance- must have
Sales
Sales Orders (PO)
Sales Invoices - ack receipts (internal)
Collections of payments - mich
HR & Payroll
Payroll Summary - inc, bs, cf
Employee Benefits - must have
Government Contributions- must have
Fixed Assets
Asset Acquisition -bs cf
Depreciation - bs , inc
Disposal - bs, inc ,cf
Deliverables
Enterprise Integration Matrix- must have
Business Event Catalog- must have
Integration Architecture- must have
SCENARIO-BASED DISCOVERY - everything here is as what is intended
Instead of discussing theory, walk through real business scenarios.
Scenario 1 – Fuel Purchase
Truck
↓
Fuel Receipt
↓
Approval
↓
Accounting
↓
Journal Entry
↓
General Ledger
↓
Trial Balance
↓
Income Statement
Scenario 2 – Inventory Purchase
Purchase Order
↓
Receiving Report
↓
Inventory
↓
Supplier Invoice
↓
Accounting
↓
Accounts Payable
↓
Payment
Scenario 3 – Customer Collection
Sales Invoice
↓
Collection
↓
Official Receipt
↓
Accounts Receivable
↓
Bank
↓
Financial Statements
Scenario 4 – Payroll
HR
↓
Payroll Summary
↓
Accounting
↓
Payroll Journal
↓
Expenses
Scenario 5 – Fixed Asset Acquisition
Purchase
↓
Receiving
↓
Asset Registration
↓
Depreciation
↓
Financial Statements
TWO-WEEK OBSERVATION PLAN - approved by accounting head
Before implementation, spend two weeks observing daily operations to validate the documented workflows.
Observe:
Daily transaction intake
Source document movement
Journal preparation
Posting process
Reconciliations
Month-end activities
Report generation
Approval flow
Cross-department coordination
The objective is to verify that documented processes match actual day-to-day operations.
FINAL DELIVERABLES
Business Architecture
Accounting Organization Map
Business Process Maps
Roles & Responsibilities
Approval Matrix
Accounting Architecture
Chart of Accounts Analysis
Financial Statement Traceability Matrix
Accounting Rules Catalog
Posting Rules Specification
Fiscal Period & Closing Design
Enterprise Architecture
Source Document Register
Business Event Catalog
Enterprise Integration Matrix
Master Data Model
Software Architecture
Domain Model
Django Models
Module Boundaries
API Contracts
Audit Trail Design
Permission Model
Implementation Roadmap
MVP Scope
Phase 2 Scope
Migration Strategy
Module Development Roadmap
Guiding Principle
Every discussion during this workshop should answer one question:
"How did this number on the Financial Statements get here?"
For every significant value, trace the complete lifecycle:
Financial Statement
        ↑
Trial Balance
        ↑
General Ledger
        ↑
Journal Entry
        ↑
Accounting Rule
        ↑
Business Event
        ↑
Source Document
        ↑
Business Process
        ↑
Operational Department
When every major account can be traced from the financial statements back to the originating business process, the accounting domain has been successfully reverse engineered. At that point, the information gathered is sufficient to design the enterprise accounting architecture with confidence.
“We should be good to go.” and make our ADR, brainstorming and set up.