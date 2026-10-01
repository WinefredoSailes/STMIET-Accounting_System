"""AP computed answers — C (payables) + A5/A14 (payments)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.core.money import money
from apps.posting.models import PostingStatus

from ..base import Answer, metric, money_metric


def _cleared_map():
    from apps.ap.models import CheckVoucher

    cleared = {
        row["rfp_id"]: row["paid"] or Decimal("0.00")
        for row in (
            CheckVoucher.objects.filter(journal_entry__status=PostingStatus.POSTED)
            .exclude(rfp__isnull=True)
            .values("rfp_id")
            .annotate(paid=Sum("gross_amount"))
        )
    }
    return cleared


def _open_payables(as_of: date | None = None):
    """Posted-RFP open payables: true payable minus cleared CV gross."""
    from apps.ap.models import RFPDocument
    from apps.ap.services import rfp_payable

    cleared = _cleared_map()
    out = []
    for rfp in (
        RFPDocument.objects.filter(status="posted")
        .exclude(journal_entry__status=PostingStatus.REVERSED)
        .select_related("payee", "segment")
        .order_by("rfp_date")
    ):
        balance = rfp_payable(rfp) - cleared.get(rfp.id, Decimal("0.00"))
        if balance <= 0:
            continue
        out.append(
            {
                "pk": rfp.id,
                "ap_number": rfp.ap_number,
                "payee": rfp.payee.name,
                "payee_id": rfp.payee_id,
                "date": rfp.rfp_date,
                "amount": rfp_payable(rfp),
                "balance": balance,
                "age_days": (as_of - rfp.rfp_date).days if as_of else None,
            }
        )
    return out


def _supplier_billed_paid(supplier) -> tuple[Decimal, Decimal]:
    """Total billed (posted RFPs, AP credit lines) and paid (cleared CVs)."""
    from apps.ap.models import CheckVoucher, RFPDocument

    billed = Decimal("0.00")
    for rfp in (
        RFPDocument.objects.filter(status="posted", payee=supplier)
        .exclude(journal_entry__status=PostingStatus.REVERSED)
        .prefetch_related("lines")
    ):
        for line in rfp.lines.all():
            if line.side == "cr" and line.account.code in ("20000", "21100"):
                billed += line.amount
    paid = (
        CheckVoucher.objects.filter(
            payee=supplier, journal_entry__status=PostingStatus.POSTED
        ).aggregate(total=Sum("gross_amount"))["total"]
        or Decimal("0.00")
    )
    return money(billed), money(paid)


def supplier_balance(ctx, e) -> Answer:
    s = e.supplier
    billed, paid = _supplier_billed_paid(s)
    outstanding = max(billed - paid, Decimal("0.00"))
    advance = max(paid - billed, Decimal("0.00"))
    return Answer(
        qid="C25",
        title="Supplier balance",
        summary=(
            f"You currently owe {s.name} {money_metric('x', outstanding)['value']} "
            f"(billed {money_metric('x', billed)['value']}, paid {money_metric('x', paid)['value']})."
        ),
        metrics=[
            money_metric("Total billed", billed),
            money_metric("Total paid", paid),
            money_metric("Outstanding", outstanding),
        ],
        links=[{"url": f"/ui/ap/suppliers/{s.pk}/", "label": f"View {s.name}"}],
        module="ap",
    )


def open_payables(ctx, e) -> Answer:
    today = date.today()
    open_rows = _open_payables(today)
    if e.supplier is not None:
        open_rows = [r for r in open_rows if r["payee_id"] == e.supplier.pk]
    rows = [
        {
            "RFP": r["ap_number"],
            "Payee": r["payee"],
            "Date": r["date"].isoformat(),
            "Age (days)": r["age_days"] or "—",
            "Balance": f"₱{r['balance']:,.2f}",
        }
        for r in open_rows
    ]
    total = sum(r["balance"] for r in open_rows)
    who = f" for {e.supplier.name}" if e.supplier else ""
    if not rows:
        return Answer(
            qid="C26",
            title="Unpaid invoices",
            summary=f"No unpaid invoices{who}.",
            metrics=[money_metric("Total outstanding", Decimal("0.00"))],
            module="ap",
        )
    return Answer(
        qid="C26",
        title="Unpaid invoices",
        summary=f"Found {len(rows)} unpaid invoice(s){who} totaling {money_metric('x', total)['value']}.",
        metrics=[money_metric("Total outstanding", total)],
        rows=rows[:10],
        links=[{"url": "/ui/ap/aging/", "label": "AP Aging register"}],
        module="ap",
    )


def company_aging(ctx, e) -> Answer:
    from apps.ui.services import ap_aging_context

    data = ap_aging_context(date.today())
    register = data["register"]
    if e.supplier is not None:
        register = [r for r in register if r["payee"] == e.supplier.name]
        buckets = {"0-30": Decimal("0.00"), "31-60": Decimal("0.00"), "61-90": Decimal("0.00"), "91-120": Decimal("0.00"), "120+": Decimal("0.00")}
        for r in register:
            age = r.get("age_days")
            key = (
                "0-30" if age and age <= 30
                else "31-60" if age and age <= 60
                else "61-90" if age and age <= 90
                else "91-120" if age and age <= 120
                else "120+"
            )
            buckets[key] += r["balance"]
    else:
        buckets = {b["bucket"]: b["amount"] for b in data["buckets"]}
    overdue_total = sum(
        v for k, v in buckets.items() if k in ("31-60", "61-90", "91-120", "120+")
    )
    rows = [
        {
            "RFP": r["ap_number"],
            "Payee": r["payee"],
            "Date": r["date"].isoformat(),
            "Age (days)": r["age_days"] or "—",
            "Balance": f"₱{r['balance']:,.2f}",
        }
        for r in register
        if r.get("age_days") and r["age_days"] > 30
    ]
    who = f" for {e.supplier.name}" if e.supplier else ""
    return Answer(
        qid="C27",
        title="Overdue payables",
        summary=f"{len(rows)} overdue payable(s){who} totaling {money_metric('x', overdue_total)['value']}.",
        metrics=[
            money_metric("Overdue (>30d)", overdue_total),
            money_metric("0-30 days", buckets.get("0-30", Decimal("0.00"))),
            money_metric("31-60", buckets.get("31-60", Decimal("0.00"))),
            money_metric("61-90", buckets.get("61-90", Decimal("0.00"))),
            money_metric("120+", buckets.get("120+", Decimal("0.00"))),
        ],
        rows=rows[:10],
        links=[{"url": "/ui/ap/aging/", "label": "AP Aging register"}],
        module="ap",
    )


def supplier_payments(ctx, e) -> Answer:
    from apps.ap.models import CheckVoucher

    rows = list(
        CheckVoucher.objects.filter(
            payee=e.supplier, journal_entry__status=PostingStatus.POSTED
        )
        .select_related("rfp")
        .order_by("-cv_date")[:10]
    )
    if not rows:
        return Answer(
            qid="C28",
            title="Supplier payments",
            summary=f"No cleared payments found for {e.supplier.name}.",
            metrics=[money_metric("Total paid", Decimal("0.00"))],
            links=[{"url": f"/ui/ap/suppliers/{e.supplier.pk}/", "label": f"View {e.supplier.name}"}],
            module="ap",
        )
    total = sum(r.gross_amount for r in rows)
    answer = Answer(
        qid="C28",
        title="Supplier payments",
        summary=f"{len(rows)} cleared payment(s) to {e.supplier.name} totaling {money_metric('x', total)['value']}.",
        metrics=[money_metric("Total paid (shown)", total)],
        rows=[
            {
                "CV": r.cv_number,
                "Check": r.check_no or "—",
                "Date": r.cv_date.isoformat(),
                "RFP": r.rfp.ap_number if r.rfp else "—",
                "Amount": f"₱{r.gross_amount:,.2f}",
            }
            for r in rows
        ],
        links=[{"url": f"/ui/ap/suppliers/{e.supplier.pk}/", "label": f"View {e.supplier.name}"}],
        module="ap",
    )
    if "when did we pay" in ctx.lower or "when was the supplier paid" in ctx.lower:
        answer.qid = "A5"
        answer.title = "Last payment date"
        answer.summary = (
            f"Latest payment to {e.supplier.name} was on {rows[0].cv_date.isoformat()} "
            f"({money_metric('x', rows[0].gross_amount)['value']} via {rows[0].cv_number})."
        )
        answer.metrics = [metric("Last payment", rows[0].cv_date.isoformat(), "date")]
    return answer


def supplier_ledger(ctx, e) -> Answer:
    from apps.ui.services import ap_supplier_ledger

    data = ap_supplier_ledger(supplier=e.supplier)
    rows_data = data.get("rows", [])
    rows = [
        {
            "Date": r.get("date", ""),
            "Ref": r.get("ref", r.get("ref_no", "")),
            "Type": r.get("type", ""),
            "Description": r.get("description", r.get("particulars", "")),
            "Debit": f"₱{r.get('debit', 0):,.2f}",
            "Credit": f"₱{r.get('credit', 0):,.2f}",
            "Balance": f"₱{r.get('balance', 0):,.2f}",
        }
        for r in rows_data[:10]
    ]
    return Answer(
        qid="C29",
        title="Supplier ledger",
        summary=f"{len(rows_data)} ledger row(s) for {e.supplier.name}.",
        metrics=[metric("Rows", len(rows_data), "count")],
        rows=rows,
        links=[{"url": f"/ui/ap/suppliers/{e.supplier.pk}/", "label": f"View {e.supplier.name}"}],
        module="ap",
    )


def supplier_aging(ctx, e) -> Answer:
    from apps.ui.services import ap_aging_context

    data = ap_aging_context(date.today())
    buckets = {"0-30": Decimal("0.00"), "31-60": Decimal("0.00"), "61-90": Decimal("0.00"), "91-120": Decimal("0.00"), "120+": Decimal("0.00")}
    for r in data["register"]:
        if r["payee"] != e.supplier.name:
            continue
        age = r.get("age_days")
        key = (
            "0-30" if age and age <= 30
            else "31-60" if age and age <= 60
            else "61-90" if age and age <= 90
            else "91-120" if age and age <= 120
            else "120+"
        )
        buckets[key] += r["balance"]
    total = sum(buckets.values())
    return Answer(
        qid="C30",
        title="Supplier aging",
        summary=(
            f"{e.supplier.name}: {money_metric('x', total)['value']} outstanding "
            f"- 0-30d {money_metric('x', buckets['0-30'])['value']}, "
            f"31-60d {money_metric('x', buckets['31-60'])['value']}, "
            f"61-90d {money_metric('x', buckets['61-90'])['value']}, "
            f"120+ {money_metric('x', buckets['120+'])['value']}."
        ),
        metrics=[
            money_metric("Total", total),
            money_metric("0-30", buckets["0-30"]),
            money_metric("31-60", buckets["31-60"]),
            money_metric("61-90", buckets["61-90"]),
            money_metric("120+", buckets["120+"]),
        ],
        module="ap",
    )