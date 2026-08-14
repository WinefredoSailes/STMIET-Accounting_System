# ADR-010: Framework Decision — Django for Seven-Trent Accounting Domain

**Status**: Accepted
**Date**: 2026-07-18
**Decision**: Django (Python) as the backend framework for the Seven-Trent Enterprise Accounting Platform.

---

## 1. Context

After reviewing all source files from the accounting team — 392-account COA, 14 transaction category posting rules, 6 financial statements, weekly cash flow tracking across 12 bank accounts, trial balance with monthly Dr/Cr, and complete workshop discovery — we must choose a software framework that can deliver this scope within the team's constraints.

### 1.1 What the Files Revealed — Complete Inventory

| File | Content | Architecture Impact |
|------|---------|-------------------|
| **COA-STMIET-2026.xlsx** | 392 accounts with 10-column metadata (code, title, segment, classification, category, sub-account, major account, behavior, traceability, controllability) | Requires hierarchical multi-dimensional account model with segment as first-class dimension |
| **TRIAL-BALANCE.xlsx** | Monthly Dr/Cr (Jan-Dec) + Opening Balances + YTD, 401 rows | Must generate from GL with period-end snapshots |
| **INCOME-STATEMENT.xlsx** | Segment-level P&L (IPPC/STPC/STMIET for each segment) with appropriation computation (10% repairs, 10% tithing) | Must aggregate by account hierarchy + segment, with custom formulas |
| **STATEMENT-OF-FINANCIAL-POSITION.xlsx** | BS with 13 asset lines, 7 liability lines, 3 equity lines + 5 financial ratios | Classification-driven reporting |
| **STATEMENT-OF-CASH-FLOW.xlsx** | Weekly cycle format across 12 bank accounts with 8 cash flow categories | Needs weekly cash cycle model, not just monthly reporting |
| **COLLECTIBLES sheet** | Two-department reconciliation (Distribution vs Finance), gross mark-up computation | Requires inter-department reconciliation workflow |
| **CASH SHORT sheet** | Variance tracking between collections and deposits | Requires cash short/excess tracking per cycle |
| **CASH END / trial sheets** | 12 bank accounts with ADB/maintaining balances: PNB, PSBC-S, PSBC-C, KB, 1VB, BDO, MBTC, RCBC, CHINA BANK, E.TAN/STPC, PCF & COH | 12-bank-account model with maintaining balance tracking |
| **Acctg-Entry-finance-and-acctg.xlsx** (14 sheets) | Complete posting rules: Machinery, Accruals, Bulilit Station (contractor), Consignment, Fuel, Govt Contributions, Installment Sales, Job Orders, Loans (ORIX + Officers), Inventory, Salaries | 14 distinct transaction workflows, each with multi-step JEs |
| **WORKSHOP DISCOVERY.docx** | 4-person team, approval hierarchy, document flow, pain points | Permission model, approval workflow, document-centric design |
| **COST-OF-SALES.xlsx** | DHPP: 12 cost lines + volume (liters), DMIE: 18 cost lines, OPS: 5 cost lines | Cost allocation by segment with volumetric tracking |
| **TOTAL-EXPENSES.xlsx** | 20 expense categories by segment | Expense classification by category + segment |
| **EQUITY.xlsx** | Beginning Capital → Additions → Net Income → Drawings → Ending Capital | Simple but needs appropriation tracking |

### 1.2 Key Architectural Requirements Derived

1. **Multi-dimensional COA**: Account × Segment × Period — every transaction tagged with segment, account, and period
2. **14 distinct transaction workflows**: Each with different document flows, approval chains, and posting logic
3. **3-segment profit centers**: DHPP, DMIE, OPS — separate P&L per segment
4. **Weekly cash cycle**: 12 bank accounts, 8 cash flow categories, ADB tracking
5. **Hierarchical reporting**: Account → Sub-Account → Major Account → FS Line Item
6. **Approval hierarchy**: Staff → Alywin (Head) → CNR (COO) — per document type and amount
7. **100 business events**: Each may trigger one or more posting rules
8. **Immutable audit trail**: No editing posted JEs, no force balance
9. **Multi-entity future**: Currently one entity, but structure must support expansion
10. **Separate inventory system**: Must integrate via API

---

## 2. Framework Evaluation

### 2.1 Django (Python)

| Criteria | Rating | Evidence |
|----------|--------|----------|
| **Rapid model development** | ★★★★★ | 80+ models needed — Django ORM creates tables, migrations, admin in minutes |
| **Built-in admin** | ★★★★★ | Accounting team needs CRUD for COA, JE, customers, suppliers — Django Admin gives production UI instantly |
| **Permission model** | ★★★★★ | Staff→Alywin→CNR maps to Django's groups + permissions + django-guardian for object-level |
| **Transaction integrity** | ★★★★★ | Atomic transactions for double-entry (debits must equal credits atomically) |
| **Migration support** | ★★★★★ | COA will evolve (new departments, dimensions) — Django migrations handle schema changes |
| **API capability** | ★★★★☆ | DRF provides REST API for inventory system integration |
| **Event-driven** | ★★★☆☆ | Not built-in, but Celery/Redis + Django Signals solves this |
| **Async support** | ★★★☆☆ | HTTP calls are synchronous by default — not critical for this use case |
| **Reporting** | ★★★★☆ | Pandas + openpyxl + Django templates cover all FS outputs |
| **Team availability** | ★★★★★ | Python developers widely available; accounting staff can learn basic reporting |
| **Ecosystem maturity** | ★★★★★ | 20+ years, extensive docs, large community |
| **Security** | ★★★★★ | Mature auth, CSRF, XSS, SQL injection protection built-in |

### 2.2 FastAPI (Python)

| Criteria | Rating | Evidence |
|----------|--------|---------|
| **Rapid model development** | ★★★★☆ | SQLAlchemy + Pydantic good, but no admin UI |
| **Built-in admin** | ★☆☆☆☆ | No admin — every screen must be custom-built |
| **Permission model** | ★★★☆☆ | Must build from scratch |
| **Transaction integrity** | ★★★★☆ | UOW pattern works but more manual |
| **Event-driven** | ★★★★★ | Native async + event bus support |
| **API capability** | ★★★★★ | Excellent — but we only need REST, not streaming/WebSocket |
| **Team availability** | ★★★☆☆ | Smaller talent pool than Django |

**Verdict**: Excellent for pure API services. Not suitable for a data-heavy ERP where 80% of screens are CRUD with complex relationships.

### 2.3 Odoo (Python ERP)

| Criteria | Rating | Evidence |
|----------|--------|---------|
| **Built-in accounting** | ★★★★☆ | Has AR/AP/GL/Inventory modules |
| **Rapid deployment** | ★★★★☆ | Pre-built modules |
| **COA customization** | ★★☆☆☆ | Your COA uses segments as account code suffixes (DHPP=00, DMIE=03, OPS=06) with 10 metadata columns — Odoo's COA structure is rigid |
| **Custom posting rules** | ★★☆☆☆ | Your 14 posting rule categories with specific logic (Bulilit contractor model, consignment, installment with freebies) would require significant customization |
| **Permission model** | ★★★☆☆ | Has roles but hierarchy is less flexible |
| **Reporting** | ★★★☆☆ | Studio reports are limited; complex FS like weekly cash cycle across 12 banks would be custom |

**Verdict**: Would fight the framework more than it helps. Your accounting is specific enough that an off-the-shelf ERP creates more work than building on Django.

### 2.4 .NET / Java (C# / Spring)

| Criteria | Rating | Evidence |
|----------|--------|---------|
| **Enterprise features** | ★★★★★ | Transaction management, security, performance |
| **Development speed** | ★★☆☆☆ | Verbose, compile-heavy, slower iteration |
| **Team availability** | ★★☆☆☆ | Higher cost, harder to find for long-term maintenance |
| **Admin UI** | ★★★☆☆ | Requires commercial tools (DevExpress, Telerik) for admin-quality UIs |

**Verdict**: Overkill. An accounting system for 4 people with 392 accounts doesn't need enterprise-grade infrastructure. The additional complexity doesn't justify the benefits.

### 2.5 Node.js (NestJS / Express)

| Criteria | Rating | Evidence |
|----------|--------|---------|
| **Development speed** | ★★★★☆ | Fast prototyping |
| **Event-driven** | ★★★★★ | Native async, good for event bus |
| **ORM** | ★★★☆☆ | TypeORM/Prisma less mature for complex financial joins |
| **Admin UI** | ★☆☆☆☆ | No built-in admin; must build every screen |
| **Maturity for ERP** | ★★☆☆☆ | Fewer battle-tested patterns for double-entry accounting |

**Verdict**: Strong for event-driven microservices. Weak for data-intensive ERP with complex relational models. Accounting is fundamentally about data integrity, not async throughput.

---

## 3. Decision

**Django** is the framework for this project.

### Why Not Odoo (the closest alternative)

The accounting team's actual posting rules (Acctg-Entry.xlsx) contain transaction types that Odoo cannot handle without heavy customization:

| Transaction Type | Odoo Support | Custom Code Needed |
|----------------|--------------|-------------------|
| Fuel hauling with depot advances + inventory tracking | Partial | Heavy |
| Bulilit contractor model (client pays → contractor share + markup) | None | Complete customization |
| Consignment sales | Partial | Moderate |
| Installment sales with freebies (Gain on Freebies reversal) | None | Complete customization |
| Weekly cash cycle across 12 banks with ADB | None | Complete customization |
| Job orders (prepaid service income) | Partial | Moderate |
| Loan financing (ORIX) with asset integration | Partial | Heavy |
| Multi-segment allocation for shared expenses | None | Heavy |
| 10-column COA with behavior/traceability/controllability | None | Heavy |

Each of these would require Odoo module overrides — and there are 14 transaction types. The cost of fighting Odoo exceeds the cost of building on Django.

### Why Not FastAPI

FastAPI is excellent for APIs. But for an ERP:

1. **80% of screens are CRUD** — Django Admin gives these for free. FastAPI requires building every list view, form, filter, and export from scratch.
2. **Your team needs management screens, not just APIs** — the accounting team manages COA, customers, suppliers, JEs daily. They need 50+ data management screens.
3. **Django Admin is production-ready** — FastAPI + React would take 4-6 months just to match what Django Admin gives you in one command.

---

## 4. How Django Maps to Each File

| File | Django Implementation |
|------|----------------------|
| **COA-STMIET-2026.xlsx** | `Account` model with all 10 columns. Import script reads Excel via openpyxl and creates 392 records. Admin for Alywin to maintain. |
| **TRIAL-BALANCE.xlsx** | `GeneralLedger` model (account × segment × period) with running balances. View queries GL and renders TB format. |
| **INCOME-STATEMENT.xlsx** | Class-based view that queries GL by major_account='REVENUE','COST_OF_SALES','OPERATING_EXPENSE'. Segment filter + appropriation logic in Python. |
| **STATEMENT-OF-FINANCIAL-POSITION.xlsx** | Query GL by major_account='CURRENT_ASSET','NON_CURRENT_ASSET','CURRENT_LIABILITY','NON_CURRENT_LIABILITY','EQUITY'. Ratio calculations. |
| **STATEMENT-OF-CASH-FLOW.xlsx** | `CashFlowStatement` model with weekly cycle support. Queries bank transactions + JE lines. 12-bank-account aggregation. |
| **COLLECTIBLES/CASH SHORT** | `CashReceiptJournal` model with dual-department reconciliation fields. Variance computation. |
| **CASH END / trial;** | `BankAccount` model per bank (12 records). `BankAccountBalance` with ADB/MaintainingBalance per period. |
| **Acctg-Entry-finance-and-acctg.xlsx** | `PostingRule` + `PostingRuleLine` models. Event-driven engine executes rules on business events. |
| **WORKSHOP DISCOVERY.docx** | `User` + `Group` + `ApprovalMatrix` models. Document workflow states. |

---

## 5. Architectural Components That Django Provides Directly

| Need | Django Feature |
|------|---------------|
| 80+ data models with relationships | Django ORM + migrations |
| Admin screens for COA, JE, customers, etc. | Django Admin (customizable) |
| User authentication | `django.contrib.auth` |
| Permissions per role | Groups + Permissions + django-guardian |
| Data validation (debits = credits) | Model validation + form validation |
| API for inventory system | Django REST Framework |
| Background posting tasks | Celery + Redis |
| Report generation | Pandas + openpyxl + Django templates |
| Search and filtering | django-filter |
| Audit trail | django-simple-history or custom |
| Approval workflow | django-workflows or custom state machine |
| File uploads (receipts, docs) | Django FileField + S3 storage |
| Logging and monitoring | Django logging + django-sentry |

---

## 6. Consequences

**Positive**:
- Rapid development — foundation phase (COA, JE, GL, TB) achievable in 8-10 weeks
- Low maintenance — Python is readable, migrations are automatic, admin is built-in
- Easy to extend — new modules (projects, cost centers, warehouses) are just new apps
- Integrates cleanly — inventory system integration via DRF APIs
- Team-friendly — Python developers are available and affordable

**Negative**:
- Django Admin isn't beautiful — but it's functional. Can be enhanced with django-grappelli or custom frontend later
- Not naturally event-driven — solved by Celery/Redis (standard Django pattern)
- Async limitations — not relevant for this workload (4-person accounting team, not millions of transactions)

**Neutral**:
- Must use DRF for API (one more library, but standard in Django ecosystem)
- Must choose Celery over native async (mature, well-tested pattern)

---

## 7. Confirmation of Tech Stack

| Layer | Technology | Justification |
|-------|-----------|---------------|
| Backend | Django 5.x | Primary framework |
| API | Django REST Framework | Inventory system integration |
| Database | PostgreSQL | Relational integrity, JSONB for flexible attributes, full-text search |
| Cache/Queue | Redis + Celery | Event posting, background reports |
| Admin Enhancement | django-grappelli or jazzmin | Better UI for accounting team |
| ORM Enhancement | django-debug-toolbar | Query optimization for TB/FS reports |
| API Docs | drf-spectacular (OpenAPI) | Integration documentation |
| Testing | pytest + pytest-django | Test posting rules, TB generation |
| File Storage | Local dev / S3 production | Receipts, OR images, supporting docs |
| Version Control | Git | Standard |
| CI/CD | GitHub Actions | Automated testing on push |
| Container | Docker (dev) / Docker Compose (prod) | Reproducible environments |
