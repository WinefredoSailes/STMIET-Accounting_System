"""Computed-answer primitives for the Smart Search Assistant.

An *answer* is a deterministic, read-only aggregate built from the same
services the UI uses (so figures always match the screens). It ships inside
the chat response as ``answer_block``; the widget renders it as an answer card
with optional metric badges, a mini table, source links and a footnote.

The record-search pipeline is untouched: the dispatcher returns ``None`` when
no catalog question matches, and the assistant falls back to the executor
search exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


def fmt_money(value) -> str:
    """Render a Decimal as a peso string: ``-₱1,234.56``."""
    if value is None or value == "":
        return ""
    d = Decimal(value)
    sign = "-" if d < 0 else ""
    return f"{sign}₱{abs(d):,.2f}"


def fmt_date(value) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


@dataclass
class Answer:
    """One computed answer to a catalog question.

    Optional parts simply render as nothing, so handlers only fill what they
    have. ``kind`` distinguishes a regular answer from an RBAC denial so the
    formatter can localize the denial message.
    """

    qid: str
    title: str
    summary: str
    metrics: list[dict] | None = None
    rows: list[dict] | None = None
    links: list[dict] | None = None
    note: str = ""
    kind: str = "answer"  # answer | denied
    module: str = ""

    def to_block(self) -> dict:
        return {
            "qid": self.qid,
            "title": self.title,
            "summary": self.summary,
            "metrics": self.metrics or [],
            "rows": self.rows or [],
            "links": self.links or [],
            "note": self.note,
            "kind": self.kind,
            "module": self.module,
        }


def metric(label: str, value, kind: str = "text") -> dict:
    return {"label": label, "value": str(value), "kind": kind}


def money_metric(label: str, value) -> dict:
    return {"label": label, "value": fmt_money(value), "kind": "money"}


def denied(qid: str, module_label: str) -> Answer:
    """An RBAC denial rendered in the user's language by the formatter."""
    return Answer(
        qid=qid,
        title="Access",
        summary=module_label,
        kind="denied",
        module=module_label,
    )


@dataclass
class ResolvedPeriod:
    """A report window. ``is_default`` marks the latest-activity fallback."""

    start: date
    end: date
    is_default: bool = False

    def label(self) -> str:
        return f"{self.start:%B %Y}"

    def previous(self) -> "ResolvedPeriod":
        from datetime import timedelta

        first = self.start.replace(day=1)
        prev_end = first - timedelta(days=1)
        return ResolvedPeriod(prev_end.replace(day=1), prev_end, is_default=False)