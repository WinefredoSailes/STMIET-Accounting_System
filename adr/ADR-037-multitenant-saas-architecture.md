# ADR-037: Multitenant SaaS Architecture

**Status:** Accepted
**Date:** 2026-09-04
**Deciders:** Architecture Team

**References:**
- [ADR-003: Segment as First-Class Dimension](../adr/ADR-003-segment-first-class.md) — segments (DHPP, DMIE, OPS) are the current intra-org tenants
- [ADR-011: Multi-Segment Data Architecture](../adr/ADR-011-multi-segment-architecture.md) — tenant-aware data model already adopted
- [ADR-010: Framework Decision](../adr/ADR-010-framework-decision.md) — Django + PostgreSQL stack
- [docs/04-multi-tenant-architecture.md](../docs/04-multi-tenant-architecture.md) — current segment-level tenant documentation

---

## Context

The system is currently built for a single organization (STMIET) with internal **segments** (DHPP, DMIE, OPS, STPC) that behave like soft tenants. The ADR-011 decision already uses the phrase "tenant-aware data model."

Two new requirements change the scope:

1. **Sister company adoption** — Another entity (or entities) wants to use the same system for their own accounting. Each company has its own COA, fiscal year, currency, users, and business rules.
2. **Future SaaS potential** — The owner may offer this system as a subscription product. This is not the immediate priority but must not be architecturally blocked.

During the development stage, the data model, API boundaries, and configuration patterns must be designed so that adding a second organization later does not require a rewrite.

---

## Decision

**Adopt a shared-database, soft multi-tenant architecture where a `Tenant` entity scopes all accounting data.**

### Core Principle

Every record in the system — every GL account, journal entry, customer, product, bank account, approval rule — is scoped to a `Tenant`. The current STMIET organization becomes `Tenant` ID 1. A second company becomes `Tenant` ID 2, and so on.

### What This Means Now (Development Stage)

| Area | Action |
|------|--------|
| **Data model** | Add `tenant` foreign key to all models that hold accounting data. Use Django's `Tenant` model with a thread-local or context-variable pattern to set the active tenant per request. |
| **Admin / UI** | All list views, forms, and reports filter by the active tenant. Operators never see another tenant's data. |
| **Auth** | Users belong to one or more tenants. Login selects the active tenant. A super-admin role exists for cross-tenant management. |
| **COA, Products, Customers** | These are tenant-scoped. A product code `111` in Tenant 1 (DHPP fuel) and a product code `111` in Tenant 2 (different product) are independent. |
| **Segments** | Segments remain a **sub-tenant** dimension within each tenant. Tenant 1 has DHPP/DMIE/OPS. Tenant 2 may have completely different segments or none at all. |
| **Intercompany** | Intercompany (e.g., STPC) is a tenant-local concept. Cross-tenant intercompany is out of scope for now. |
| **Fiscal year, currency, tax rules** | These become tenant-level configuration, not global constants. |

### What This Defers (Not Now)

| Area | Deferred |
|------|----------|
| **Schema-per-tenant or DB-per-tenant** | Not needed at this scale. Shared DB with row-level tenant isolation is sufficient. Revisit if a tenant requires regulatory data isolation. |
| **Tenant provisioning API** | Creating a new tenant is a manual admin operation for now. Automated self-service provisioning is a SaaS-stage concern. |
| **Per-tenant deployment** | All tenants run on the same Django instance. No separate deployments. |
| **Cross-tenant reporting** | No consolidated reporting across tenants. Each tenant is fully independent. |
| **Billing / subscription** | Not in scope. Tenant model must not preclude adding billing later. |

---

## Tenant Isolation Strategy

### Row-Level Isolation (Current Choice)

Every table with accounting data has a `tenant_id` column. A custom middleware sets the active tenant for each request. All queries automatically filter by tenant.

```
Request → Middleware sets Tenant context → ORM filters all queries → Response
```

This is the standard Django multi-tenant pattern (django-tenants, django-tenants-plus, or custom middleware with `CurrentTenantMiddleware`).

### Why Not Schema-Per-Tenant (django-tenants with PostgreSQL schemas)

- **Premature** — We have 1-2 tenants, not 100. Schema isolation adds operational complexity (migrations run per-schema, connection routing, schema creation on provisioning).
- **Django ecosystem friction** — Many third-party apps don't support `django-tenants` out of the box. Custom middleware is simpler and works with all apps.
- **Reversible** — If a tenant later requires regulatory isolation (e.g., a bank), we can migrate that tenant to a separate schema or database without affecting others.

### Why Not Database-Per-Tenant

- **Overkill** — A small accounting system for 4-person teams does not need separate database servers per tenant.
- **Deployment complexity** — Each tenant requires its own Postgres instance, migrations, backups. Not justified at this scale.

---

## Data Model Impact

### New Model: `Tenant`

```python
class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name = models.CharField(max_length=200)           # "STMIET Group"
    slug = models.SlugField(unique=True)               # "stmiet"
    fiscal_year_start = models.DateField()             # Per-tenant fiscal year
    currency = models.CharField(max_length=3, default="PHP")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

### Modified Models (All Accounting Entities)

Every model that currently has no tenant concept gains a `tenant` field:

```python
class Account(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=200)
    # ... existing fields

    class Meta:
        unique_together = [("tenant", "code")]
```

This applies to: `Account`, `JournalEntry`, `JournalEntryLine`, `Customer`, `Supplier`, `Product`, `BankAccount`, `AR`, `AP`, `ApprovalMatrix`, `PostingRule`, and all other domain models.

### Segment Stays Sub-Tenant

```python
class Segment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    code = models.CharField(max_length=10)              # "DHPP", "DMIE"
    name = models.CharField(max_length=200)
    default_unearned_revenue_gl = models.ForeignKey(Account, ...)

    class Meta:
        unique_together = [("tenant", "code")]
```

A tenant may have 0 segments (single-segment company), 3 segments (current STMIET), or many more.

---

## Middleware Pattern

```python
class TenantMiddleware:
    """Sets the active tenant for each request based on the authenticated user."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # User's default tenant or selected tenant from session
            tenant_id = request.session.get("tenant_id")
            request.tenant = Tenant.objects.get(id=tenant_id, is_active=True)
        else:
            request.tenant = None

        response = self.get_response(request)
        return response
```

A `set_current_tenant()` helper (or thread-local) makes the tenant available in models, services, and management commands without passing it explicitly.

---

## Consequences

**Positive:**
- A second tenant (sister company) can be onboarded by creating a `Tenant` record, importing their COA, and inviting their users — no code changes required.
- The existing segment architecture (ADR-003, ADR-011) is preserved. Segments are per-tenant, not global.
- Row-level isolation is simple to implement, test, and audit.
- The system remains a single deployment, single database — low operational cost.
- Future SaaS billing (per-tenant subscription) can be added to the `Tenant` model without schema changes.

**Negative:**
- Every query must include a tenant filter. Forgetting to filter is a data leak bug. Mitigated by a custom manager (`TenantManager`) that auto-filters by tenant.
- Migrations must add `tenant_id` to all existing tables. This is a one-time migration effort.
- A malicious user who bypasses middleware could see another tenant's data. Mitigated by database-level row security (PostgreSQL RLS) as a second layer.

**Trade-offs Accepted:**
- Shared database means all tenants share connection pool and storage. Acceptable for small-scale accounting systems.
- No tenant-level resource limits (CPU, storage) for now. If SaaS is pursued, add quotas at the application layer.

---

## Options Considered

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Shared DB, row-level tenant (selected)** | Simple, single deployment, works with all Django apps, reversible | Must filter every query, shared resources | **Selected** |
| **Schema-per-tenant** (django-tenants) | Stronger isolation, per-tenant schema migrations | Complex setup, many Django apps don't support it, overkill for 1-2 tenants | Deferred to SaaS stage |
| **DB-per-tenant** | Strongest isolation, independent backups | Deployment complexity, expensive, migration overhead | Rejected for now |
| **No tenant model, just deploy separate instances** | Zero code changes now | Cannot share codebase updates, cannot offer SaaS, duplicate ops | Rejected — defeats the purpose |

---

## Implementation Checklist

During the current development phases, the following should be done as part of normal feature work:

- [ ] Create `Tenant` model and initial migration
- [ ] Add `tenant` FK to all accounting models (can be done incrementally per module)
- [ ] Implement `TenantMiddleware` and `set_current_tenant()` helper
- [ ] Add tenant-scoped unique constraints (e.g., `unique_together = [("tenant", "code")]` on Account)
- [ ] Update Django Admin to filter by tenant
- [ ] Update all service-layer queries to respect tenant context
- [ ] Add tenant selection screen after login (if user has access to multiple tenants)
- [ ] Seed Tenant 1 (STMIET) with existing data
- [ ] Add PostgreSQL Row-Level Security policy as a defense-in-depth layer (optional, recommended before SaaS)

**Do not block current development on this.** Add tenant fields incrementally as each module is built. The first migration that adds `tenant_id` to core models should be created soon, but the rest can follow the module development cadence.
