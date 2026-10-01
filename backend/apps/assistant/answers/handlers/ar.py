"""AR computed answers — D (receivables)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.ar.models import AcknowledgmentReceipt, ARInvoice

from ..base import Answer, metric, money_metric


def _open_invoices(as_of: date | None = None, customer=None):
    qs = ARInvoice.objects.filter(status__in=("open", "partially_paid")).select_related("customer", "segment").order_by("transaction_date")
    if customer is not None:
        qs = qs.filter(customer=customer)
    out = []
    for inv in qs:
        balance = inv.balance
        if balance <= 0:
            continue
        if as_of is not None and inv.transaction_date > as_of:
            continue
        out.append(
            {
                "pk": inv.id,
                "invoice_no": inv.invoice_no,
                "customer": inv.customer.name,
                "customer_id": inv.customer_id,
                "date": inv.transaction_date,
                "balance": balance,
                "age_days": (as_of - inv.transaction_date).days if as_of else None,
            }
        )
    return out


def _customer_balance(customer) -> Decimal:
    return sum(r["balance"] for r in _open_invoices(customer=customer))


def customer_balance(ctx, e) -> Answer:
    c = e.customer
    balance = _customer_balance(c)
    open_count = sum(1 for r in _open_invoices(customer=c) if r["balance"] > 0)
    return Answer(
        qid="D31",
        title="Customer balance",
        summary=(
            f"{c.name} owes us {money_metric('x', balance)['value']} "
            f"across {open_count} open invoice(s)."
        ),
        metrics=[money_metric("Receivable balance", balance), metric("Open invoices", open_count, "count")],
        rows=[{"Invoice": r["invoice_no"], "Date": r["date"].isoformat(), "Balance": f"₱{r['balance']:,.2f}"} for r in _open_invoices(customer=c)[:5]],
        links=[{"url": f"/ui/ar/customers/{c.pk}/", "label": f"View {c.name}"}],
        module="ar",
    )


def unpaid_invoices(ctx, e) -> Answer:
    rows_all = _open_invoices(as_of=None)
    if e.customer is not None:
        rows_all = [r for r in rows_all if r["customer_id"] == e.customer.pk]
    total = sum(r["balance"] for r in rows_all)
    who = f" for {e.customer.name}" if e.customer else ""
    if not rows_all:
        return Answer(
            qid="D32",
            title="Unpaid invoices",
            summary=f"No unpaid invoices{who}.",
            metrics=[money_metric("Total outstanding", Decimal("0.00"))],
            module="ar",
        )
    return Answer(
        qid="D32",
        title="Unpaid invoices",
        summary=f"{len(rows_all)} unpaid invoice(s){who} totaling {money_metric('x', total)['value']}.",
        metrics=[money_metric("Total outstanding", total)],
        rows=[
            {"Invoice": r["invoice_no"], "Customer": r["customer"], "Date": r["date"].isoformat(), "Balance": f"₱{r['balance']:,.2f}"}
            for r in rows_all[:10]
        ],
        links=[{"url": "/ui/ar/aging/", "label": "AR Aging register"}],
        module="ar",
    )


def _receipts(customer):
    return (
        AcknowledgmentReceipt.objects.filter(customer=customer, journal_entry__isnull=False)
        .select_related("segment")
        .order_by("-transaction_date")
    )


def last_payment(ctx, e) -> Answer:
    receipt = _receipts(e.customer).first()
    if not receipt:
        return Answer(
            qid="D33",
            title="Last payment",
            summary=f"No posted payment found for {e.customer.name}.",
            metrics=[metric("Last payment", "—", "text")],
            module="ar",
        )
    return Answer(
        qid="D33",
        title="Last payment",
        summary=(
            f"Last payment from {e.customer.name} was {receipt.receipt_no} on "
            f"{receipt.transaction_date} for {money_metric('x', receipt.amount)['value']}."
        ),
        metrics=[
            metric("Date", receipt.transaction_date.isoformat(), "date"),
            money_metric("Amount", receipt.amount),
            metric("Receipt", receipt.receipt_no, "text"),
        ],
        links=[{"url": f"/ui/ar/receipts/{receipt.pk}/", "label": f"View {receipt.receipt_no}"}],
        module="ar",
    )


def customer_payments(ctx, e) -> Answer:
    receipts = list(_receipts(e.customer)[:10])
    if not receipts:
        return Answer(
            qid="D34",
            title="Customer payments",
            summary=f"No posted payments found from {e.customer.name}.",
            metrics=[money_metric("Total collected", Decimal("0.00"))],
            module="ar",
        )
    total = sum(r.amount for r in receipts)
    return Answer(
        qid="D34",
        title="Customer payments",
        summary=f"{len(receipts)} posting(s) from {e.customer.name} totaling {money_metric('x', total)['value']}.",
        metrics=[money_metric("Total collected (shown)", total)],
        rows=[
            {"Receipt": r.receipt_no, "Date": r.transaction_date.isoformat(), "Method": r.get_payment_method_display(), "Amount": f"₱{r.amount:,.2f}"}
            for r in receipts
        ],
        links=[{"url": f"/ui/ar/customers/{e.customer.pk}/", "label": f"View {e.customer.name}"}],
        module="ar",
    )


def overdue(ctx, e) -> Answer:
    from apps.ui.services import aging_context

    data = aging_context(date.today())
    rows = [
        {"Invoice": r["invoice_no"], "Customer": r["customer"], "Age (days)": r["age_days"], "Balance": f"₱{r['balance']:,.2f}"}
        for r in data["register"]
        if r["age_days"] is not None and r["age_days"] > 30
    ]
    if e.customer is not None:
        rows = [r for r in rows if r["Customer"] == e.customer.name]
    total = data["bucket_total"] or Decimal("0.00")
    if not rows:
        return Answer(
            qid="D35",
            title="Overdue receivables",
            summary="No overdue receivables.",
            metrics=[money_metric("Overdue total", Decimal("0.00"))],
            module="ar",
        )
    return Answer(
        qid="D35",
        title="Overdue receivables",
        summary=f"{len(rows)} receivable(s) over 30 days.",
        metrics=[money_metric("Overdue total", total)],
        rows=rows[:10],
        links=[{"url": "/ui/ar/aging/", "label": "AR Aging register"}],
        module="ar",
    )


def customer_aging(ctx, e) -> Answer:
    from apps.ui.services import customer_aging_context

    data = customer_aging_context(e.customer, date.today())
    buckets = data["buckets"]
    total = sum(b["amount"] for b in buckets.values()) if isinstance(buckets, dict) else (data.get("bucket_total") or Decimal("0.00"))
    bucket_rows = []
    if isinstance(buckets, dict):
        bucket_rows = [{"Bucket": k, "Amount": f"₱{v:,.2f}"} for k, v in buckets.items()]
    return Answer(
        qid="D36",
        title="Customer aging",
        summary=f"{e.customer.name}: {money_metric('x', total)['value']} outstanding across aging buckets.",
        metrics=[
            money_metric("Total", total),
            money_metric("0-30", _bucket(buckets, "0-30")),
            money_metric("31-60", _bucket(buckets, "31-60")),
            money_metric("61-90", _bucket(buckets, "61-90")),
            money_metric("120+", _bucket(buckets, "120+")),
        ],
        rows=bucket_rows,
        module="ar",
    )


def _bucket(buckets, key) -> Decimal:
    if isinstance(buckets, dict):
        return buckets.get(key, Decimal("0.00"))
    for b in buckets:
        if b["bucket"] == key:
            return b["amount"]
    return Decimal("0.00")


def customer_ledger(ctx, e) -> Answer:
    from apps.ar.services import CycleLedgerService

    rows = CycleLedgerService.for_customer(e.customer)
    if not rows:
        return Answer(
            qid="D37",
            title="Customer ledger",
            summary=f"No activity found for {e.customer.name}.",
            rows=[],
            module="ar",
        )
    return Answer(
        qid="D37",
        title="Customer ledger",
        summary=f"Per-cycle over/(short) ledger for {e.customer.name}.",
        rows=[
            {
                "Cycle start": r["cycle_start"].isoformat(),
                "Paid": f"₱{r['paid']:,.2f}",
                "Billed": f"₱{r['billed']:,.2f}",
                "Over/(Short)": f"₱{r['over_short']:,.2f}",
                "Cumulative": f"₱{r['cumulative']:,.2f}",
            }
            for r in rows[-10:]
        ],
        links=[{"url": f"/ui/ar/customers/{e.customer.pk}/", "label": f"View {e.customer.name}"}],
        module="ar",
    )