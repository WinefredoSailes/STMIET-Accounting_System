"""Purchase/item read-model (Phase 2 projection) — read-only.

There is no Item master in the system yet; the projection answers item
questions from the purchase documents that already exist:

    POLine (item, qty, unit, unit price, PR no)  <- PO.supplier / po_date
        -> RFP (payable) -> CheckVoucher (cleared gross)

Item identity is free-text over ``POLine.description`` (exact product codes
arrive with the external inventory feed). Payment attribution is **pro-rata
by line share of the PO's line total** (the approved method): a PO paid
₱60K whose item lines make up 80% of the PO is attributed ₱48K to the item.
Every figure is flagged "estimated" in the answer.
"""

from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal

from django.db.models import Sum

from apps.ap.models import CheckVoucher, POLine, RFPDocument
from apps.posting.models import PostingStatus

LINE_CAP = 300


def item_lines(item_text: str, limit: int = LINE_CAP) -> list:
    """Every PO line whose description contains the item text."""
    return list(
        POLine.objects.filter(description__icontains=item_text)
        .select_related("po", "po__supplier", "po__segment")
        .order_by("po__po_date", "id")[:limit]
    )


def _po_line_total(po_id: int) -> Decimal:
    return (
        POLine.objects.filter(po_id=po_id).aggregate(t=Sum("amount"))["t"]
        or Decimal("0.00")
    )


def _po_paid(po_id: int) -> Decimal:
    """Cleared CV gross posted against any RFP of the PO (reversed excluded)."""
    paid = Decimal("0.00")
    for rfp_id in RFPDocument.objects.filter(po_id=po_id).values_list("id", flat=True):
        amt = (
            CheckVoucher.objects.filter(
                rfp_id=rfp_id, journal_entry__status=PostingStatus.POSTED
            ).aggregate(s=Sum("gross_amount"))["s"]
            or Decimal("0.00")
        )
        paid += amt
    return paid


def item_history(item_text: str, limit: int = 20) -> list[dict]:
    rows = []
    for ln in item_lines(item_text)[:limit]:
        rows.append(
            {
                "po_id": ln.po_id,
                "po_number": ln.po.po_number,
                "po_date": ln.po.po_date,
                "supplier": ln.po.supplier.name,
                "supplier_id": ln.po.supplier_id,
                "pr_number": ln.pr_number or "—",
                "qty": ln.qty,
                "unit": ln.unit or "",
                "description": ln.description,
                "unit_price": ln.unit_price,
                "amount": ln.amount,
            }
        )
    return rows


def item_suppliers(item_text: str) -> list[dict]:
    seen: "OrderedDict[int, dict]" = OrderedDict()
    for ln in item_lines(item_text):
        s = ln.po.supplier
        b = seen.setdefault(
            s.id,
            {"supplier_id": s.id, "supplier": s.name, "lines": 0, "qty": Decimal("0.00"), "amount": Decimal("0.00"), "last_date": None},
        )
        b["lines"] += 1
        b["qty"] += ln.qty
        b["amount"] += ln.amount
        d = ln.po.po_date
        b["last_date"] = d if b["last_date"] is None or d > b["last_date"] else b["last_date"]
    return sorted(seen.values(), key=lambda r: -r["amount"])


def item_totals(item_text: str) -> dict:
    lines = item_lines(item_text)
    total_qty = sum((ln.qty for ln in lines), Decimal("0.00"))
    total_amount = sum((ln.amount for ln in lines), Decimal("0.00"))
    po_ids = set(ln.po_id for ln in lines)
    return {
        "lines": len(lines),
        "po_count": len(po_ids),
        "total_qty": total_qty,
        "total_amount": total_amount,
    }


def price_history(item_text: str, limit: int = 8) -> list[dict]:
    entries: list[dict] = []
    seen_prices = set()
    for ln in item_lines(item_text):
        price = ln.unit_price
        if str(price) in seen_prices:
            continue
        seen_prices.add(str(price))
        entries.append(
            {
                "unit_price": price,
                "po_number": ln.po.po_number,
                "po_date": ln.po.po_date,
                "supplier": ln.po.supplier.name,
            }
        )
    return sorted(entries, key=lambda r: (r["po_date"], r["po_number"]), reverse=True)[:limit]


def item_paid(item_text: str) -> Decimal:
    """Cleared payments attributed to the item by pro-rata line share."""
    lines = item_lines(item_text)
    paid = Decimal("0.00")
    for po_id in dict.fromkeys(ln.po_id for ln in lines):
        base = _po_line_total(po_id)
        if base <= 0:
            continue
        item_amt = sum((ln.amount for ln in lines if ln.po_id == po_id), Decimal("0.00"))
        if item_amt <= 0:
            continue
        share = item_amt / base
        paid += _po_paid(po_id) * share
    return paid


def item_payment_status(item_text: str) -> dict:
    """Per-PO payment status for the item's purchase lines."""
    lines = item_lines(item_text)
    rows = []
    total_base = Decimal("0.00")
    total_paid = Decimal("0.00")
    for po_id in dict.fromkeys(ln.po_id for ln in lines):
        base = _po_line_total(po_id)
        if base <= 0:
            continue
        item_amt = sum((ln.amount for ln in lines if ln.po_id == po_id), Decimal("0.00"))
        share = item_amt / base
        paid = _po_paid(po_id) * share
        total_base += item_amt
        total_paid += paid
        ratio = (paid / item_amt) if item_amt else Decimal("0.00")
        rows.append(
            {
                "PO": next(ln.po.po_number for ln in lines if ln.po_id == po_id),
                "Item lines": f"₱{item_amt:,.2f}",
                "Attributed paid": f"₱{paid:,.2f}",
                "": "—" if ratio >= Decimal("0.9999") else (f"{ratio*100:.0f}% paid" if ratio > 0 else "unpaid"),
            }
        )
    return {"rows": rows, "total_paid": total_paid, "total_base": total_base}


def supplier_items(supplier) -> list[dict]:
    seen = OrderedDict()
    for ln in (
        POLine.objects.filter(po__supplier=supplier)
        .select_related("po")
        .order_by("po__po_date", "id")[:LINE_CAP]
    ):
        key = ln.description.strip().lower()
        b = seen.setdefault(key, {"description": ln.description, "po_count": 0, "qty": Decimal("0.00"), "amount": Decimal("0.00"), "last_date": None})
        b["po_count"] += 1
        b["qty"] += ln.qty
        b["amount"] += ln.amount
        d = ln.po.po_date
        b["last_date"] = d if b["last_date"] is None or d > b["last_date"] else b["last_date"]
    return sorted(seen.values(), key=lambda r: -r["amount"])


def event_items(item_text: str, limit: int = 60) -> list:
    """InventoryEvent rows whose payload names the item (best effort)."""
    from apps.inventory.models import InventoryEvent

    out = []
    for ev in (
        InventoryEvent.objects.filter(status__in=("received", "validated", "posted"))
        .select_related("segment")
        .order_by("-occurred_on")[:limit]
    ):
        payload = ev.payload or {}
        name = (
            payload.get("product")
            or payload.get("item")
            or payload.get("description")
            or ""
        )
        if not name or item_text.lower() not in str(name).lower():
            continue
        qty = payload.get("qty", payload.get("quantity"))
        unit_cost = payload.get("unit_cost", payload.get("price"))
        out.append(
            {
                "occurred_on": ev.occurred_on,
                "event_key": ev.event_key,
                "event_type": ev.get_event_type_display() if hasattr(ev, "get_event_type_display") else ev.event_type,
                "qty": qty,
                "unit_cost": unit_cost,
                "status": ev.status,
            }
        )
    return out