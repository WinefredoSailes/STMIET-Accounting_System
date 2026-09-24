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


def _approval_role(user):
    """The user's approval role ('' when unassigned) — cached per request."""
    from apps.core.approvals import get_approval_role

    return get_approval_role(user)


def weekly_verse(request):
    """The rotating featured Bible verse (ESV) for the current ISO week."""
    from .verses import weekly_verse as pick

    return {"weekly_verse": pick()}


def nav_sections(request):
    """Sidebar navigation built from apps.ui.nav.NAV_SECTIONS.

    Each item is annotated with its resolved URL and its active flag (set when
    the current request's url_name matches the item). Sections carrying
    ``superuser_only`` are dropped for non-superusers. The template loops this
    list, so adding a module = one config entry, zero template edits.
    """
    user = request.user
    if not user.is_authenticated:
        return {"nav_sections": []}

    from django.urls import NoReverseMatch, reverse

    from .nav import NAV_SECTIONS
    from .screens import effective_screens

    allowed = set(effective_screens(user))
    current = getattr(getattr(request, "resolver_match", None), "url_name", "")
    current_args = tuple(
        getattr(request.resolver_match, "kwargs", {}).values()
        if getattr(request, "resolver_match", None)
        else ()
    )

    sections = []
    for section in NAV_SECTIONS:
        if section.get("superuser_only") and not user.is_superuser:
            # A superuser-only section may still allow named approval roles.
            roles_allowed = section.get("roles_allowed") or []
            if not roles_allowed or _approval_role(user) not in roles_allowed:
                continue
        items = []
        for item in section["items"]:
            name = item["name"]
            # Screen access (ADR-047): hide what the user cannot open — the
            # middleware already 403s deep links, this keeps the desk honest.
            if name not in allowed:
                continue
            active = name == current
            also = item.get("also_active") or []
            if name in also and current in also:
                active = True
            # Statement entries share one URL name ('statement'); active only
            # when the current statement-type kwarg matches this item's arg.
            if name == "statement" and item.get("args"):
                active = current == "statement" and tuple(item["args"]) == current_args
            url = ""
            try:
                url = reverse(f"ui:{name}", args=item.get("args") or [])
            except NoReverseMatch:
                url = "#"
            items.append(
                {
                    "name": name,
                    "label": item["label"],
                    "icon": item["icon"],
                    "url": url,
                    "active": active,
                    "badge": item.get("badge"),
                }
            )
        if not items:
            continue  # nothing in this section is on their desk
        sections.append(
            {
                "label": section.get("label"),
                "pinned": section.get("pinned", False),
                "items": items,
                "active": any(i["active"] for i in items),
            }
        )
    return {"nav_sections": sections}