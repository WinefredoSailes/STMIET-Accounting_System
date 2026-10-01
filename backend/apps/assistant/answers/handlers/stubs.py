"""Stub-aware answers — needs-stub questions (B18/B19/B24/G62/H71).

These document references (Receiving Report, Delivery Receipt, Supplier
Invoice, supporting files) are not captured in the data model yet. Instead of
a dead-end search, the assistant answers honestly that the reference is not
tracked and points at what is coming (Phase-3 lightweight capture fields),
keeping the question answerable later without a schema change.
"""

from __future__ import annotations

from ..base import Answer

STUB_MESSAGES = {
    "receiving/delivery report": (
        "Receiving report / delivery receipt references are not captured in the system yet.",
        "We plan to add lightweight RR/DR number fields on Purchase Orders so "
        "this becomes answerable — no workflow change, just a reference for tracing.",
    ),
    "supplier invoice": (
        "Supplier invoice numbers are not captured in the system yet.",
        "A lightweight supplier-invoice reference on the RFP is planned so "
        "payments can be traced to the vendor invoice.",
    ),
    "supporting documents": (
        "Supporting document references are not captured in the system yet.",
        "Attachment capture on purchase and payment documents is planned; "
        "for now, open the document itself and check its attached files.",
    ),
    "journal supporting file": (
        "The journal entry has no captured source file to point at.",
        "When a source file is recorded on the entry it becomes available here.",
    ),
}


def not_tracked(ctx, e) -> Answer:
    entry = ctx.entry
    summary, note = STUB_MESSAGES.get(
        entry.stub_kind, ("This reference is not tracked yet.", "")
    )
    return Answer(
        qid=entry.qid,
        title="Not tracked yet",
        summary=summary,
        note=note,
        module="ap" if entry.category in ("B", "G") else "posting",
    )