"""Declarative, reusable list filtering — one engine for every list screen.

Each list screen declares a :class:`FilterSpec` (a list of :class:`FilterField`)
and the shared ``ui/partials/filter_bar.html`` renders the controls; HTMX swaps
the table fragment. Exports reuse the same spec so a download always matches
what the user sees.

Adding a filter to a screen is one line::

    REALM_FILTERS = FilterSpec([
        FilterField("q", "Search", kind="text"),
        FilterField("segment", "Segment", kind="choice", choices=segment_choices),
        FilterField("status", "Status", kind="choice", choices=AssetStatus.choices),
    ])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from django.db.models import Q


@dataclass(frozen=True)
class Option:
    value: str
    label: str


def _normalize_options(raw) -> list[Option]:
    out: list[Option] = []
    for item in raw or []:
        if isinstance(item, Option):
            out.append(item)
        elif isinstance(item, (tuple, list)):
            value, label = item[0], item[1]
            out.append(Option(str(value), str(label)))
        else:
            out.append(Option(str(item), str(item)))
    return out


@dataclass
class FilterField:
    """One filter control mapped to an ORM lookup.

    ``kind``: text | choice | date | bool | number.
    ``choices``: an iterable of (value, label) pairs, or a callable taking the
    request and returning them (for DB-backed option lists).
    ``lookup``: explicit ORM suffix (e.g. "gte", "lte"); defaults to
    ``icontains`` for text and ``exact`` otherwise.
    """

    name: str
    label: str
    kind: str = "text"
    choices: object = None
    lookup: str = ""
    placeholder: str = ""
    empty_label: str = ""

    def resolve_choices(self, request=None) -> list[Option]:
        choices = self.choices
        if callable(choices):
            choices = choices(request)
        return _normalize_options(choices)

    def effective_lookup(self) -> str:
        if self.lookup:
            return self.lookup
        if self.kind == "text":
            return "icontains"
        return "exact"


@dataclass
class FilterSpec:
    fields: list[FilterField] = field(default_factory=list)

    def apply(self, qs, params: dict):
        """Filter ``qs`` by the non-empty params named by this spec."""
        for f in self.fields:
            raw = params.get(f.name)
            if raw in (None, ""):
                continue
            if f.kind == "bool":
                value = str(raw).lower() in ("1", "true", "yes", "on")
            else:
                value = raw
            qs = qs.filter(**{f"{f.name}__{f.effective_lookup()}": value})
        return qs

    def context(self, params: dict, request=None) -> list[dict]:
        out = []
        for f in self.fields:
            out.append(
                {
                    "name": f.name,
                    "label": f.label,
                    "kind": f.kind,
                    "placeholder": f.placeholder,
                    "empty_label": f.empty_label or f"All {f.label.lower()}",
                    "value": params.get(f.name, ""),
                    "options": f.resolve_choices(request),
                }
            )
        return out

    def export_params(self, params: dict) -> dict:
        return {
            f.name: params.get(f.name, "")
            for f in self.fields
            if params.get(f.name, "") not in (None, "")
        }


# ---------------------------------------------------------------------------
# Shared option builders (DB-backed choice lists)
# ---------------------------------------------------------------------------


def segment_choices(request=None):
    from apps.foundation.models import Segment

    return [(s.code, s.code) for s in Segment.objects.order_by("code")]


def account_choices(request=None):
    from apps.foundation.models import Account

    return [
        (a.code, f"{a.code} — {a.name}")
        for a in Account.objects.filter(is_postable=True).order_by("code")
    ]


def cost_center_choices(request=None):
    from apps.foundation.models import CostCenter

    return [(c.code, c.code) for c in CostCenter.objects.filter(is_active=True).order_by("code")]


def customer_choices(request=None):
    from apps.ar.models import Customer

    return [(str(c.id), c.name) for c in Customer.objects.order_by("name")]


def supplier_choices(request=None):
    from apps.ap.models import Supplier

    return [(str(s.id), s.name) for s in Supplier.objects.order_by("name")]
