"""UI template filters."""

from django.template import Library

register = Library()


@register.filter
def get_item(mapping, key):
    """dict[key] lookup — used for per-segment amount columns."""
    try:
        return mapping[key]
    except (KeyError, TypeError):
        return None