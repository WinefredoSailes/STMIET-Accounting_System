from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

MONEY_QUANT = Decimal("0.01")


def money(value) -> Decimal:
    """Canonical money normalization: 2dp, half-up, no floating point."""
    return Decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def approve_threshold() -> Decimal:
    """ADR-033: threshold above which a JE requires a second reviewer."""
    return money(settings.DOMAIN["JE_APPROVAL_THRESHOLD"])