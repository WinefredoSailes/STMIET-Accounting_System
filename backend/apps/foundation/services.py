"""User management service (superadmin, ADR-020 / ADR-036).

Every approval in the system is driven by the "who does what" mapping on
``UserProfile.approval_role``:

    staff -> head -> coo

This service is the single place that lists users, creates logins, and
assigns approval roles, so the UI, API and admin can never drift. It is a
thin layer over Django's auth user and ``UserProfile`` — no UI logic here.
"""

from collections import defaultdict

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count
from django.utils.crypto import get_random_string

from apps.core.approvals import APPROVAL_ROLES
from apps.core.exceptions import ValidationError
from apps.foundation.models import UserProfile
from apps.cash.models import PettyCashFund

User = get_user_model()


def _role_label(role):
    from apps.core.approvals import ROLE_LABELS

    return ROLE_LABELS.get(role, "")


class UserManagementService:
    """CRUD over logins + their accounting approval role."""

    @staticmethod
    def list_users():
        """All logins ordered by approval role (staff first), then username.

        Each row carries the approval role label, whether the account is
        active / a superuser, and the petty-cash funds the user is custodian
        of (so the "who does what" view shows custodians too).
        """
        funds_by_user = defaultdict(list)
        for fund in PettyCashFund.objects.exclude(custodian=None):
            funds_by_user[fund.custodian_id].append(fund.fund_code)
        profiles = {
            p.user_id: p
            for p in UserProfile.objects.select_related("user")
        }
        rows = []
        for u in User.objects.all().order_by("username"):
            p = profiles.get(u.pk)
            role = p.approval_role if p else ""
            rows.append(
                {
                    "user": u,
                    "profile": p,
                    "role": role,
                    "role_label": _role_label(role)
                    or (role if role else "Unassigned"),
                    "position": next(
                        (i for i, r in enumerate(APPROVAL_ROLES) if r == role),
                        None,
                    ),
                    "pcf_funds": funds_by_user.get(u.pk, []),
                }
            )
        return sorted(
            rows,
            key=lambda r: (
                r["position"] if r["position"] is not None else len(APPROVAL_ROLES),
                r["user"].username.lower(),
            ),
        )

    @staticmethod
    def custodian_stats():
        """PCF wait — number of funds each custodian holds (for the page header)."""
        return PettyCashFund.objects.exclude(custodian=None).values(
            "custodian__username"
        ).annotate(n=Count("id")).order_by("custodian__username")

    @staticmethod
    def create_user(*, username, first_name="", last_name="", email="", role="", password=None):
        """Create a login and its approval profile."""
        username = (username or "").strip()
        email = (email or "").strip()
        role = (role or "").strip()
        if not username:
            raise ValidationError("Username is required.")
        if role and role not in APPROVAL_ROLES:
            raise ValidationError(f"Unknown approval role '{role}'.")

        with transaction.atomic():
            password = password or get_random_string(length=16)
            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=(first_name or "").strip(),
                last_name=(last_name or "").strip(),
                password=password,
            )
            UserProfile.objects.create(user=user, approval_role=role)
            return user

    @staticmethod
    def assign_role(*, user, role):
        """Set (or clear) a user's approval role."""
        role = (role or "").strip()
        if role and role not in APPROVAL_ROLES:
            raise ValidationError(f"Unknown approval role '{role}'.")
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.approval_role = role
        profile.save(update_fields=["approval_role", "updated_at"])
        return profile

    @staticmethod
    def set_active(*, user, is_active):
        """Deactivate / reactivate a login (soft — keeps history)."""
        user.is_active = bool(is_active)
        user.save(update_fields=["is_active"])
        return user