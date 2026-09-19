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
    "deposit_list_filter_spec",
    "supplier_list_filter_spec",
    "rfp_filter_spec",
    "po_filter_spec",
    "cv_filter_spec",
    "je_filter_spec",
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
            FilterField("segment", "Segment", kind="choice", choices=segment_pk_choices),
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


def deposit_list_filter_spec():
    return FilterSpec(
        fields=[
            FilterField(
                "q", "Search", kind="text", placeholder="Slip no / reference",
                search_fields=("deposit_no", "reference"),
            ),
            FilterField("bank_account", "Bank Account", kind="choice", choices=account_choices),
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
