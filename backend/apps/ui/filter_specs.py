"""Per-screen filter specs so the shared partial can render + apply consistently."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from apps.foundation.models import Account, AccountType, CostCenter, Segment
from apps.ar.models import Customer
from apps.ap.models import Supplier


@dataclass
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
    fields: list = field(default_factory=list)

    def apply(self, qs, params):
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

    def context(self, params, request=None):
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


def segment_choices(request=None):
    from apps.foundation.models import Segment

    return [(s.code, s.code) for s in Segment.objects.order_by("code")]


def coa_filter_spec():
    return FilterSpec(
        fields=[
            FilterField("q", "Search", kind="text", placeholder="Code or name"),
            FilterField("segment", "Segment", kind="choice", choices=segment_choices),
            FilterField("account_type", "Type", kind="choice", choices=lambda req: AccountType.choices),
        ]
    )


def receipt_list_filter_spec():
    from apps.ar.services import segment_choices as _seg_choices
    return FilterSpec(
        fields=[
            FilterField("q", "Search", kind="text", placeholder="Receipt no or customer"),
            FilterField("status", "Status", kind="choice", choices=lambda: [("draft", "Draft"), ("submitted", "Submitted"), ("posted", "Posted")]),
            FilterField("customer", "Customer", kind="choice", choices=lambda req: [(str(c.id), c.name) for c in Customer.objects.order_by("name")]),
        ]
    )


def deposit_list_filter_spec():
    from apps.foundation.models import Account
    from apps.ar.services import segment_choices as _seg_choices
    return FilterSpec(
        fields=[
            FilterField("q", "Search", kind="text", placeholder="Reference"),
            FilterField("status", "Status", kind="choice", choices=lambda req: [("posted", "Posted"), ("draft", "Draft")]),
            FilterField("bank_account", "Bank Account", kind="choice", choices=lambda req: [(str(a.id), str(a.code)) for a in Account.objects.filter(is_postable=True).order_by("code")]),
        ]
    )


def customer_list_filter_spec():
    from apps.ar.models import Customer
    return FilterSpec(
        fields=[
            FilterField("q", "Search", kind="text", placeholder="Name or group"),
            FilterField("segment", "Segment", kind="choice", choices=lambda: [(s.code, s.code) for s in Customer._meta.get_field("segment").choices]),
            FilterField("pricing_tier", "Pricing Tier", kind="choice", choices=lambda: [(t.value, t.label) for t in Customer._meta.get_field("pricing_tier").choices]),
        ]
    )


def rfq_filter_spec():
    from apps.ap.models import CheckVoucher
    return FilterSpec(
        fields=[
            FilterField("q", "Search", kind="text", placeholder="PO / CV number"),
            FilterField("status", "Status", kind="choice", choices=lambda: [("draft", "Draft"), ("submitted", "Submitted"), ("posted", "Posted")]),
            FilterField("payee", "Payee", kind="choice", choices=lambda req: [(str(p.id), p.name) for p in ...]),
        ]
    )