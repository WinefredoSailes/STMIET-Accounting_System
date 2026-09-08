"""UI template filters and tags."""

from decimal import Decimal, InvalidOperation

from django import template
from django.template import Library, Node, TemplateSyntaxError

register = Library()


@register.filter
def get_item(mapping, key):
    """dict[key] lookup - used for per-segment amount columns."""
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


@register.filter
def split(value, sep=" "):
    """Split a string into a list - lets partials accept token lists (e.g.
    report_toolbar takes formats="xlsx csv pdf")."""
    return [part for part in str(value).split(sep) if part]


@register.filter
def pct(value):
    """Fraction (0.85) -> whole-percent display (85%)."""
    try:
        return f"{Decimal(value) * 100:,.0f}%"
    except (InvalidOperation, TypeError, ValueError):
        return value


# Single source of truth for status -> Tailwind badge color mapping.
# Consumed by ui/partials/status_badge.html. "Approved" and "open" have
# domain-specific colors today (JE approved = blue, cash-short approved =
# emerald); those screens pass `color` explicitly when they refactor, and this
# dict stays the canonical default.
STATUS_COLOR_CLASSES = {
    # emerald = terminal / done states
    "posted": "bg-emerald-100 text-emerald-800",
    "closed": "bg-emerald-100 text-emerald-800",
    "cleared": "bg-emerald-100 text-emerald-800",
    "liquidated": "bg-emerald-100 text-emerald-800",
    "resolved": "bg-emerald-100 text-emerald-800",
    "paid": "bg-emerald-100 text-emerald-800",
    "locked": "bg-emerald-100 text-emerald-800",
    "active": "bg-emerald-100 text-emerald-800",
    "approved": "bg-emerald-100 text-emerald-800",
    # amber = in-flight / workflow mid-states
    "acctg_approved": "bg-amber-100 text-amber-800",
    "fin_approved": "bg-amber-100 text-amber-800",
    "cnr_approved": "bg-amber-100 text-amber-800",
    "checked": "bg-amber-100 text-amber-800",
    "submitted": "bg-amber-100 text-amber-800",
    "pending": "bg-amber-100 text-amber-800",
    "in_progress": "bg-amber-100 text-amber-800",
    "due": "bg-amber-100 text-amber-800",
    # indigo = treasury / post-signing
    "reconciled": "bg-indigo-100 text-indigo-800",
    "signed": "bg-indigo-100 text-indigo-800",
    "released": "bg-indigo-100 text-indigo-800",
    # red = failure states
    "rejected": "bg-red-100 text-red-800",
    "void": "bg-red-100 text-red-800",
    "reversed": "bg-red-100 text-red-800",
    "overdue": "bg-red-100 text-red-800",
    # slate = draft / created / neutral
    "draft": "bg-slate-100 text-slate-700",
    "prepared": "bg-slate-100 text-slate-700",
    "created": "bg-slate-100 text-slate-700",
    "open": "bg-slate-100 text-slate-600",
    "disposed": "bg-slate-100 text-slate-500",
}


@register.filter
def status_color_class(status):
    """Map a workflow status string to its Tailwind badge classes."""
    return STATUS_COLOR_CLASSES.get(status, "bg-slate-100 text-slate-600")


class CaptureNode(Node):
    """Render the body and store the output in a context variable.

    Enables the block-in-parameter pattern for partials that wrap variable
    content (list_card, form_card, document_shell): the caller captures its
    markup with {% capture as x %}...{% endcapture %} and passes it to the
    partial via {% include ... with ... %}.
    """

    def __init__(self, nodelist, varname):
        self.nodelist = nodelist
        self.varname = varname

    def render(self, context):
        context[self.varname] = self.nodelist.render(context)
        return ""


@register.tag(name="capture")
def do_capture(parser, token):
    bits = token.split_contents()
    if len(bits) != 3 or bits[1] != "as":
        raise TemplateSyntaxError("'capture' requires syntax: {% capture as varname %}")
    nodelist = parser.parse(("endcapture",))
    parser.delete_first_token()
    return CaptureNode(nodelist, bits[2])