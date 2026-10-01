"""General-ledger (account) computed answers — E (account inquiry).

Read-only over the posted GL projection (ADR-005), across every company the
assistant user can see, mirroring TrialBalanceService semantics:
balance = SUM(debit) - SUM(credit), positive toward the account's normal side.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum

from apps.posting.models import GL_EFFECTIVE_STATUSES, GeneralLedger

from ..base import Answer, metric, money_metric


def _account_gl(account, companies, start=None, end=None):
    qs = GeneralLedger.objects.filter(
        account=account,
        entry__status__in=GL_EFFECTIVE_STATUSES,
        entry__company__in=companies,
    )
    if start:
        qs = qs.filter(transaction_date__gte=start)
    if end:
        qs = qs.filter(transaction_date__lte=end)
    return qs


def _round(v) -> Decimal:
    return Decimal(v or "0.00")


def _signed(account, debit, credit) -> Decimal:
    debit = _round(debit)
    credit = _round(credit)
    if (account.normal_balance or "debit") == "credit":
        return credit - debit
    return debit - credit


def _balance(account, companies, start=None, end=None) -> Decimal:
    agg = _account_gl(account, companies, start=start, end=end).aggregate(
        debit=Sum("debit"), credit=Sum("credit")
    )
    return _signed(account, agg["debit"], agg["credit"])


def _windows(ctx):
    """(start, end) report window: explicit period else latest activity."""
    period = ctx.entities.period
    return (period.start, period.end) if period else (None, None)


def balance(ctx, e) -> Answer:
    acc = e.account
    as_of = e.as_of
    bal = _balance(acc, ctx.companies, end=as_of)
    note = ""
    if as_of:
        note = f"Balance as of {as_of.isoformat()}."
    return Answer(
        qid="E38",
        title="Account balance",
        summary=f"{acc.code} {acc.name}: {money_metric('x', bal)['value']}.",
        metrics=[money_metric("Balance", bal), metric("Account", f"{acc.code} — {acc.name}", "text")],
        note=note,
        links=[{"url": f"/ui/reports/ledger/{acc.pk}/", "label": "Open the account register"}],
        module="posting",
    )


def balance_as_of(ctx, e) -> Answer:
    acc = e.account
    as_of = e.as_of
    if not as_of:
        return balance(ctx, e)
    bal = _balance(acc, ctx.companies, end=as_of)
    return Answer(
        qid="E39",
        title="Balance as of",
        summary=f"{acc.code} {acc.name} was {money_metric('x', bal)['value']} as of {as_of.isoformat()}.",
        metrics=[money_metric("Balance", bal), metric("As of", as_of.isoformat(), "date")],
        module="posting",
    )


def _movement(ctx, account, start, end) -> tuple[Decimal, list, list]:
    rows = list(
        _account_gl(account, ctx.companies, start=start, end=end)
        .select_related("entry")
        .order_by("transaction_date", "id")
    )
    net = _signed(
        account,
        sum((r.debit for r in rows), Decimal("0.00")),
        sum((r.credit for r in rows), Decimal("0.00")),
    )
    by_type: dict = {}
    for r in rows:
        key = r.entry.source_doc_type or r.entry.entry_no or "Other"
        bucket = by_type.setdefault(key, {"count": 0, "t1": r.entry.transaction_date, "t2": r.entry.transaction_date, "entry_no": r.entry.entry_no})
        bucket["count"] += 1
        bucket["t1"] = min(bucket["t1"], r.entry.transaction_date)
        bucket["t2"] = max(bucket["t2"], r.entry.transaction_date)
        bucket["net"] = bucket.get("net", Decimal("0.00")) + _signed(account, r.debit, r.credit)
    summary_rows = sorted(by_type.items(), key=lambda kv: -abs(kv[1].get("net", Decimal("0.00"))))[:6]
    return net, rows, [
        {
            "Source": k,
            "Entries": v["count"],
            "From": v["t1"].isoformat(),
            "To": v["t2"].isoformat(),
            "Net": f"₱{v.get('net', Decimal('0.00')):,.2f}",
        }
        for k, v in summary_rows
    ]


def movement_reason(ctx, e) -> Answer:
    acc = e.account
    start, end = _windows(ctx)
    net, rows, summary = _movement(ctx, acc, start, end)
    period_label = ctx.entities.period.label() if ctx.entities.period else "all time"
    direction = "increased" if net > 0 else ("decreased" if net < 0 else "held flat")
    period_note = ctx.entities.period_note
    return Answer(
        qid="E40",
        title="Why the balance moved",
        summary=(
            f"{acc.code} {acc.name} {direction} by {money_metric('x', abs(net))['value']} "
            f"({len(rows)} posted line(s) in {period_label})."
        ),
        metrics=[
            money_metric("Net movement", net),
            metric("Posted lines", len(rows), "count"),
        ],
        rows=summary,
        note=period_note,
        module="posting",
    )


def composition(ctx, e) -> Answer:
    acc = e.account
    start, end = _windows(ctx)
    rows = list(
        _account_gl(acc, ctx.companies, start=start, end=end)
        .select_related("entry", "line")
        .order_by("-transaction_date", "-id")[:12]
    )
    bal = _balance(acc, ctx.companies)
    return Answer(
        qid="E42",
        title="Balance composition",
        summary=f"Latest transactions making up {acc.code} {acc.name} (current {money_metric('x', bal)['value']}).",
        rows=[
            {
                "Date": r.transaction_date.isoformat(),
                "Entry": r.entry.entry_no,
                "Description": (r.line.description or r.entry.description)[:60],
                "Amount": f"₱{_signed(acc, r.debit, r.credit):,.2f}",
            }
            for r in rows
        ],
        module="posting",
    )


def debit_credit(ctx, e) -> Answer:
    acc = e.account
    start, end = _windows(ctx)
    agg = _account_gl(acc, ctx.companies, start=start, end=end).aggregate(
        debit=Sum("debit"), credit=Sum("credit")
    )
    debit_total = _round(agg["debit"])
    credit_total = _round(agg["credit"])
    count = _account_gl(acc, ctx.companies, start=start, end=end).count()
    net = _signed(acc, debit_total, credit_total)
    return Answer(
        qid="E43",
        title="Debit / credit movements",
        summary=(
            f"{acc.code} {acc.name}: {money_metric('x', debit_total)['value']} debits, "
            f"{money_metric('x', credit_total)['value']} credits, net {money_metric('x', net)['value']} "
            f"across {count} posted line(s)."
        ),
        metrics=[
            money_metric("Debits", debit_total),
            money_metric("Credits", credit_total),
            money_metric("Net", net),
            metric("Lines", count, "count"),
        ],
        module="posting",
    )


def beginning_balance(ctx, e) -> Answer:
    acc = e.account
    start, end = _windows(ctx)
    if not start:
        return Answer(
            qid="E44",
            title="Beginning balance",
            summary="No explicit period given; there is no cut-off for an opening balance.",
            module="posting",
        )
    opening = _balance(acc, ctx.companies, end=start - timedelta(days=1))
    return Answer(
        qid="E44",
        title="Beginning balance",
        summary=f"Opening balance of {acc.code} {acc.name} at {start.isoformat()}: {money_metric('x', opening)['value']}.",
        metrics=[money_metric("Opening balance", opening), metric("Period", ctx.entities.period.label(), "text")],
        module="posting",
    )


def ending_balance(ctx, e) -> Answer:
    acc = e.account
    start, end = _windows(ctx)
    closing = _balance(acc, ctx.companies, end=end)
    label = ctx.entities.period.label() if ctx.entities.period else "all time"
    return Answer(
        qid="E45",
        title="Ending balance",
        summary=f"Ending balance of {acc.code} {acc.name} for {label}: {money_metric('x', closing)['value']}.",
        metrics=[money_metric("Ending balance", closing), metric("Period", label, "text")],
        module="posting",
    )