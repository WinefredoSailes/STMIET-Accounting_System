"""Advances computed answers — I (employee / officer advances, ADR-021)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.ap.models import AdvanceToEmployee

from ..base import Answer, metric, money_metric

KINDS = ("employee", "officer")


def _qs():
    return AdvanceToEmployee.objects.select_related("rfp").order_by("-granted_date")


def _outstanding_rows(qs=None):
    qs = qs if qs is not None else _qs()
    out = []
    for a in qs:
        if a.outstanding > 0 and a.status == "granted":
            out.append(a)
    return out


def _rows_data(rows):
    return [
        {
            "Name": a.employee_name,
            "Kind": a.kind,
            "Granted": a.granted_date.isoformat(),
            "Amount": f"₱{a.amount:,.2f}",
            "Liquidated": f"₱{a.liquidated_amount:,.2f}",
            "Outstanding": f"₱{a.outstanding:,.2f}",
        }
        for a in rows
    ]


def total(ctx, e) -> Answer:
    rows = _outstanding_rows()
    total_amount = sum(a.outstanding for a in rows)
    by_kind = {}
    for a in rows:
        by_kind[a.kind] = by_kind.get(a.kind, Decimal("0.00")) + a.outstanding
    return Answer(
        qid="I73",
        title="Outstanding advances",
        summary=(
            f"{money_metric('x', total_amount)['value']} outstanding across "
            f"{len(rows)} advance(s)."
        ),
        metrics=[
            money_metric("Total outstanding", total_amount),
            metric("Advances", len(rows), "count"),
            money_metric("Employee", by_kind.get("employee", Decimal("0.00"))),
            money_metric("Officer", by_kind.get("officer", Decimal("0.00"))),
            money_metric("Salary", by_kind.get("salary_advance", Decimal("0.00"))),
        ],
        rows=_rows_data(rows[:8]),
        module="ap",
    )


def outstanding_list(ctx, e) -> Answer:
    rows = _outstanding_rows()
    if e.party_text:
        rows = [a for a in rows if a.employee_name and e.party_text.lower() in a.employee_name.lower()]
    if not rows:
        return Answer(qid="I74", title="Outstanding advances", summary="No outstanding advances found.", metrics=[money_metric("Total", Decimal("0.00"))], module="ap")
    total_amount = sum(a.outstanding for a in rows)
    return Answer(
        qid="I74",
        title="Outstanding advances",
        summary=f"{len(rows)} outstanding advance(s), {money_metric('x', total_amount)['value']} total.",
        metrics=[
            money_metric("Total outstanding", total_amount),
            metric("Parties", len(rows), "count"),
        ],
        rows=_rows_data(rows[:10]),
        module="ap",
    )


def age(ctx, e) -> Answer:
    rows = _outstanding_rows()
    today = date.today()
    if e.party_text:
        rows = [a for a in rows if a.employee_name and e.party_text.lower() in a.employee_name.lower()]
    if not rows:
        return Answer(qid="I75", title="Advance age", summary="No outstanding advances found.", module="ap")
    return Answer(
        qid="I75",
        title="Advance age",
        summary=f"{len(rows)} outstanding advance(s); longest outstanding is {(today - min(a.granted_date for a in rows)).days} days.",
        metrics=[metric("Oldest (days)", f"{(today - min(a.granted_date for a in rows)).days}", "count")],
        rows=[
            {
                "Name": a.employee_name,
                "Granted": a.granted_date.isoformat(),
                "Days": (today - a.granted_date).days,
                "Outstanding": f"₱{a.outstanding:,.2f}",
            }
            for a in rows[:10]
        ],
        module="ap",
    )


def liquidated(ctx, e) -> Answer:
    qs = _qs().exclude(liquidated_amount=Decimal("0.00"))
    if e.party_text:
        qs = qs.filter(employee_name__icontains=e.party_text)
    elif e.advance is not None:
        qs = qs.filter(pk=e.advance.pk)
    rows = list(qs[:10])
    total_liqu = sum(a.liquidated_amount for a in rows)
    if not rows:
        return Answer(qid="I76", title="Liquidation", summary="No liquidated advances found for this party.", module="ap")
    return Answer(
        qid="I76",
        title="Liquidation",
        summary=f"{len(rows)} advance(s) showing {money_metric('x', total_liqu)['value']} liquidated.",
        metrics=[money_metric("Liquidated (shown)", total_liqu)],
        rows=[
            {
                "Name": a.employee_name,
                "Amount": f"₱{a.amount:,.2f}",
                "Liquidated": f"₱{a.liquidated_amount:,.2f}",
                "Date": a.liquidated_date.isoformat() if a.liquidated_date else "—",
                "Status": a.status,
            }
            for a in rows
        ],
        module="ap",
    )


def liquidating_txn(ctx, e) -> Answer:
    qs = _qs().exclude(liquidated_amount=Decimal("0.00"))
    if e.advance is not None:
        qs = qs.filter(pk=e.advance.pk)
    elif e.party_text:
        qs = qs.filter(employee_name__icontains=e.party_text)
    rows = list(qs[:10])
    if not rows:
        return Answer(
            qid="I77",
            title="Liquidating transaction",
            summary="No liquidation record found.", module="ap",
        )
    return Answer(
        qid="I77",
        title="Liquidating transaction",
        summary=f"Liquidation on {rows[0].liquidated_date} ({rows[0].liquidated_amount:.2f}) for {rows[0].employee_name}.",
        metrics=[
            metric("Liquidated", rows[0].liquidated_date.isoformat() if rows[0].liquidated_date else "—", "date"),
            money_metric("Amount", rows[0].liquidated_amount),
        ],
        note="Liquidation clears the standing advance against RFPs for the same party (ADR-021).",
        rows=[{"Name": a.employee_name, "Liquidated": f"₱{a.liquidated_amount:,.2f}", "Date": a.liquidated_date.isoformat() if a.liquidated_date else "—"} for a in rows[:8]],
        module="ap",
    )


def employee_list(ctx, e) -> Answer:
    return _by_kind("employee", "I78")


def officer_list(ctx, e) -> Answer:
    return _by_kind("officer", "I79")


def _by_kind(kind: str, qid: str) -> Answer:
    rows = [a for a in _outstanding_rows() if a.kind == kind]
    total_amount = sum(a.outstanding for a in rows)
    label = "Employees" if kind == "employee" else "Officers"
    if not rows:
        return Answer(qid=qid, title=f"{label} advances", summary=f"No outstanding {kind.lower()} advances.", metrics=[money_metric("Total", Decimal("0.00"))], module="ap")
    return Answer(
        qid=qid,
        title=f"{label} advances",
        summary=f"{len(rows)} outstanding {label.lower()}, {money_metric('x', total_amount)['value']} total.",
        metrics=[money_metric("Total outstanding", total_amount), metric(label, len(rows), "count")],
        rows=_rows_data(rows[:10]),
        module="ap",
    )


def history(ctx, e) -> Answer:
    qs = _qs()
    if e.advance is not None:
        qs = qs.filter(employee_name=e.advance.employee_name)
    elif e.party_text:
        qs = qs.filter(employee_name__icontains=e.party_text)
    rows = list(qs[:15])
    if not rows:
        return Answer(qid="I80", title="Advance history", summary="No advance records found.", module="ap")
    return Answer(
        qid="I80",
        title="Advance history",
        summary=f"{len(rows)} advance record(s) for {rows[0].employee_name}.",
        rows=[
            {
                "Name": a.employee_name,
                "Kind": a.kind,
                "Granted": a.granted_date.isoformat(),
                "Amount": f"₱{a.amount:,.2f}",
                "Liquidated": f"₱{a.liquidated_amount:,.2f}",
                "Status": a.status,
            }
            for a in rows
        ],
        module="ap",
    )