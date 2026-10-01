"""Document-count and cross-document aggregates — L (extension questions).

All reads are `count()`/aggregate over existing masters — no projections,
no writes. Period handling mirrors the rest of the assistant: an explicit
"this week/month/quarter/year" phrase widens or narrows the window, while a
plain "how many X?" counts everything (the latest-activity default is NOT
applied to counts, since people expect lifetime totals).
"""

from __future__ import annotations

import importlib
from decimal import Decimal

from django.db.models import Count, Q

from ..base import Answer, metric, money_metric


def _load_model(path: str):
    module_name, _, cls = path.rpartition(".")
    return getattr(importlib.import_module(module_name), cls)


#: kind -> spec. ``status`` names the model's lifecycle field (used only when
#: the question literally says "posted"/"cleared"/...). ``pr`` is special:
#: PR numbers live on PO lines (ADR-0XX), so it counts distinct pr_number.
COUNTS = {
    "cv": {"model": "apps.ap.models.CheckVoucher", "date": "cv_date", "label": "check vouchers", "link": "/ap/cv/", "status": "status"},
    "rfp": {"model": "apps.ap.models.RFPDocument", "date": "rfp_date", "label": "RFPs", "link": "/ap/rfps/", "status": "status"},
    "je": {"model": "apps.posting.models.JournalEntry", "date": "transaction_date", "label": "journal entries", "link": "/journal/", "status": "status"},
    "ftv": {"model": "apps.cash.models.InterAccountTransfer", "date": "transfer_date", "label": "fund transfers", "link": "/cash/transfers/", "status": "status"},
    "po": {"model": "apps.ap.models.PurchaseOrder", "date": "po_date", "label": "purchase orders", "link": "/ap/pos/", "status": "status"},
    "conso": {"model": "apps.ap.models.CONSOBatch", "date": "conso_date", "label": "CONSO batches", "link": "/ap/conso/", "status": "status"},
    "si": {"model": "apps.ar.models.ARInvoice", "date": "transaction_date", "label": "sales invoices", "link": "/ar/invoices/", "status": "status"},
    "receipt": {"model": "apps.ar.models.AcknowledgmentReceipt", "date": "transaction_date", "label": "receipts", "link": "/ar/receipts/", "status": "status"},
    "deposit": {"model": "apps.ar.models.Deposit", "date": "transaction_date", "label": "bank deposits", "link": "/ar/receipts/"},
    "pcf": {"model": "apps.cash.models.PCFReplenishment", "date": "request_date", "label": "PCF replenishments", "link": "/cash/pcf/replenishments/", "status": "status"},
    "advance": {"model": "apps.ap.models.AdvanceToEmployee", "date": "granted_date", "label": "advances", "link": "/ap/advances/", "status": "status"},
    "billing": {"model": "apps.billing.models.BillingDocument", "date": "billing_date", "label": "billing transactions", "link": "/billing/", "status": "status"},
    "asset": {"model": "apps.assets.models.Asset", "date": "acquisition_date", "label": "asset acquisitions", "link": "/assets/", "status": "status"},
}

#: Master-data counts (no date field).
MASTERS = {
    "suppliers": ("apps.ap.models.Supplier", "suppliers", "/ap/suppliers/"),
    "customers": ("apps.ar.models.Customer", "customers", "/ar/customers/"),
    "banks": ("apps.cash.models.BankAccount", "bank accounts", "/cash/banks/"),
    "funds": ("apps.cash.models.PettyCashFund", "petty cash funds", "/cash/pcf/"),
}

#: Literal lifecycle words honored as a status filter on count questions.
STATUS_TOKENS = {
    "posted", "cleared", "open", "draft", "submitted", "prepared",
    "approved", "rejected", "requested",
}


def _window(ctx):
    """(use_window, start, end): explicit periods only (never the default)."""
    period = ctx.entities.period
    if period is None or period.is_default:
        return False, None, None
    return True, period.start, period.end


def _scope(start, end) -> str:
    if start.year == end.year and start.month == end.month:
        return f"{start:%B %Y}"
    return f"{start:%b %d} – {end:%b %d, %Y}"


def _status_token(ctx) -> str | None:
    import re

    for token in STATUS_TOKENS:
        if re.search(rf"\b{token}\b", ctx.lower):
            return token
    return None


def rfp_per_cv(ctx, e) -> Answer:
    """L101 — how many RFPs each check voucher settles (aggregate + exceptions)."""
    CheckVoucher = _load_model("apps.ap.models.CheckVoucher")
    RFPDocument = _load_model("apps.ap.models.RFPDocument")
    total = CheckVoucher.objects.count()
    linked = CheckVoucher.objects.exclude(rfp__isnull=True).count()
    rfps_posted = RFPDocument.objects.filter(status="posted").count()
    pct = (Decimal(linked) / Decimal(total) * 100).quantize(Decimal("0.1")) if total else Decimal("0.0")
    avg = (Decimal(linked) / Decimal(total)).quantize(Decimal("0.01")) if total else Decimal("0.00")
    splits = list(
        RFPDocument.objects.filter(status="posted")
        .annotate(n=Count("cv"))
        .filter(n__gt=1)
        .order_by("-rfp_date")[:8]
    )
    summary = (
        f"{total} check voucher(s) settle {linked} RFP(s) ({pct}% linked) — "
        f"on average {avg} RFP per CV."
    )
    note = (
        "One CV pays at most one RFP by design; RFPs split across multiple CVs are listed below."
        if splits else "One CV pays at most one RFP by design — no split settlements found."
    )
    rows = [{"RFP split across": r.ap_number, "CVs": r.n} for r in splits] or None
    return Answer(
        qid="L101",
        title="RFPs per CV",
        summary=summary,
        metrics=[
            metric("Check vouchers", total, "count"),
            metric("Linked to an RFP", linked, "count"),
            metric("Linked %", f"{pct}%", "text"),
            metric("Avg RFP per CV", f"{avg}", "text"),
            metric("RFPs posted", rfps_posted, "count"),
        ],
        rows=rows,
        note=note,
        links=[{"url": "/ap/cv/", "label": "Check voucher register"}, {"url": "/ap/rfps/", "label": "RFP register"}],
        module="ap",
    )


def doc_count(ctx, e) -> Answer:
    """L102–L115 — how many <document>s (optionally a period/status)."""
    kind = (ctx.entry.extra or "").lower() if ctx.entry is not None else ""
    if not kind:
        return None
    use_window, start, end = _window(ctx)
    status = _status_token(ctx)

    if kind == "pr":
        POLine = _load_model("apps.ap.models.POLine")
        qs = POLine.objects.exclude(pr_number="")
        if use_window:
            qs = qs.filter(po__po_date__gte=start, po__po_date__lte=end)
        count = qs.values("pr_number").distinct().count()
        label = "purchase requests (PR numbers on PO lines)"
        link = "/ap/pos/"
        status = None
    else:
        spec = COUNTS.get(kind)
        if spec is None:
            return None
        model = _load_model(spec["model"])
        qs = model.objects.all()
        if use_window:
            qs = qs.filter(**{f"{spec['date']}__gte": start, f"{spec['date']}__lte": end})
        if status and spec.get("status"):
            qs = qs.filter(**{spec["status"]: status})
        count = qs.count()
        label = spec["label"]
        link = spec["link"]

    scope_bits = []
    if use_window:
        scope_bits.append(_scope(start, end))
    if status:
        scope_bits.append(f"status {status!r}")
    scope_text = " · ".join(scope_bits)
    summary = (
        f"{count} {label} in {scope_text}."
        if scope_text else f"{count} {label} in total."
    )
    return Answer(
        qid=ctx.entry.qid,
        title="Count",
        summary=summary,
        metrics=[
            metric("Count", count, "count"),
            metric("Scope", scope_text or "all time", "text"),
        ],
        links=[{"url": link, "label": f"Open the {label} register"}],
        module=ctx.entry.module,
    )


def master_counts(ctx, e) -> Answer:
    """L116 — how many suppliers / customers / bank accounts / PCF funds."""
    lower = ctx.lower or ""
    if "pcf fund" in lower or "petty cash fund" in lower:
        key = "funds"
    elif "bank" in lower:
        key = "banks"
    elif "customer" in lower:
        key = "customers"
    else:
        key = "suppliers"
    _, label, link = MASTERS[key]
    model = _load_model(MASTERS[key][0])
    qs = model.objects.all()
    if key in ("banks", "funds") and hasattr(model, "is_active"):
        qs = qs.filter(is_active=True)
    count = qs.count()
    return Answer(
        qid=ctx.entry.qid,
        title="Master count",
        summary=f"{count} {label} in the master list.",
        metrics=[metric("Count", count, "count")],
        links=[{"url": link, "label": f"Open the {label} list"}],
        module="ap" if key == "suppliers" else "ar" if key == "customers" else "cash",
    )


def _user_name(u) -> str:
    if u is None:
        return "—"
    name = getattr(u, "get_full_name", lambda: "")()
    return name or u.username


def who_prepared(ctx, e) -> Answer:
    """L117 — who processed this item for this supplier (RFP and PO preparers)."""
    RFPDocument = _load_model("apps.ap.models.RFPDocument")
    PurchaseOrder = _load_model("apps.ap.models.PurchaseOrder")
    supplier = e.supplier
    item = e.item_text

    rfp_qs = RFPDocument.objects.select_related("created_by", "payee")
    po_qs = PurchaseOrder.objects.select_related("created_by", "supplier")
    if supplier is not None:
        rfp_qs = rfp_qs.filter(payee=supplier)
        po_qs = po_qs.filter(supplier=supplier)
    if item:
        rfp_qs = rfp_qs.filter(
            Q(particulars__icontains=item) | Q(lines__description__icontains=item)
        )
        po_qs = po_qs.filter(
            Q(particulars__icontains=item) | Q(lines__description__icontains=item)
        )
    latest_rfp = rfp_qs.order_by("-rfp_date", "-id").first()
    latest_po = po_qs.order_by("-po_date", "-id").first()
    if latest_rfp is None and latest_po is None:
        what = f" for {item!r}" if item else ""
        who = f" of {supplier.name}" if supplier is not None else ""
        return Answer(
            qid="L117",
            title="Who processed",
            summary=f"No matching purchase or payment document found{what}{who}. Here are the closest records from search instead.",
            module="ap",
        )
    parts = []
    metrics = []
    links = []
    if latest_po is not None:
        who = _user_name(latest_po.created_by)
        parts.append(f"PO {latest_po.po_number} was prepared by {who} on {latest_po.po_date.isoformat()}")
        metrics.append(metric("PO prepared by", who, "person"))
        links.append({"url": f"/ap/pos/{latest_po.pk}/", "label": f"Open {latest_po.po_number}"})
    if latest_rfp is not None:
        who = _user_name(latest_rfp.created_by)
        parts.append(f"RFP {latest_rfp.ap_number} was prepared by {who} on {latest_rfp.rfp_date.isoformat()}")
        metrics.append(metric("RFP prepared by", who, "person"))
        links.append({"url": f"/ap/rfps/{latest_rfp.pk}/", "label": f"Open {latest_rfp.ap_number}"})
    return Answer(
        qid="L117",
        title="Who processed",
        summary=" · ".join(parts) + ".",
        metrics=metrics,
        links=links,
        module="ap",
    )