"""Screen registry — the single source of truth for who sees what (ADR-047).

A *screen* is a UI module (its list page plus every sub-route: detail, create,
edit, export, print). ``approval_role`` stays what it always was — signature
authority (ADR-008/020) — while this registry answers the different question
"what is on this person's desk". A user's grants come from
``UserProfile.screen_access`` (explicit list) or, when null, from their role
template, so enabling this feature changes nothing until someone edits a user.

The same keys drive: the sidebar filter, the user-management checkbox grid,
the login landing decision, and the enforcement middleware (UI + API).
"""

from __future__ import annotations

# (key, label, sidebar section). key = the module's primary UI URL name.
SCREENS: list[tuple[str, str, str | None]] = [
    ("dashboard", "Executive Dashboard", None),
    ("my_approvals", "My Approvals", None),
    ("je_list", "Journal Entries", "Journal"),
    ("general_journal", "General Journal", "Journal"),
    ("fleet_fuel", "Fleet Fuel Report", "Fleet"),
    ("coa_list", "Chart of Accounts", "Foundation"),
    ("customer_list", "Customers", "Receivables (AR)"),
    ("si_list", "Sales Invoices", "Receivables (AR)"),
    ("receipt_list", "Acknowledgment Receipts", "Receivables (AR)"),
    ("ar_aging", "AR Aging / Register", "Receivables (AR)"),
    ("ar_ledger", "AR Subsidiary Ledger", "Receivables (AR)"),
    ("supplier_list", "Suppliers", "Payables (AP)"),
    ("po_list", "Purchase Orders", "Payables (AP)"),
    ("rfp_list", "RFPs (Disbursements)", "Payables (AP)"),
    ("conso_list", "CONSO Batches", "Payables (AP)"),
    ("cv_list", "Check Vouchers", "Payables (AP)"),
    ("ap_aging", "AP Aging / Register", "Payables (AP)"),
    ("ap_ledger", "AP Subsidiary Ledger", "Payables (AP)"),
    ("advances", "Advances to Employees", "Payables (AP)"),
    ("billing_list", "Billing Transactions", "Billing"),
    ("bank_list", "Bank Accounts", "Cash"),
    ("cycle_list", "Weekly Cycles", "Cash"),
    ("recon_list", "Bank Reconciliation", "Cash"),
    ("cash_short_list", "Cash Short", "Cash"),
    ("collections_summary", "Daily Collections Summary", "Cash"),
    ("collectibles", "Collectibles Worksheet", "Cash"),
    ("transfers", "Inter-Account Transfers", "Cash"),
    ("pcf_list", "Petty Cash Funds", "Cash"),
    ("pcf_replenishment_list", "Petty Cash Vouchers", "Cash"),
    ("asset_list", "Assets", "Fixed Assets"),
    ("tax_dashboard", "Tax Dashboard", "Tax & Compliance"),
    ("tax_vat", "VAT (SI level)", "Tax & Compliance"),
    ("tax_wht", "WHT Certificates", "Tax & Compliance"),
    ("tax_provision", "Income Tax Provision", "Tax & Compliance"),
    ("tax_calendar", "Tax Calendar", "Tax & Compliance"),
    ("trial_balance", "Trial Balance", "Reports"),
    ("ledger_index", "Ledger", "Reports"),
    ("cash_flow", "Cash Flow Statement", "Reports"),
    ("statement", "Financial Statements", "Reports"),
    ("month_end_close", "Month-End Close", "Reports"),
    ("user_management", "User Management", "Settings / Admin"),
]

SCREEN_KEYS: frozenset[str] = frozenset(k for k, _, _ in SCREENS)
SCREEN_LABELS: dict[str, str] = {k: label for k, label, _ in SCREENS}
SCREEN_SECTIONS: dict[str, str | None] = {k: sec for k, _, sec in SCREENS}

#: Everything except the Settings module — the default for staff and unassigned.
WORK_KEYS: frozenset[str] = SCREEN_KEYS - {"user_management"}

#: UI routes that are infrastructure, not screens.
PUBLIC_UI_URLS = frozenset({"login", "logout"})

#: Shared pickers/options every module's forms use — gated as "any authed user"
#: on purpose: a supplier picker is not a screen.
SHARED_UI_URL_NAMES = frozenset({
    "profile",  # ADR-048: everyone's own My Profile
    "account_options",
    "supplier_options",
    "party_options",
    "po_options",
    "billing_rfp_options",
    "ar_invoice_options",
    # Typeahead pickers used by OTHER modules' forms: a CV preparer needs the
    # RFP picker without owning the RFP register, a cashier needs the customer
    # picker without owning Customers (prod 403, Sep-2026: "rfp_"/"customer_"
    # prefixes silently gated these - keep every *_options endpoint shared;
    # test_picker_endpoints_are_shared enforces it).
    "rfp_options",
    "customer_options",
})

#: Approve-side actions belong to the My Approvals screen, so an approver who
#: is locked out of a register can still sign what waits on them *from the
#: inbox* (ADR-047: the COO's clean-lockdown default). Wrong-role calls are
#: still refused by the service-layer approval guards (ADR-020).
APPROVAL_ACTIONS = frozenset({
    "je_approve", "je_reject",
    "je_reversal_approve", "je_reversal_reject",
    "receipt_approve", "receipt_reject",
    "si_approve", "si_reject",
    "rfp_approve", "rfp_approve_cnr", "rfp_reject",
    "po_approve", "po_approve_cnr", "po_reject",
    "cv_approve", "cv_clear", "cv_reject",
    "billing_approve", "billing_reject",
    "cash_short_approve",
    "transfer_approve", "transfer_reject",
    "pcf_replenishment_approve",
})

#: Exact UI url-name -> screen overrides (checked before prefixes).
_EXACT = {
    "aging_export": "ar_aging",
    "ar_receipts_export": "receipt_list",
    "ar_ledger_export": "ar_ledger",
    "ap_ledger_export": "ap_ledger",
    "ap_aging_export": "ap_aging",
    "ar_aging_export": "ar_aging",
    "banks_export": "bank_list",
    "cycles_export": "cycle_list",
    "month_end_close_export": "month_end_close",
    "advances_export": "advances",
    "assets_list_export": "asset_list",
    "conso_list_export": "conso_list",
}

#: UI url-name prefixes -> screen. Longest prefix wins.
_PREFIXES: list[tuple[str, str]] = sorted(
    [
        ("je_", "je_list"),
        ("general_journal", "general_journal"),
        ("fleet_fuel", "fleet_fuel"),
        ("coa_", "coa_list"),
        ("customer_", "customer_list"),
        ("si_", "si_list"),
        ("receipt_", "receipt_list"),
        ("ar_aging", "ar_aging"),
        ("ar_receipt", "receipt_list"),
        ("ar_ledger", "ar_ledger"),
        ("ar_customer_ledger", "ar_ledger"),
        ("supplier_", "supplier_list"),
        ("po_", "po_list"),
        ("rfp_", "rfp_list"),
        ("conso_", "conso_list"),
        ("cv_", "cv_list"),
        ("ap_aging", "ap_aging"),
        ("ap_ledger", "ap_ledger"),
        ("ap_supplier_ledger", "ap_ledger"),
        ("advance", "advances"),
        ("billing_", "billing_list"),
        ("bank_", "bank_list"),
        ("cycle", "cycle_list"),
        ("recon_", "recon_list"),
        ("cash_short_", "cash_short_list"),
        ("collections_", "collections_summary"),
        ("collectibles", "collectibles"),
        ("transfer", "transfers"),
        ("ftv_", "transfers"),
        ("pcf_replenish", "pcf_replenishment_list"),
        ("pcf_", "pcf_list"),
        ("asset", "asset_list"),
        ("tax_dashboard", "tax_dashboard"),
        ("tax_vat", "tax_vat"),
        ("tax_wht", "tax_wht"),
        ("tax_provision", "tax_provision"),
        ("tax_calendar", "tax_calendar"),
        ("trial_balance", "trial_balance"),
        ("ledger_", "ledger_index"),
        ("cash_flow", "cash_flow"),
        ("statement", "statement"),
        ("month_end_", "month_end_close"),
        ("user_", "user_management"),
    ],
    key=lambda kv: len(kv[0]),
    reverse=True,
)


def screen_for_url_name(name: str) -> str | None:
    """The screen gating a UI url name; None = not gated (public/shared)."""
    if name in PUBLIC_UI_URLS or name in SHARED_UI_URL_NAMES:
        return None
    if name in APPROVAL_ACTIONS:
        return "my_approvals"
    if name in SCREEN_KEYS:
        return name
    if name in _EXACT:
        return _EXACT[name]
    for prefix, screen in _PREFIXES:
        if name.startswith(prefix):
            return screen
    return None


# ---------------------------------------------------------------------------
# API (/api/v1/<section>/<resource>/...) — mapped to the same screen keys so
# UI and API can never disagree. Unmapped machine-integration endpoints are
# deliberately shared (any authenticated caller): payroll/inventory feeds are
# system-to-system, and token/schema/docs are public infrastructure.
# ---------------------------------------------------------------------------

API_RESOURCE_SCREENS: dict[str, str] = {
    "suppliers": "supplier_list",
    "rfps": "rfp_list",
    "conso-batches": "conso_list",
    "check-vouchers": "cv_list",
    "disbursements": "cv_list",
    "advances": "advances",
    "purchase-orders": "po_list",
    "customers": "customer_list",
    "price-snapshots": "customer_list",
    "invoices": "si_list",
    "receipts": "receipt_list",
    "deposits": "receipt_list",
    "asset-categories": "asset_list",
    "assets": "asset_list",
    "depreciation-schedule": "asset_list",
    "disposals": "asset_list",
    "billings": "billing_list",
    "bank-accounts": "bank_list",
    "cycles": "cycle_list",
    "reconciliations": "recon_list",
    "pcf-funds": "pcf_list",
    "pcf-replenishments": "pcf_replenishment_list",
    "transfers": "transfers",
    "cash-flow": "cash_flow",
    "collectibles": "collectibles",
    "cash-short": "cash_short_list",
    "entries": "je_list",
    "trial-balance": "trial_balance",
    "templates": "statement",
    "statements": "statement",
    "month-end-close": "month_end_close",
    "requests": "my_approvals",
}

#: reference data + machine feeds: authenticated callers, no screen needed.
API_SHARED_RESOURCES = frozenset({
    "companies", "segments", "fiscal-years", "fiscal-periods", "accounts",
    "rules", "feeds", "events",
})

API_PUBLIC_SECTIONS = frozenset({"auth"})  # token endpoints under /api/v1/auth/


def screen_for_api_path(path: str) -> str | None:
    """Map /api/v1/<section>/<resource>/... to its screen key (None = not gated).

    ``/api/schema``, ``/api/docs`` and ``/api/v1/auth/*`` are infrastructure;
    machine feeds (payroll/inventory) and master reference data are shared.
    Unknown resources are not gated (fail-open on the API surface is safe —
    their screens remain gated at the UI; the completeness test in
    test_screens_registry pins that every *registered* resource maps).
    """
    parts = [p for p in path.split("/") if p]
    if not parts or parts[0] != "api":
        return None
    if len(parts) >= 2 and parts[1] in ("schema", "docs"):
        return None
    if len(parts) >= 3 and parts[1] == "v1":
        if parts[2] in API_PUBLIC_SECTIONS:
            return None
        resource = parts[3] if len(parts) > 3 else ""
        if resource in API_SHARED_RESOURCES:
            return None
        return API_RESOURCE_SCREENS.get(resource)
    return None


# ---------------------------------------------------------------------------
# Role templates + effective grants
# ---------------------------------------------------------------------------

def role_template(approval_role: str) -> frozenset[str]:
    """The default screen set for an approval role (superuser handled apart)."""
    if approval_role == "head":
        return SCREEN_KEYS
    if approval_role == "coo":
        return frozenset({"dashboard", "my_approvals"})
    return WORK_KEYS  # staff + unassigned keep the full work set


def effective_screens(user) -> frozenset[str]:
    """Screens the user may use: explicit grants, else the role template.

    Dashboard is always included — it is the landing and read-only overview;
    locking it out would dead-end any personalized home.
    """
    if user.is_superuser:
        return SCREEN_KEYS
    profile = getattr(user, "profile", None)
    grants = getattr(profile, "screen_access", None) if profile else None
    if grants is None:
        return role_template(getattr(profile, "approval_role", "") or "") | {"dashboard"}
    return frozenset(set(grants) | {"dashboard"}) & SCREEN_KEYS


def home_url_for(user) -> str:
    """Where a user lands after login (role home, kept inside their grants).

    Management (superuser/head/coo) and unassigned users open on the
    Executive Dashboard; staff open on their desk (the journal), falling
    back to the approvals inbox, then the dashboard, if narrowed.
    """
    from django.urls import reverse

    allowed = effective_screens(user)
    role = getattr(getattr(user, "profile", None), "approval_role", "") or ""
    if user.is_superuser or role in ("head", "coo") or role not in ("staff",):
        return "/"  # management/unassigned: bird's-eye (always in allowed)
    for key in ("je_list", "my_approvals"):
        if key in allowed:
            return reverse(f"ui:{key}")
    return "/"


def can_edit_grants_for(actor, target) -> bool:
    """Who may change whose screen grants (ADR-047):

    - superuser: anyone;
    - head: other users that are not superusers, not heads (no peer edits),
      and not themselves (no self-service expansion).
    """
    if actor.is_superuser:
        return True
    from apps.core.approvals import get_approval_role

    if get_approval_role(actor) != "head":
        return False
    if target.pk == actor.pk or target.is_superuser:
        return False
    return get_approval_role(target) != "head"
