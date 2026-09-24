"""Per-screen filter specs.

One declarative :class:`~apps.ui.filtering.FilterSpec` per list screen. The
shared engine in :mod:`apps.ui.filtering` does the applying and the
``ui/partials/filter_bar.html`` partial does the rendering, so every list
behaves the same way: same query-string params, same HTMX swap, same Clear.
"""

from __future__ import annotations

from .filtering import (
    FilterField,
    FilterSpec,
    Option,
    account_choices,
    asset_category_choices,
    bank_choices,
    customer_choices,
    segment_choices,
    segment_pk_choices,
    supplier_choices,
)

__all__ = [
    "FilterField",
    "FilterSpec",
    "Option",
    "coa_filter_spec",
    "customer_list_filter_spec",
    "receipt_list_filter_spec",
    "supplier_list_filter_spec",
    "rfp_filter_spec",
    "po_filter_spec",
    "cv_filter_spec",
    "je_filter_spec",
    "transfer_filter_spec",
    "asset_filter_spec",
    "si_filter_spec",
    "billing_filter_spec",
    "conso_filter_spec",
    "bank_filter_spec",
    "cycle_filter_spec",
    "pcf_fund_filter_spec",
    "pcf_replenishment_filter_spec",
    "recon_filter_spec",
    "cash_short_filter_spec",
]


# --- Foundation ------------------------------------------------------------


def coa_filter_spec():
    from apps.foundation.models import AccountType

    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="Code or name",
                search_fields=("code", "name"),
            ),
            FilterField("segment", "Segment", kind="choice", choices=segment_choices),
            FilterField(
                "account_type", "Type", kind="choice",
                choices=lambda req: AccountType.choices,
            ),
        ]
    )


# --- AR --------------------------------------------------------------------


def customer_list_filter_spec():
    from apps.ar.models import CustomerGroup, PricingTier

    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="Code or name",
                search_fields=("code", "name", "owner_name"),
            ),
            FilterField(
                "group", "Group", kind="choice",
                choices=lambda req: CustomerGroup.choices,
            ),
            FilterField(
                "pricing_tier", "Pricing Tier", kind="choice",
                choices=lambda req: PricingTier.choices,
            ),
        ]
    )


def receipt_list_filter_spec():
    from apps.ar.models import ReceiptStatus

    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="Receipt no / customer",
                search_fields=("receipt_no", "customer__name", "check_no", "transaction_no"),
            ),
            FilterField(
                "status", "Status", kind="choice",
                choices=lambda req: ReceiptStatus.choices,
            ),
            FilterField("segment", "Segment", kind="choice", choices=segment_pk_choices),
            FilterField("customer", "Customer", kind="choice", choices=customer_choices),
        ]
    )


# --- AP --------------------------------------------------------------------


def supplier_list_filter_spec():
    from apps.ap.models import SupplierType

    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="Code, name or TIN",
                search_fields=("code", "name", "tin", "owner_name"),
            ),
            FilterField(
                "supplier_type", "Type", kind="choice",
                choices=lambda req: SupplierType.choices,
            ),
            FilterField("default_segment", "Segment", kind="choice", choices=segment_pk_choices),
        ]
    )


# RFP statuses follow the ADR-018/020 chain.
RFP_STATUS_CHOICES = [
    ("draft", "Draft"),
    ("submitted", "Submitted"),
    ("checked", "Checked"),
    ("acctg_approved", "Approved (Acctg)"),
    ("fin_approved", "Approved (Fin)"),
    ("cnr_approved", "Approved (CNR)"),
    ("posted", "Posted"),
    ("rejected", "Rejected"),
]

PO_STATUS_CHOICES = [
    ("prepared", "Prepared"),
    ("submitted", "Submitted"),
    ("checked", "Checked"),
    ("acctg_approved", "Approved (Acctg)"),
    ("fin_approved", "Approved (Fin)"),
    ("cnr_approved", "Approved (CNR)"),
    ("approved", "Approved"),
    ("closed", "Closed"),
    ("rejected", "Rejected"),
]

CV_STATUS_CHOICES = [
    ("created", "Created"),
    ("approved", "Approved"),
    ("cleared", "Cleared"),
    ("rejected", "Rejected"),
    ("void", "Void"),
]


def rfp_filter_spec():
    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="AP no, payee or particulars",
                search_fields=("ap_number", "payee__name", "particulars"),
            ),
            FilterField(
                "status", "Status", kind="choice",
                choices=lambda req: RFP_STATUS_CHOICES,
            ),
            FilterField("payee", "Payee", kind="choice", choices=supplier_choices),
            FilterField("segment", "Segment", kind="choice", choices=segment_pk_choices),
        ]
    )


def po_filter_spec():
    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="PO no, vendor or particulars",
                search_fields=("po_number", "supplier__name", "particulars"),
            ),
            FilterField(
                "status", "Status", kind="choice",
                choices=lambda req: PO_STATUS_CHOICES,
            ),
            FilterField("supplier", "Vendor", kind="choice", choices=supplier_choices),
            FilterField("segment", "Segment", kind="choice", choices=segment_pk_choices),
        ]
    )


def cv_filter_spec():
    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="CV no, payee or check no",
                search_fields=("cv_number", "payee__name", "check_no"),
            ),
            FilterField(
                "status", "Status", kind="choice",
                choices=lambda req: CV_STATUS_CHOICES,
            ),
            FilterField("payee", "Payee", kind="choice", choices=supplier_choices),
            FilterField("bank_account", "Bank Account", kind="choice", choices=account_choices),
        ]
    )


# --- Posting ---------------------------------------------------------------


def je_filter_spec():
    from apps.posting.models import PostingStatus

    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="Entry no or description",
                search_fields=("entry_no", "description", "source_doc_no"),
            ),
            FilterField(
                "status", "Status", kind="choice",
                choices=lambda req: PostingStatus.choices,
            ),
            FilterField("segment", "Segment", kind="choice", choices=segment_pk_choices),
        ]
    )


# --- Cash ------------------------------------------------------------------

TRANSFER_STATUS_CHOICES = [
    ("requested", "Requested"),
    ("submitted", "Submitted"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
]


def transfer_filter_spec():
    """Inter-account transfer register filters (ADR-030)."""
    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text",
                placeholder="Voucher, bank, purpose or reference",
                search_fields=(
                    "voucher_no",
                    "from_account__code",
                    "from_account__bank_name",
                    "to_account__code",
                    "to_account__bank_name",
                    "purpose",
                    "reference",
                    "check_no",
                ),
            ),
            FilterField(
                "status", "Status", kind="choice",
                choices=lambda req: TRANSFER_STATUS_CHOICES,
            ),
            FilterField("from_account", "From (Credit)", kind="choice", choices=bank_choices),
            FilterField("to_account", "To (Debit)", kind="choice", choices=bank_choices),
        ]
    )


# --- Fixed Assets -----------------------------------------------------------

ASSET_STATUS_CHOICES = [
    ("active", "Active"),
    ("fully_depreciated", "Fully Depreciated (still in use)"),
    ("disposed", "Disposed"),
]


def asset_filter_spec():
    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="Name or FA number",
                search_fields=("name", "asset_no"),
            ),
            FilterField("category", "Category", kind="choice", choices=asset_category_choices),
            FilterField("segment", "Segment", kind="choice", choices=segment_pk_choices),
            FilterField(
                "status", "Status", kind="choice",
                choices=lambda req: ASSET_STATUS_CHOICES,
            ),
        ]
    )


# --- AR Sales Invoices ------------------------------------------------------

SI_STATUS_CHOICES = [
    ("draft", "Draft"),
    ("submitted", "Submitted"),
    ("posted", "Posted"),
    ("open", "Open"),
    ("partially_paid", "Partially Paid"),
    ("paid", "Paid"),
]


def si_filter_spec():
    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="Invoice no, customer or PO",
                search_fields=("invoice_no", "customer__name", "customer__code"),
            ),
            FilterField(
                "status", "Status", kind="choice",
                choices=lambda req: SI_STATUS_CHOICES,
            ),
            FilterField("customer", "Customer", kind="choice", choices=customer_choices),
            FilterField("segment", "Segment", kind="choice", choices=segment_pk_choices),
        ]
    )


# --- Billing ----------------------------------------------------------------

BILLING_STATUS_CHOICES = [
    ("draft", "Draft"),
    ("submitted", "Submitted for approval"),
    ("approved", "Approved (ready to post)"),
    ("posted", "Posted to GL"),
]


def billing_filter_spec():
    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="Billing no, party or reference",
                search_fields=("billing_no", "party_name", "reference"),
            ),
            FilterField(
                "billing_type", "Type", kind="choice",
                choices=lambda req: [
                    ("stpc", "Intercompany Billing - STPC"),
                    ("third_party", "Third-Party Billing"),
                ],
            ),
            FilterField(
                "status", "Status", kind="choice",
                choices=lambda req: BILLING_STATUS_CHOICES,
            ),
            FilterField("segment", "Segment", kind="choice", choices=segment_pk_choices),
        ]
    )


# --- CONSO Batches ----------------------------------------------------------

CONSO_STATUS_CHOICES = [
    ("open", "Open"),
    ("reviewed", "Reviewed"),
    ("posted", "Posted"),
    ("rejected", "Rejected"),
]


def conso_filter_spec():
    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="Batch no",
                search_fields=("batch_no",),
            ),
            FilterField(
                "status", "Status", kind="choice",
                choices=lambda req: CONSO_STATUS_CHOICES,
            ),
        ]
    )


# --- Banks ------------------------------------------------------------------

def bank_filter_spec():
    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="Code, name, bank",
                search_fields=("code", "name", "bank_name"),
            ),
            FilterField(
                "account_type", "Type", kind="choice",
                choices=lambda req: [
                    ("savings", "Savings"),
                    ("checking", "Checking"),
                    ("pcf_coh", "Petty Cash & Cash on Hand"),
                ],
            ),
            FilterField("is_active", "Active", kind="bool"),
        ]
    )


# --- Cash Cycles ------------------------------------------------------------

CYCLE_STATUS_CHOICES = [
    ("open", "Open"),
    ("reconciled", "Reconciled"),
    ("locked", "Locked"),
]


def cycle_filter_spec():
    return FilterSpec(
        fields=[
            FilterField("segment", "Segment", kind="choice", choices=segment_pk_choices),
            FilterField(
                "status", "Status", kind="choice",
                choices=lambda req: CYCLE_STATUS_CHOICES,
            ),
        ]
    )


# --- PCF Funds --------------------------------------------------------------

def pcf_fund_filter_spec():
    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="Fund code or name",
                search_fields=("fund_code", "name", "custodian_name"),
            ),
            FilterField("is_active", "Active", kind="bool"),
        ]
    )


# --- PCF Replenishments -----------------------------------------------------

PCF_REPLENISHMENT_STATUS_CHOICES = [
    ("requested", "Requested"),
    ("approved", "Approved"),
    ("posted", "Posted"),
]


def pcf_replenishment_filter_spec():
    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="Voucher no, payee or reference",
                search_fields=("voucher_no", "payee_name", "reference"),
            ),
            FilterField(
                "status", "Status", kind="choice",
                choices=lambda req: PCF_REPLENISHMENT_STATUS_CHOICES,
            ),
        ]
    )


# --- Bank Reconciliation ----------------------------------------------------

RECON_STATUS_CHOICES = [
    ("open", "Open"),
    ("resolved", "Resolved"),
    ("escalated", "Escalated"),
]


def recon_filter_spec():
    return FilterSpec(
        fields=[
            FilterField("bank_account", "Bank Account", kind="choice", choices=bank_choices),
            FilterField(
                "status", "Status", kind="choice",
                choices=lambda req: RECON_STATUS_CHOICES,
            ),
        ]
    )


# --- Cash Short / Excess ----------------------------------------------------

CASH_SHORT_STATUS_CHOICES = [
    ("open", "Open"),
    ("approved", "Approved"),
    ("adjusted", "Adjusted"),
]

CASH_SHORT_CAUSE_CHOICES = [
    ("typo", "Typo"),
    ("pop", "POP"),
    ("cashier", "Cashier"),
    ("other", "Other"),
]


def cash_short_filter_spec():
    return FilterSpec(
        fields=[
            FilterField("segment", "Segment", kind="choice", choices=segment_pk_choices),
            FilterField(
                "status", "Status", kind="choice",
                choices=lambda req: CASH_SHORT_STATUS_CHOICES,
            ),
            FilterField(
                "cause_category", "Cause", kind="choice",
                choices=lambda req: CASH_SHORT_CAUSE_CHOICES,
            ),
        ]
    )
