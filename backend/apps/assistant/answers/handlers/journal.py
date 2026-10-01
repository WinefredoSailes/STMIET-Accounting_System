"""Journal-entry computed answers — H (JE lookups) + G61/B23 hooks.

A question names a document (JE no., RFP no., CV no., PO no.); the matching
posted entry is located via the document's own ``journal_entry`` FK, or by the
entry number / source-document number on the entry itself.
"""

from __future__ import annotations

from apps.posting.models import JournalEntry

from ..base import Answer, metric, money_metric


def _user_name(u):
    if u is None:
        return "—"
    name = getattr(u, "get_full_name", lambda: "")()
    return name or u.username


def _resolve_je(ctx, e) -> JournalEntry | None:
    if e.je is not None:
        return e.je
    if e.rfp is not None:
        return e.rfp.journal_entry
    if e.cv is not None:
        return e.cv.journal_entry
    if e.po is not None:
        rfp = e.po.rfps.filter(status="posted").select_related("journal_entry").first()
        return rfp.journal_entry if rfp else None
    if e.advance is not None and e.advance.rfp is not None:
        return e.advance.rfp.journal_entry
    return None


def _fallback_by_source(ctx, doc_no: str) -> JournalEntry | None:
    return (
        JournalEntry.objects.filter(source_doc_no__icontains=doc_no, status="posted")
        .order_by("-transaction_date")
        .first()
    )


def lookup(ctx, e) -> Answer:
    je = _resolve_je(ctx, e)
    if je is None:
        code = next((t for t in ctx.terms if t), "") or ctx.lower[:40]
        if code:
            je = _fallback_by_source(ctx, code)
    if je is None:
        return Answer(qid="H65", title="Journal entry", summary="No posted journal entry found for this document.", module="posting")
    je.refresh_from_db()
    return Answer(
        qid="H65",
        title="Journal entry",
        summary=(
            f"{je.entry_no} ({je.status}) on {je.transaction_date} — "
            f"{money_metric('x', je.total_debit)['value']} "
            f"({len(je.gl_lines.all())} GL line(s))."
        ),
        metrics=[
            metric("Entry", je.entry_no, "text"),
            metric("Date", je.transaction_date.isoformat(), "date"),
            metric("Status", je.status, "text"),
            money_metric("Total", je.total_debit),
        ],
        note=je.description[:200],
        links=[{"url": f"/journal/{je.pk}/", "label": f"Open {je.entry_no}"}],
        module="posting",
    )


def _lines(ctx, e, side: str):
    je = _resolve_je(ctx, e)
    if je is None:
        return None, []
    qs = je.lines.all()
    if side == "debit":
        out = [ln for ln in qs if ln.debit > 0]
    else:
        out = [ln for ln in qs if ln.credit > 0]
    return je, out


def debits(ctx, e) -> Answer:
    je, lines = _lines(ctx, e, "debit")
    if je is None:
        return Answer(qid="H66", title="Debited accounts", summary="No posted journal entry found for this document.", module="posting")
    total = sum(ln.debit for ln in lines)
    return Answer(
        qid="H66",
        title="Debited accounts",
        summary=f"{je.entry_no} debits {len(lines)} account(s), {money_metric('x', total)['value']} total.",
        metrics=[money_metric("Total debits", total), metric("Accounts", len(lines), "count")],
        rows=[
            {"Account": f"{ln.account.code} {ln.account.name}", "Description": (ln.description or "")[:50], "Amount": f"₱{ln.debit:,.2f}"}
            for ln in lines[:10]
        ],
        module="posting",
    )


def credits(ctx, e) -> Answer:
    je, lines = _lines(ctx, e, "credit")
    if je is None:
        return Answer(qid="H67", title="Credited accounts", summary="No posted journal entry found for this document.", module="posting")
    total = sum(ln.credit for ln in lines)
    return Answer(
        qid="H67",
        title="Credited accounts",
        summary=f"{je.entry_no} credits {len(lines)} account(s), {money_metric('x', total)['value']} total.",
        metrics=[money_metric("Total credits", total), metric("Accounts", len(lines), "count")],
        rows=[
            {"Account": f"{ln.account.code} {ln.account.name}", "Description": (ln.description or "")[:50], "Amount": f"₱{ln.credit:,.2f}"}
            for ln in lines[:10]
        ],
        module="posting",
    )


def reference(ctx, e) -> Answer:
    je = _resolve_je(ctx, e)
    if je is None:
        return Answer(qid="H68", title="Journal reference", summary="No posted journal entry found for this document.", module="posting")
    ref = je.ref_number or je.source_doc_no or "—"
    return Answer(
        qid="H68",
        title="Journal reference",
        summary=f"Reference of {je.entry_no}: {ref}.",
        metrics=[
            metric("Reference", ref, "text"),
            metric("Source doc", je.source_doc_no or "—", "text"),
            metric("PO", je.po or "—", "text"),
        ],
        links=[{"url": f"/journal/{je.pk}/", "label": f"Open {je.entry_no}"}],
        module="posting",
    )


def preparer(ctx, e) -> Answer:
    je = _resolve_je(ctx, e)
    if je is None:
        return Answer(qid="H69", title="Prepared by", summary="No posted journal entry found for this document.", module="posting")
    return Answer(
        qid="H69",
        title="Prepared by",
        summary=f"{je.entry_no} was prepared by {_user_name(je.created_by)}.",
        metrics=[metric("Prepared by", _user_name(je.created_by), "person"), metric("Entry", je.entry_no, "text")],
        module="posting",
    )


def approver(ctx, e) -> Answer:
    je = _resolve_je(ctx, e)
    if je is None:
        return Answer(qid="H70", title="Approved by", summary="No posted journal entry found for this document.", module="posting")
    return Answer(
        qid="H70",
        title="Approved by",
        summary=(
            f"{je.entry_no} was approved by {_user_name(je.approved_by)}."
            if je.approved_by else f"{je.entry_no} has not been approved yet (status: {je.status})."
        ),
        metrics=[metric("Entry", je.entry_no, "text"), metric("Status", je.status, "text")],
        module="posting",
    )


def supporting_doc(ctx, e) -> Answer:
    je = _resolve_je(ctx, e)
    if je is None:
        return Answer(qid="H71", title="Supporting document", summary="No posted journal entry found for this document.", module="posting")
    if je.source_file:
        return Answer(
            qid="H71",
            title="Supporting document",
            summary=f"Source file recorded on {je.entry_no}: {je.source_file}.",
            metrics=[metric("Source file", je.source_file, "text")],
            module="posting",
        )
    return Answer(
        qid="H71",
        title="Supporting document",
        summary=f"{je.entry_no} has no source file attached yet.",
        note="Attachment capture is part of the upcoming enhancement phase.",
        module="posting",
    )