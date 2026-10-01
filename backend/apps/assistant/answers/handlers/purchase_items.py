"""Purchase/item computed answers — A (Phase 2 projection) via the read model.

Every answer is derived from PO lines + cleared CV payments (read-only) and
carries a note that item identity is free-text and payment attribution is
pro-rata by line share (approved method).
"""

from __future__ import annotations

from decimal import Decimal

from ..base import Answer, metric, money_metric
from .. import purchase_projection as proj

NOTE = "Matches purchase lines by item description; payment amounts are pro-rata estimates."


def _qid(ctx) -> str:
    return getattr(ctx.entry, "qid", "A1")


def item_suppliers(ctx, e) -> Answer:
    rows = proj.item_suppliers(e.item_text)
    if not rows:
        return Answer(qid=_qid(ctx), title="Item suppliers", summary=f"No purchases found matching \"{e.item_text}\".", module="ap")
    qid = _qid(ctx)
    if qid in ("A1", "A2", "J83"):
        main = rows[0]
        summary = (
            f"\"{e.item_text}\" has been purchased from {len(rows)} supplier(s); "
            f"{main['supplier']} supplied the most ({money_metric('x', main['amount'])['value']})."
        )
    else:
        summary = f"Suppliers of \"{e.item_text}\" ({len(rows)}):"
    return Answer(
        qid=qid,
        title="Item suppliers",
        summary=summary,
        metrics=[
            metric("Suppliers", len(rows), "count"),
            money_metric("Top supplier spend", rows[0]["amount"]),
        ],
        rows=[
            {"Supplier": r["supplier"], "Lines": r["lines"], "Qty": f"{r['qty']:,.2f}", "Spent": f"₱{r['amount']:,.2f}", "Last": r["last_date"].isoformat() if r["last_date"] else "—"}
            for r in rows[:8]
        ],
        note=NOTE,
        module="ap",
    )


def item_history(ctx, e) -> Answer:
    qid = _qid(ctx)
    rows = proj.item_history(e.item_text)
    if not rows:
        return Answer(qid=qid, title="Item purchase history", summary=f"No purchases found matching \"{e.item_text}\".", module="ap")
    if qid in ("A4", "J84"):
        latest = rows[-1]
        summary = (
            f"\"{e.item_text}\" was purchased {len(rows)} time(s); "
            f"latest on {latest['po_date'].isoformat()} under {latest['po_number']} "
            f"({latest['qty']:,.2f} {latest['unit']} at {money_metric('x', latest['unit_price'])['value']}/unit)."
        )
    else:
        summary = f"{len(rows)} purchase line(s) for \"{e.item_text}\":"
    return Answer(
        qid=qid,
        title="Item purchase history",
        summary=summary,
        metrics=[metric("Purchases", len(rows), "count")],
        rows=[
            {"Date": r["po_date"].isoformat(), "PO": r["po_number"], "Supplier": r["supplier"], "Qty": f"{r['qty']:,.2f} {r['unit']}".strip(), "Unit": f"₱{r['unit_price']:,.2f}", "Amount": f"₱{r['amount']:,.2f}"}
            for r in rows[:10]
        ],
        note=NOTE,
        module="ap",
    )


def item_units(ctx, e) -> Answer:
    t = proj.item_totals(e.item_text)
    if not t["lines"]:
        return Answer(qid="A6", title="Units purchased", summary=f"No purchases found matching \"{e.item_text}\".", module="ap")
    return Answer(
        qid="A6",
        title="Units purchased",
        summary=f"Total purchased quantity of \"{e.item_text}\": {t['total_qty']:,.2f} across {t['po_count']} PO(s) / {t['lines']} line(s).",
        metrics=[
            metric("Total qty", f"{t['total_qty']:,.2f}", "count"),
            metric("POs", t["po_count"], "count"),
        ],
        note=NOTE,
        module="ap",
    )


def item_totals_handler(ctx, e) -> Answer:
    t = proj.item_totals(e.item_text)
    if not t["lines"]:
        return Answer(qid="A8", title="Total purchase cost", summary=f"No purchases found matching \"{e.item_text}\".", module="ap")
    return Answer(
        qid="A8",
        title="Total purchase cost",
        summary=f"Total purchase cost of \"{e.item_text}\": {money_metric('x', t['total_amount'])['value']} ({t['lines']} line(s)).",
        metrics=[
            money_metric("Total cost", t["total_amount"]),
            metric("Lines", t["lines"], "count"),
        ],
        note=NOTE,
        module="ap",
    )


def item_prices(ctx, e) -> Answer:
    qid = _qid(ctx)
    rows = proj.price_history(e.item_text)
    if not rows:
        return Answer(qid=qid, title="Item price", summary=f"No purchases found matching \"{e.item_text}\".", module="ap")
    if qid in ("A9", "J85"):
        top = rows[0]
        summary = (
            f"Latest price paid for \"{e.item_text}\": {money_metric('x', top['unit_price'])['value']} "
            f"({top['po_date']}, {top['po_number']}, {top['supplier']})."
        )
        metrics = [
            money_metric("Latest unit price", top["unit_price"]),
            metric("Date", top["po_date"].isoformat(), "date"),
            metric("PO", top["po_number"], "text"),
        ]
    elif qid == "A10":
        prev = rows[1] if len(rows) > 1 else None
        if prev is None:
            return Answer(qid="A10", title="Previous price", summary=f"Only one recorded price for \"{e.item_text}\"; no previous price yet.", rows=[{"Unit price": f"₱{rows[0]['unit_price']:,.2f}"}], note=NOTE, module="ap")
        summary = f"Previous price for \"{e.item_text}\": {money_metric('x', prev['unit_price'])['value']} ({prev['po_date']})."
        metrics = [money_metric("Previous unit price", prev["unit_price"]), metric("Date", prev["po_date"].isoformat(), "date")]
    else:
        summary = f"{len(rows)} distinct price(s) for \"{e.item_text}\":"
        metrics = [metric("Distinct prices", len(rows), "count")]
    return Answer(
        qid=qid,
        title="Item price",
        summary=summary,
        metrics=metrics,
        rows=[
            {"Date": r["po_date"].isoformat(), "PO": r["po_number"], "Supplier": r["supplier"], "Unit price": f"₱{r['unit_price']:,.2f}"}
            for r in rows[:8]
        ],
        note=NOTE,
        module="ap",
    )


def item_paid(ctx, e) -> Answer:
    paid = proj.item_paid(e.item_text)
    t = proj.item_totals(e.item_text)
    if not t["lines"]:
        return Answer(qid="A3", title="Amount paid", summary=f"No purchases found matching \"{e.item_text}\".", module="ap")
    purchased = t["total_amount"]
    ratio = (paid / purchased) if purchased else Decimal("0.00")
    return Answer(
        qid="A3",
        title="Amount paid for item",
        summary=(
            f"Approximately {money_metric('x', paid)['value']} has been cleared "
            f"against \"{e.item_text}\" purchases totaling {money_metric('x', purchased)['value']} "
            f"({ratio*100:.0f}% paid)."
        ),
        metrics=[
            money_metric("Estimated paid", paid),
            money_metric("Total purchased", purchased),
            metric("Paid ratio", f"{ratio*100:.0f}%", "text"),
        ],
        note=NOTE + " Attribution splits PO payments across its lines by share of the PO total.",
        module="ap",
    )


def item_payment_status(ctx, e) -> Answer:
    data = proj.item_payment_status(e.item_text)
    if not data["rows"]:
        return Answer(qid="A15", title="Payment status", summary=f"No purchases found matching \"{e.item_text}\".", module="ap")
    total_ratio = (data["total_paid"] / data["total_base"]) if data["total_base"] else Decimal("0.00")
    total_ratio = min(total_ratio, Decimal("1.00"))
    if total_ratio >= Decimal("0.9999"):
        verdict = "fully paid"
    elif total_ratio > 0:
        verdict = f"partially paid ({total_ratio*100:.0f}%)"
    else:
        verdict = "not paid yet"
    return Answer(
        qid="A15",
        title="Payment status",
        summary=f"\"{e.item_text}\" purchases are {verdict} (estimated).",
        metrics=[
            metric("Verdict", verdict, "text"),
            money_metric("Attributed paid", data["total_paid"]),
            money_metric("Item purchases", data["total_base"]),
        ],
        rows=data["rows"][:8],
        note=NOTE,
        module="ap",
    )


def supplier_items_handler(ctx, e) -> Answer:
    rows = proj.supplier_items(e.supplier)
    if not rows:
        return Answer(qid="A12", title="Items from supplier", summary=f"No PO lines found for {e.supplier.name}.", module="ap")
    return Answer(
        qid="A12",
        title="Items from supplier",
        summary=f"{len(rows)} distinct item line(s) purchased from {e.supplier.name}.",
        metrics=[metric("Items", len(rows), "count")],
        rows=[
            {"Item": r["description"], "POs": r["po_count"], "Qty": f"{r['qty']:,.2f}", "Spent": f"₱{r['amount']:,.2f}"}
            for r in rows[:10]
        ],
        note=NOTE,
        module="ap",
    )