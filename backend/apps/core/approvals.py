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

# CV lifecycle holders: created->signed (COO), signed->released (staff /
# treasury e.g. Quibs), released->cleared (head approves the release).
# ACCTG-FOR-010 / 7.4.
CV_NEXT_ROLE = {
    "created": "coo",
    "signed": "staff",
    "released": "head",
}


def display_name(user):
    """Full name when the account has one, else the username (never blank)."""
    if user is None:
        return ""
    full = user.get_full_name().strip()
    return full or user.username


def get_profile(user, create=True):
    """Return the user's profile (created on demand, role empty)."""
    from apps.foundation.models import UserProfile

    if create:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile
    return getattr(user, "profile", None)


def approval_role_of(user):
    """The single approval role a user holds ("" when unassigned)."""
    profile = get_profile(user, create=False)
    return profile.approval_role if profile else ""


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
        if rfp.status == "fin_approved":
            if rfp.amount > 100000:
                role = "coo"
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
                    "action": ("ui:rfp_approve", rfp.id),
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
                        ("ui:cv_sign", cv.id)
                        if cv.status == "created"
                        else ("ui:cv_release", cv.id)
                        if cv.status == "signed"
                        else ("ui:cv_clear", cv.id)
                    ),
                    "action_label": {"created": "Sign", "signed": "Release", "released": "Clear"}[
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


def pending_approval_queue(user):
    """All documents waiting on `user`, oldest first (My Approvals)."""
    role = approval_role_of(user)
    if not role:
        return []
    queues = rfp_queue({role}) + cv_queue({role}) + cash_short_queue({role})
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