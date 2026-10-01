from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from django.db.models import Q

from apps.ui.screens import effective_screens


@dataclass
class Group:
    module: str
    label: str
    count: int
    items: list[dict[str, Any]]


@dataclass
class ExecutionResult:
    module: str
    groups: list[Group] = field(default_factory=list)
    error: str | None = None


class BaseExecutor:
    module_name: str = ""
    screen_key: str = ""

    def __init__(self, user, parsed_query):
        self.user = user
        self.parsed_query = parsed_query

    def has_access(self) -> bool:
        if self.user.is_superuser:
            return True
        if not self.screen_key:
            return self.user.is_authenticated
        screens = effective_screens(self.user)
        return self.screen_key in screens

    def execute(self) -> ExecutionResult:
        if not self.has_access():
            return ExecutionResult(module=self.module_name, error="no_access")
        try:
            groups = self._query()
        except Exception as exc:  # surface for tests, but keep the chat alive
            return ExecutionResult(module=self.module_name, error=str(exc))
        groups = [g for g in groups if g.items]
        return ExecutionResult(module=self.module_name, groups=groups)

    def _query(self) -> list[Group]:
        raise NotImplementedError

    @property
    def browsing(self) -> bool:
        return not self.parsed_query.search_terms

    def _has(self, *words: str) -> bool:
        ks = {k.lower() for k in self.parsed_query.keywords}
        for w in words:
            if any(w in k or k in w for k in ks):
                return True
        return False

    @property
    def is_text_search(self) -> bool:
        # True only if a search term is a real word (name/item), not a bare
        # id or a document code like CV-2026-0009. Drives whether a query
        # should fan out across all document types or stay on the hinted one.
        for term in self.parsed_query.search_terms:
            if re.fullmatch(r"\d+", term):
                continue
            if "-" in term or "/" in term:
                continue
            return True
        return False

    def _make_group(
        self,
        label: str,
        qs,
        row_map: Callable[[Any], dict[str, Any]],
        *,
        search_fields: list[str] | None = None,
        date_field: str | None = None,
        status_field: str | None = None,
        status_map: dict[str, Any] | None = None,
        amount_field: str | None = None,
        order: tuple[str, ...] | None = None,
    ) -> Group:
        terms = self.parsed_query.search_terms
        if search_fields and terms:
            q = Q()
            for term in terms:
                for field in search_fields:
                    q |= Q(**{f"{field}__icontains": term})
            qs = qs.filter(q)

        if date_field and (self.parsed_query.date_from or self.parsed_query.date_to):
            if self.parsed_query.date_from:
                qs = qs.filter(**{f"{date_field}__gte": self.parsed_query.date_from})
            if self.parsed_query.date_to:
                qs = qs.filter(**{f"{date_field}__lte": self.parsed_query.date_to})

        if status_field and self.parsed_query.status:
            token = self.parsed_query.status
            mapping = status_map or {}
            value = mapping.get(token, token)
            if value is not None:
                if isinstance(value, (list, tuple)):
                    qs = qs.filter(**{f"{status_field}__in": list(value)})
                else:
                    qs = qs.filter(**{status_field: value})

        count = qs.count()
        limit = self.parsed_query.top_n or 10

        wants_rank = bool(self.parsed_query.top_n or self.parsed_query.sort_amount)
        if wants_rank and amount_field:
            qs = qs.order_by(f"-{amount_field}")
        elif order:
            qs = qs.order_by(*order)

        items = [row_map(obj) for obj in qs[:limit]]
        return Group(module=self.module_name, label=label, count=count, items=items)
