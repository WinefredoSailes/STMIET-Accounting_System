"""Approval roles and the "My Approvals" inbox (ADR-020, ADR-036).

Three positions drive every approval:

    staff (prepares/submits) -> head (checks + acctg + fin) -> coo (>P100k)

Roles are stored on ``apps.foundation.UserProfile``: the Accounting &
Finance Head is the user whose profile says ``head`` (Alywin Aidan D. Baje
in the demo seed) and he is the checker of everything; the COO's profile
says ``coo`` and only sees RFPs above P100k. Everything here derives from
that mapping — nothing is hard-coded to a login name.
"""

from datetime import date

from django.core.exceptions import PermissionDenied
from django.db.models import Q

from apps.core.exceptions import ValidationError

APPROVAL_ROLES = (
    "staff",
    "head",
    "coo",
)

ROLE_LABELS = {
    "staff": "Accounting Staff",
    "head": "Accounting & Finance Head",
    "coo": "COO (CNR)",
}

# RFP status -> approval role that must act next (ADR-020). The head
# checks and approves at every step; the COO only above P100k.
RFP_NEXT_ROLE = {
    "prepared": "head",
    "submitted": "head",
    "checked": "head",
    "acctg_approved": "head",
}

# RFP step names (as used by the approve endpoints) -> profile role keys.
RFP_STEP_TO_ROLE = {
    "checked": "head",
    "acctg_approved": "head",
    "fin_approved": "head",
}

# CV lifecycle holders: every CV action lands on the Accounting & Finance
# Head — created->approved (head signs off), approved->cleared (head books
# the encashment). The COO is not part of the CV path (per current policy);
# ACCTG-FOR-010 / 7.4.
CV_NEXT_ROLE = {
    "created": "head",
    "approved": "head",
}

# Manual Journal Entry approval: staff submits → head approves.
# COO gate can be added later for >₱100k entries (extend map).
JE_NEXT_ROLE = {
    "submitted": "head",
}

# Billing transaction approval: staff prepares/submits → head approves (and
# then posts the Journal Entry).
BILLING_NEXT_ROLE = {
    "submitted": "head",
}

# Acknowledgment Receipt status -> next approval role (ADR-033).
# Same pattern: head checks and approves at every step; no amount threshold.
AR_NEXT_ROLE = {
    "submitted": "head",
}

# Sales Invoice (SI) status -> next approval role (ADR-033). Mirrors receipts:
# the preparer submits, the Head approves and posts the revenue JE.
AR_INVOICE_NEXT_ROLE = {
    "submitted": "head",
}

# Inter-account transfer status -> next approval role (ADR-030). Mirrors JE:
# the preparer submits, the head approves (and the JE posts).
TRANSFER_NEXT_ROLE = {
    "submitted": "head",
}


# Purchase Order status -> next approval role (ADR-0XX). Same matrix as the
# RFP: the head checks and approves at every step; the COO only above P100k
# (POs at `fin_approved` appear here only while the COO gate is due).
PO_NEXT_ROLE = {
    "prepared": "head",
    "submitted": "head",
    "checked": "head",
    "acctg_approved": "head",
    "fin_approved": "coo",
}


# Master-data write permissions (COA, customers, suppliers, bank accounts):
# the Accounting & Finance Head edits; accounting staff can only add.
MASTER_CREATE_ROLES = ("staff", "head")
MASTER_EDIT_ROLES = ("head",)


def can_create_master(user):
    """Whether `user` may add master data (add-only for staff)."""
    if user.is_superuser:
        return True
    return approval_role_of(user) in MASTER_CREATE_ROLES


def can_edit_master(user):
    """Whether `user` may edit master data (head + admins only)."""
    if user.is_superuser:
        return True
    return approval_role_of(user) in MASTER_EDIT_ROLES


def require_can_create_master(user):
    """Gate: raise PermissionDenied unless `user` may add master data."""
    if not can_create_master(user):
        raise PermissionDenied(
            "Adding master data (COA, customers, suppliers, banks) requires an "
            "accounting staff or Accounting & Finance Head account."
        )


def require_can_edit_master(user):
    """Gate: raise PermissionDenied unless `user` may edit master data."""
    if not can_edit_master(user):
        raise PermissionDenied(
            "Editing master data (COA, customers, suppliers, banks) is reserved "
            "for the Accounting & Finance Head. Accounting staff can only add."
        )


def display_name(user):
    """Full name when the account has one, else the username (never blank)."""
    if user is None:
        return ""
    full = user.get_full_name().strip()
    return full or user.username


def signatory_name(user):
    """Printed-name resolution for RFP/CV signature blocks (dynamic).

    Always reads the account's own first_name/last_name fields, so a
    different account holder prints their own name. Resolution order:
    "first last" -> first_name -> last_name -> username -> "".
    """
    if user is None:
        return ""
    first = (user.first_name or "").strip()
    last = (user.last_name or "").strip()
    if first and last:
        return f"{first} {last}"
    if first:
        return first
    if last:
        return last
    return user.username


def get_profile(user, create=True):
    """Return the user's profile (created on demand, role empty)."""
    from apps.foundation.models import UserProfile

    if create:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile
    return getattr(user, "profile", None)


def get_approval_role(user):
    """The single approval role a user holds ("" when unassigned)."""
    profile = get_profile(user, create=False)
    return profile.approval_role if profile else ""


# Backward-compatible name for existing callers.
approval_role_of = get_approval_role


def users_with_role(role):
    """Every user pk holding `role` (used for the 'Awaiting …' display)."""
    from apps.foundation.models import UserProfile

    return list(
        UserProfile.objects.filter(approval_role=role)
        .select_related("user")
        .values_list("user", flat=True)
    )


def role_assignee(role):
    """Primary assignee name for `role` ("" when nobody holds it)."""
    from django.contrib.auth import get_user_model

    users = users_with_role(role)
    if not users:
        return ""
    return display_name(get_user_model().objects.get(pk=users[0]))


def require_approval_role(user, role):
    """Raise unless `user` holds `role` (the loud gate — never silent).

    `role` may be a profile role key (checker/acctg/fin/cnr) or an RFP
    step name (checked/acctg_approved/fin_approved) — both are normalized.
    """
    role = RFP_STEP_TO_ROLE.get(role, role)
    held = approval_role_of(user)
    if held != role:
        assignee = role_assignee(role)
        who = f" ({assignee})" if assignee else ""
        raise ValidationError(
            f"This step is for the {ROLE_LABELS[role]}{who}. "
            f"You are signed in as {display_name(user)} "
            f"({ROLE_LABELS.get(held, 'no approval role')}) — the document was not moved."
        )
    return role


def rfp_queue(user_roles):
    """RFPs waiting on any of `user_roles` (set of role keys).

    Prepared RFPs are excluded: the staff who raised them submits them
    first (the head's queue starts at "submitted").
    """
    from apps.ap.models import RFPDocument

    out = []
    docs = RFPDocument.objects.filter(
        status__in=list(RFP_NEXT_ROLE) + ["fin_approved"]
    ).select_related("payee", "segment", "created_by")
    for rfp in docs:
        if rfp.status == "prepared":
            continue  # awaits the preparer's submit, not an approval
        role = RFP_NEXT_ROLE.get(rfp.status)
        cnr = False
        if rfp.status == "fin_approved":
            from apps.ap.services import coo_required

            if coo_required(rfp):
                role = "coo"
                cnr = True
            else:
                continue  # fully approved, waits for CONSO
        if role in user_roles:
            out.append(
                {
                    "kind": "rfp",
                    "role": role,
                    "doc": rfp,
                    "number": rfp.ap_number,
                    "title": rfp.particulars or (rfp.payee.name if rfp.payee else ""),
                    "date": rfp.rfp_date,
                    "amount": rfp.amount,
                    "detail": ("ui:rfp_detail", rfp.id),
                    # The CNR step lives on its own endpoint — signing from
                    # the inbox must hit the CNR Manager action, not Head's.
                    "action": (
                        "ui:rfp_approve_cnr" if cnr else "ui:rfp_approve",
                        rfp.id,
                    ),
                    "action_label": (
                        "Check" if rfp.status in ("prepared", "submitted") else "Approve"
                    ),
                }
            )
    return out


def cv_queue(user_roles):
    """Check vouchers waiting on any of `user_roles`."""
    from apps.ap.models import CheckVoucher

    out = []
    docs = CheckVoucher.objects.filter(status__in=list(CV_NEXT_ROLE)).select_related(
        "payee", "rfp"
    )
    for cv in docs:
        role = CV_NEXT_ROLE[cv.status]
        if role in user_roles:
            ref = cv.rfp.ap_number if cv.rfp_id else "standalone"
            out.append(
                {
                    "kind": "cv",
                    "role": role,
                    "doc": cv,
                    "number": cv.cv_number,
                    "title": f"payable to {cv.payee.name if cv.payee else ''} · ref {ref}",
                    "date": cv.cv_date,
                    "amount": cv.gross_amount,
                    "detail": ("ui:cv_detail", cv.id),
                    "action": (
                        ("ui:cv_approve", cv.id)
                        if cv.status == "created"
                        else ("ui:cv_clear", cv.id)
                        if cv.status == "approved"
                        else ("ui:cv_clear", cv.id)
                    ),
                    "action_label": {"created": "Approve", "approved": "Clear"}[
                        cv.status
                    ],
                }
            )
    return out


def cash_short_queue(user_roles):
    """Open cash short/excess worksheets waiting on the head."""
    from apps.cash.models import CashShortExcessWorksheet

    if "head" not in user_roles:
        return []
    out = []
    docs = CashShortExcessWorksheet.objects.filter(status="open").select_related(
        "cycle__segment", "created_by"
    )
    for ws in docs:
        seg = ws.cycle.segment.code if ws.cycle_id and ws.cycle else ""
        out.append(
            {
                "kind": "cash_short",
                "role": "head",
                "doc": ws,
                "number": f"#{ws.id}",
                "title": f"{seg} variance ₱{ws.variance} · reported by {display_name(ws.created_by)}",
                "date": ws.created_at.date() if ws.created_at else None,
                "amount": abs(ws.variance),
                "detail": ("ui:cash_short_list",),
                "action": ("ui:cash_short_approve", ws.id),
                "action_label": "Approve",
            }
        )
    return out


def transfer_queue(user_roles):
    """Inter-account transfers waiting on the head (ADR-030, no threshold).

    Mirrors rfp_queue/cv_queue: a transfer appears in the head's inbox only
    once the preparer has submitted it; the head's approval posts its JE.
    """
    if "head" not in user_roles:
        return []
    from apps.cash.models import InterAccountTransfer

    out = []
    docs = InterAccountTransfer.objects.filter(status="submitted").select_related(
        "from_account", "to_account", "initiated_by"
    )
    for transfer in docs:
        label = transfer.voucher_no or f"FTV#{transfer.id}"
        out.append(
            {
                "kind": "transfer",
                "role": "head",
                "doc": transfer,
                "number": label,
                "title": (
                    f"{transfer.from_account.code} -> {transfer.to_account.code} "
                    f"· {transfer.purpose}"
                ),
                "date": transfer.transfer_date,
                "amount": transfer.amount,
                "detail": ("ui:transfer_detail", transfer.id),
                "action": ("ui:transfer_approve", transfer.id),
                "action_label": "Approve",
            }
        )
    return out


def reversal_queue(user_roles):
    """Pending journal-entry reversal requests waiting on the head (ADR-004)."""
    if "head" not in user_roles:
        return []
    from apps.posting.models import ReversalRequest

    out = []
    docs = ReversalRequest.objects.filter(
        status=ReversalRequest.Status.REQUESTED
    ).select_related("entry", "requested_by")
    for req in docs:
        out.append(
            {
                "kind": "reversal",
                "role": "head",
                "doc": req,
                "number": f"REV {req.entry.entry_no}",
                "title": f"Reversal requested · {req.reason[:60]}",
                "date": req.requested_at.date() if req.requested_at else None,
                "amount": req.entry.total_debit,
                "detail": ("ui:je_detail", req.entry_id),
                "action": ("ui:je_reversal_approve", req.id),
                "action_label": "Approve reversal",
            }
        )
    return out


def je_queue(user_roles):
    """Manual Journal Entries waiting on `user_roles` (head only).

    Document-owned JEs (CV/RFP/Billing/Transfer/PCF/AR receipt/AR deposit)
    are deliberately excluded: they are approved from their own document's
    screen and would show up here only when out of sync with that document's
    submission state. The "Journal Entries" inbox therefore lists manual JEs
    only, and only once they reach ``submitted``.
    """
    if "head" not in user_roles:
        return []
    from apps.posting.models import JournalEntry, PostingStatus

    out = []
    docs = (
        JournalEntry.objects.filter(status=PostingStatus.SUBMITTED)
        .select_related("company", "segment", "created_by")
        .exclude(
            Q(cv__isnull=False)
            | Q(rfps__isnull=False)
            | Q(billing_documents__isnull=False)
            | Q(transfers__isnull=False)
            | Q(pcf_replenishments__isnull=False)
            | Q(ar_receipts__isnull=False)
            | Q(ar_deposits__isnull=False)
        )
    )
    for je in docs:
        out.append(
            {
                "kind": "je",
                "role": "head",
                "doc": je,
                "number": je.entry_no,
                "title": je.description or "Journal Entry",
                "date": je.transaction_date,
                "amount": je.total_debit,
                "detail": ("ui:je_detail", je.id),
                "action": ("ui:je_approve", je.id),
                "action_label": "Approve",
            }
        )
    return out


def po_queue(user_roles):
    """Purchase Orders waiting on any of `user_roles` (same matrix as RFPs).

    Prepared POs are excluded — the preparer submits them first, so the head's
    in-box starts at "submitted". `fin_approved` POs are listed only while the
    COO gate (ADR-0XX) is actually due; otherwise they are already approved
    and RFP-bankable.
    """
    from apps.ap.models import PurchaseOrder

    out = []
    docs = PurchaseOrder.objects.filter(status__in=list(PO_NEXT_ROLE)).select_related(
        "supplier", "segment", "created_by"
    )
    for po in docs:
        if po.status == "prepared":
            continue  # awaits the preparer's submit, not an approval
        role = PO_NEXT_ROLE.get(po.status)
        if po.status == "fin_approved":
            from apps.ap.services import po_coo_required

            if po_coo_required(po):
                role = "coo"
            else:
                continue  # marked 'approved', ready for RFP funding
        if role in user_roles:
            out.append(
                {
                    "kind": "po",
                    "role": role,
                    "doc": po,
                    "number": po.po_number,
                    "title": po.particulars or (po.supplier.name if po.supplier else ""),
                    "date": po.po_date,
                    "amount": po.amount,
                    "detail": ("ui:po_detail", po.id),
                    "action": ("ui:po_approve", po.id),
                    "action_label": (
                        "Check" if po.status in ("prepared", "submitted") else "Approve"
                    ),
                }
            )
    return out


def ar_receipt_queue(user_roles):
    """Acknowledgment Receipts waiting on any of `user_roles`.

    Receipts in "submitted" status wait for the Accounting & Finance Head.
    Receipts in "draft" or "posted" are excluded.
    """
    from apps.ar.models import AcknowledgmentReceipt

    out = []
    docs = AcknowledgmentReceipt.objects.filter(
        status="submitted"
    ).select_related("customer", "segment", "created_by")
    for receipt in docs:
        role = AR_NEXT_ROLE.get(receipt.status)
        if role in user_roles:
            out.append(
                {
                    "kind": "ar_receipt",
                    "role": role,
                    "doc": receipt,
                    "number": receipt.receipt_no,
                    "title": f"AR · {receipt.customer.name} · {receipt.segment.code if receipt.segment else ''}",
                    "date": receipt.transaction_date,
                    "amount": receipt.amount,
                    "detail": ("ui:receipt_detail", receipt.id),
                    "action": ("ui:receipt_approve", receipt.id),
                    "action_label": "Approve",
                }
            )
    return out


def ar_invoice_queue(user_roles):
    """Sales Invoices waiting on any of `user_roles`.

    SIs in "submitted" status wait for the Accounting & Finance Head, who
    approves and posts the revenue JE. Drafts are excluded; approved SIs are
    posted and drop out of the queue.
    """
    from apps.ar.models import ARInvoice

    out = []
    docs = ARInvoice.objects.filter(
        status="submitted"
    ).select_related("customer", "segment", "created_by")
    for invoice in docs:
        role = AR_INVOICE_NEXT_ROLE.get(invoice.status)
        if role in user_roles:
            out.append(
                {
                    "kind": "invoice",
                    "role": role,
                    "doc": invoice,
                    "number": invoice.invoice_no,
                    "title": f"SI · {invoice.customer.name} · {invoice.segment.code if invoice.segment else ''}",
                    "date": invoice.transaction_date,
                    "amount": invoice.total,
                    "detail": ("ui:si_detail", invoice.id),
                    "action": ("ui:si_approve", invoice.id),
                    "action_label": "Approve",
                }
            )
    return out


def billing_queue(user_roles):
    """Billing transactions waiting on `user_roles` (head only).

    Billing documents in "submitted" status wait on the Accounting & Finance
    Head, who approves and then posts the Journal Entry.
    """
    if "head" not in user_roles:
        return []
    from apps.billing.models import BillingDocument, BillingStatus

    out = []
    docs = BillingDocument.objects.filter(
        status=BillingStatus.SUBMITTED
    ).select_related("segment", "created_by", "rfp")
    for billing in docs:
        title = billing.particulars or billing.party_name or "Billing"
        if billing.rfp_id:
            title = f"{title} · RFP {billing.rfp.ap_number}"
        out.append(
            {
                "kind": "billing",
                "role": "head",
                "doc": billing,
                "number": billing.billing_no,
                "title": title,
                "date": billing.billing_date,
                "amount": billing.amount,
                "detail": ("ui:billing_detail", billing.id),
                "action": ("ui:billing_approve", billing.id),
                "action_label": "Approve",
            }
        )
    return out


def pcf_queue(user_roles):
    """Petty cash replenishments waiting on the head.

    PCF replenishments have no preparer submit step (mirroring CV ``created``
    and cash-short ``open``): ``requested`` is the awaiting-head state — the
    head's approval batches the claim to CONSO.
    """
    if "head" not in user_roles:
        return []
    from apps.cash.models import PCFReplenishment

    out = []
    docs = PCFReplenishment.objects.filter(status="requested").select_related(
        "fund", "requested_by"
    )
    for replen in docs:
        fund = replen.fund.fund_code if replen.fund_id else ""
        out.append(
            {
                "kind": "pcf",
                "role": "head",
                "doc": replen,
                "number": replen.voucher_no or f"PCF-{replen.id}",
                "title": f"{fund} replenishment",
                "date": replen.request_date,
                "amount": replen.amount,
                "detail": ("ui:pcf_replenishment_detail", replen.id),
                "action": ("ui:pcf_replenishment_approve", replen.id),
                "action_label": "Approve",
            }
        )
    return out


def pending_approval_queue(user):
    """All documents waiting on `user`, oldest first (My Approvals)."""
    role = approval_role_of(user)
    if not role:
        return []
    queues = (
        rfp_queue({role})
        + po_queue({role})
        + cv_queue({role})
        + cash_short_queue({role})
        + transfer_queue({role})
        + je_queue({role})
        + reversal_queue({role})
        + ar_receipt_queue({role})
        + ar_invoice_queue({role})
        + billing_queue({role})
        + pcf_queue({role})
    )
    queues.sort(key=lambda item: (item["date"] or date.min, item["number"]))
    return queues


def pending_approval_count(user):
    """Count used for the sidebar badge."""
    return len(pending_approval_queue(user))


def group_by_role(queues):
    """[(role, label, [items])] in approval-chain order."""
    buckets = {}
    for item in queues:
        buckets.setdefault((item["role"], ROLE_LABELS[item["role"]]), []).append(item)
    return [
        (role, label, buckets[(role, label)])
        for role, label in sorted(
            buckets, key=lambda kv: APPROVAL_ROLES.index(kv[0])
        )
    ]