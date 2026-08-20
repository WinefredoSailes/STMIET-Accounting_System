"""Context processors: sidebar badge for the My Approvals queue (ADR-036)."""


def pending_approval_count(request):
    """Number of documents waiting on the logged-in user's approval step."""
    user = request.user
    if not user.is_authenticated:
        return {"pending_approval_count": 0}
    from apps.core.approvals import pending_approval_count as queued

    return {"pending_approval_count": queued(user)}