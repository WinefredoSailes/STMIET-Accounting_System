"""UI template filters."""

from decimal import Decimal, InvalidOperation

from django.template import Library

register = Library()


@register.filter
def get_item(mapping, key):
    """dict[key] lookup — used for per-segment amount columns."""
    try:
        return mapping[key]
    except (KeyError, TypeError):
        return None


@register.filter
def money(value):
    """Format an amount with thousand separators + 2dp: 1234567.5 -> "1,234,567.50"."""
    try:
        return f"{Decimal(value):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return value