from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.conf import settings

from apps.core.exceptions import ValidationError

MONEY_QUANT = Decimal("0.01")


def money(value) -> Decimal:
    """Canonical money normalization: 2dp, half-up, no floating point.

    Raises ValidationError (an AccountingError the UI/API already render)
    instead of leaking decimal.InvalidOperation when a form posts an empty
    or malformed amount.
    """
    if value is None or value == "":
        raise ValidationError("Amount cannot be empty.")
    if isinstance(value, str):
        value = value.strip().replace(",", "").replace("₱", "")
    try:
        return Decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError(f"Invalid amount: {value!r}") from exc


def approve_threshold() -> Decimal:
    """ADR-033: threshold above which a JE requires a second reviewer."""
    return money(settings.DOMAIN["JE_APPROVAL_THRESHOLD"])