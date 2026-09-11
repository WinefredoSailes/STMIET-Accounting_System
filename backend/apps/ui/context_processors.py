"""Context processors: sidebar badge for the My Approvals queue (ADR-036)."""


def pending_approval_count(request):
    """Number of documents waiting on the logged-in user's approval step."""
    user = request.user
    if not user.is_authenticated:
        return {"pending_approval_count": 0}
    from apps.core.approvals import pending_approval_count as queued

    return {"pending_approval_count": queued(user)}


def master_data_permissions(request):
    """Write flags for master data (COA/customers/suppliers/banks) so the
    templates show add/edit controls only to the roles allowed to use them."""
    user = request.user
    if not user.is_authenticated:
        return {"can_create_master": False, "can_edit_master": False}
    from apps.core.approvals import can_create_master, can_edit_master

    return {
        "can_create_master": can_create_master(user),
        "can_edit_master": can_edit_master(user),
    }