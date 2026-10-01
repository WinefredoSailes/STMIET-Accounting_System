"""Inventory computed answers — J (Phase 2 projection).

Derived from the event-bridge records (InventoryEvent.payload) and the
purchase projection (PO lines). Stock on hand (J81) and minimum-stock (J87)
stay deferred — they need the external inventory system's balance feed.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from ..base import Answer, metric, money_metric
from .. import purchase_projection as proj

NOTE = "Derived from inventory event records and purchase lines (no stock balance feed yet)."


def _event_rows(item_text: str, limit: int = 30):
    rows = []
    for ev in proj.event_items(item_text, limit=limit * 3):
        qty = ev["qty"]
        unit_cost = ev["unit_cost"]
        rows.append(
            {
                "Date": ev["occurred_on"].isoformat(),
                "Event": ev["event_type"],
                "Status": ev["status"],
                "Qty": f"{Decimal(qty):,.2f}" if qty is not None else "—",
                "Unit cost": f"₱{Decimal(unit_cost):,.2f}" if unit_cost is not None else "—",
                "Key": ev["event_key"],
            }
        )
    return rows[:limit]


def inventory_cost(ctx, e) -> Answer:
    rows = proj.event_items(e.item_text, limit=60)
    total_cost = Decimal("0.00")
    total_qty = Decimal("0.00")
    for ev in rows:
        qty = ev["qty"]
        unit_cost = ev["unit_cost"]
        if qty is None or unit_cost is None:
            continue
        total_qty += Decimal(qty)
        total_cost += Decimal(qty) * Decimal(unit_cost)
    summary = (
        f"Inventory record for \"{e.item_text}\": {len(rows)} event(s), "
        f"{money_metric('x', total_cost)['value']} cost on {total_qty:,.2f} unit(s)."
        if rows else f"No inventory events found for \"{e.item_text}\"."
    )
    return Answer(
        qid="J82",
        title="Inventory cost",
        summary=summary,
        metrics=[money_metric("Recorded cost", total_cost), metric("Events", len(rows), "count")],
        rows=_event_rows(e.item_text),
        note=NOTE,
        module="inventory",
    )


def item_movement(ctx, e) -> Answer:
    rows = proj.event_items(e.item_text, limit=200)
    by_type: dict = {}
    for ev in rows:
        key = ev["event_type"]
        by_type[key] = by_type.get(key, Decimal("0.00")) + (
            Decimal(ev["qty"]) if ev["qty"] is not None else Decimal("0.00")
        )
    summary = (
        f"{len(rows)} inventory event(s) for \"{e.item_text}\"."
        if rows else f"No inventory movement found for \"{e.item_text}\"."
    )
    return Answer(
        qid="J86",
        title="Item movement",
        summary=summary,
        metrics=[
            metric("Events", len(rows), "count"),
            metric("Movement types", len(by_type), "count"),
        ],
        rows=[
            {"Movement type": k, "Qty": f"{v:,.2f}"} for k, v in sorted(by_type.items())
        ] + _event_rows(e.item_text, limit=8),
        note=NOTE,
        module="inventory",
    )


def no_movement(ctx, e) -> Answer:
    """Descriptions with no PO purchase and no inventory event recently."""
    from apps.ap.models import POLine
    from apps.inventory.models import InventoryEvent

    since = date.today() - timedelta(days=90)
    active = set(
        InventoryEvent.objects.filter(occurred_on__gte=since)
        .values_list("payload__product", flat=True)
    )
    active |= set(
        InventoryEvent.objects.filter(occurred_on__gte=since)
        .values_list("payload__item", flat=True)
    )
    active = {str(v).strip().lower() for v in active if v}

    inactive: list[dict] = []
    seen = set()
    for desc in (
        POLine.objects.filter(po__po_date__lt=since)
        .values_list("description", flat=True)
        .distinct()
    ):
        d = (desc or "").strip()
        low = d.lower()
        if not d or low in seen or low in active:
            continue
        seen.add(low)
        latest = (
            POLine.objects.filter(description__iexact=d)
            .select_related("po")
            .order_by("-po__po_date")
            .first()
        )
        inactive.append(
            {
                "Item": d,
                "Last PO": latest.po.po_date.isoformat() if latest else "—",
                "Last PO no": latest.po.po_number if latest else "—",
            }
        )
    if e.item_text:
        filtered = [r for r in inactive if e.item_text.lower() in r["Item"].lower()]
        if not filtered and e.item_text:
            return Answer(
                qid="J88",
                title="Items without movement",
                summary=f"\"{e.item_text}\" has activity in the last 90 days (or is not tracked).",
                note=NOTE,
                module="inventory",
            )
        inactive = filtered
    return Answer(
        qid="J88",
        title="Items without movement",
        summary=f"{len(inactive)} item(s) with no PO or inventory event in the last 90 days.",
        metrics=[metric("Inactive items", len(inactive), "count")],
        rows=inactive[:12],
        note=NOTE,
        module="inventory",
    )


def inventory_history(ctx, e) -> Answer:
    po_rows = [
        {
            "Date": r["po_date"].isoformat(),
            "Source": r["po_number"],
            "Type": "Purchase",
            "Qty": f"{r['qty']:,.2f} {r['unit']}".strip(),
            "Unit cost": f"₱{r['unit_price']:,.2f}",
        }
        for r in proj.item_history(e.item_text, limit=20)
    ]
    event_rows = [
        {
            "Date": ev["occurred_on"].isoformat(),
            "Source": ev["event_key"],
            "Type": ev["event_type"],
            "Qty": f"{Decimal(ev['qty']):,.2f}" if ev["qty"] is not None else "—",
            "Unit cost": f"₱{Decimal(ev['unit_cost']):,.2f}" if ev["unit_cost"] is not None else "—",
        }
        for ev in proj.event_items(e.item_text, limit=40)
    ]
    merged = sorted(po_rows + event_rows, key=lambda r: (r["Date"], r["Type"]), reverse=True)
    if not merged:
        return Answer(qid="J89", title="Inventory history", summary=f"No history found for \"{e.item_text}\".", module="inventory")
    return Answer(
        qid="J89",
        title="Inventory history",
        summary=f"{len(po_rows)} purchase line(s) + {len(event_rows)} event(s) for \"{e.item_text}\".",
        metrics=[metric("Rows", len(merged), "count")],
        rows=merged[:14],
        note=NOTE,
        module="inventory",
    )