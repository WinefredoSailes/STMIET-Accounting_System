"""Purchase-document trace answers — B (PR/PO/RFP/CV/check chain).

The doc chain is RFP.po + RFP.cv + CheckVoucher.check_no (ADR-018/ADR-0XX);
the Purchase Request number lives per PO line (POLine.pr_number). All reads.
"""

from __future__ import annotations

from ..base import Answer, metric, money_metric


def _po_of(ctx, e):
    if e.po is not None:
        return e.po
    if e.rfp is not None:
        return e.rfp.po
    if e.cv is not None and e.cv.rfp is not None:
        return e.cv.rfp.po
    return None


def pr_numbers(ctx, e) -> Answer:
    po = _po_of(ctx, e)
    if po is None:
        return Answer(qid="B16", title="Purchase Request", summary="No purchase order could be matched to this document.", module="ap")
    prs = list(dict.fromkeys(ln.pr_number for ln in po.lines.all() if ln.pr_number))
    if not prs:
        return Answer(
            qid="B16",
            title="Purchase Request",
            summary=f"{po.po_number} has no PR numbers recorded on its lines yet.",
            module="ap",
        )
    return Answer(
        qid="B16",
        title="Purchase Request",
        summary=f"{po.po_number} references {len(prs)} PR number(s): {', '.join(prs)}.",
        metrics=[metric("PR count", len(prs), "count")],
        rows=[{"PR No.": p} for p in prs],
        links=[{"url": f"/ap/pos/{po.pk}/", "label": f"Open {po.po_number}"}],
        module="ap",
    )


def po_of(ctx, e) -> Answer:
    po = _po_of(ctx, e)
    if po is None:
        return Answer(qid="B17", title="Purchase Order", summary="No purchase order found for this document.", module="ap")
    return Answer(
        qid="B17",
        title="Purchase Order",
        summary=f"{po.po_number} ({po.po_date}) — {po.supplier.name}, {money_metric('x', po.amount)['value']} ({po.status}).",
        metrics=[
            metric("PO no", po.po_number, "text"),
            metric("Date", po.po_date.isoformat(), "date"),
            money_metric("Amount", po.amount),
            metric("Status", po.status, "text"),
        ],
        links=[{"url": f"/ap/pos/{po.pk}/", "label": f"Open {po.po_number}"}],
        module="ap",
    )


def rfp_of(ctx, e) -> Answer:
    rfps = []
    if e.rfp is not None:
        rfps = [e.rfp]
    elif e.po is not None:
        rfps = list(e.po.rfps.all().order_by("rfp_date"))
    elif e.cv is not None and e.cv.rfp is not None:
        rfps = [e.cv.rfp]
    if not rfps:
        return Answer(qid="B20", title="Related RFP", summary="No RFP found for this purchase document.", module="ap")
    return Answer(
        qid="B20",
        title="Related RFP",
        summary=f"{len(rfps)} RFP(s) relating to this purchase.",
        metrics=[metric("RFPs", len(rfps), "count")],
        rows=[
            {"RFP": r.ap_number, "Date": r.rfp_date.isoformat(), "Payee": r.payee.name, "Amount": f"₱{r.amount:,.2f}", "Status": r.status}
            for r in rfps[:8]
        ],
        module="ap",
    )


def _cv_list(ctx, e):
    if e.cv is not None:
        return [e.cv]
    rfps = []
    if e.rfp is not None:
        rfps = [e.rfp]
    elif e.po is not None:
        rfps = list(e.po.rfps.all())
    out = []
    for r in rfps:
        out.extend(r.cv.all())
    return out


def cv_of(ctx, e) -> Answer:
    cvs = _cv_list(ctx, e)
    if not cvs:
        return Answer(qid="B21", title="Related Check Voucher", summary="No Check Voucher found for this purchase.", module="ap")
    return Answer(
        qid="B21",
        title="Related Check Voucher",
        summary=f"{len(cvs)} Check Voucher(s) for this purchase.",
        metrics=[metric("CVs", len(cvs), "count")],
        rows=[
            {"CV": c.cv_number, "Date": c.cv_date.isoformat(), "Payee": c.payee.name, "Status": c.status, "Amount": f"₱{c.gross_amount:,.2f}"}
            for c in cvs[:8]
        ],
        module="ap",
    )


def check_of(ctx, e) -> Answer:
    cvs = _cv_list(ctx, e)
    checks = [{"cv": c, "check_no": c.check_no} for c in cvs if c.check_no]
    if not checks:
        return Answer(qid="B22", title="Issued check", summary="No check number recorded for this purchase yet.", module="ap")
    return Answer(
        qid="B22",
        title="Issued check",
        summary=f"Check(s) {', '.join(c['check_no'] for c in checks)} issued for this purchase.",
        metrics=[metric("Checks", len(checks), "count")],
        rows=[{"CV": c["cv"].cv_number, "Check no": c["check_no"], "Payee": c["cv"].payee.name, "Amount": f"₱{c['cv'].gross_amount:,.2f}"} for c in checks[:8]],
        module="ap",
    )


def fully_paid(ctx, e) -> Answer:
    """A15 — is this purchase (PO/RFP document) fully paid?

    Paid = cleared CV gross (posted JEs) against the document's RFPs; for a
    PO the RFPs must be linked to it, so payment is attributed at document
    level (no per-item estimate here).
    """
    from decimal import Decimal

    from django.db.models import Sum

    from apps.ap.models import CheckVoucher
    from apps.posting.models import PostingStatus

    doc_label = None
    base = None
    rfps = None
    if e.po is not None:
        doc_label = e.po.po_number
        base = Decimal(e.po.amount or 0)
        rfps = e.po.rfps.all()
    elif e.rfp is not None:
        doc_label = e.rfp.ap_number
        base = Decimal(e.rfp.amount or 0)
        rfps = [e.rfp]
    if rfps is None:
        return Answer(qid="A15", title="Payment status", summary="No purchase document could be matched.", module="ap")
    paid = Decimal("0.00")
    for rfp in rfps:
        if rfp.status != "posted" or rfp.is_reversed:
            continue
        paid += (
            CheckVoucher.objects.filter(
                rfp=rfp, journal_entry__status=PostingStatus.POSTED
            ).aggregate(s=Sum("gross_amount"))["s"]
            or Decimal("0.00")
        )
    ratio = (paid / base) if base else Decimal("0.00")
    if not base and not paid:
        verdict, note = "no amount recorded", ""
    elif ratio >= Decimal("0.9999"):
        verdict, note = "fully paid", ""
    elif ratio > 0:
        verdict, note = f"partially paid ({ratio*100:.0f}%)", f"Remaining: {money_metric('x', base - paid)['value']}"
    else:
        verdict, note = "not paid yet", f"Total amount: {money_metric('x', base)['value']}"
    return Answer(
        qid="A15",
        title="Payment status",
        summary=f"{doc_label} is {verdict}.",
        metrics=[
            metric("Status", verdict, "text"),
            money_metric("Paid", paid),
            money_metric("Amount", base),
        ],
        note=note,
        module="ap",
    )


def rr_of(ctx, e) -> Answer:
    """B18 — which Receiving Report / Delivery Receipt covers this purchase?

    Reads the optional capture fields on the PO (ADR-050 Phase 3). When the
    reference has not been recorded yet the answer says so honestly.
    """
    po = _po_of(ctx, e)
    if po is None:
        return Answer(qid="B18", title="Receiving/Delivery Report", summary="No purchase order could be matched to this document.", module="ap")
    rr = po.receiving_report_no or ""
    dr = po.delivery_receipt_no or ""
    rd = po.receipt_date
    if not (rr or dr or rd):
        return Answer(
            qid="B18",
            title="Receiving/Delivery Report",
            summary=f"No receiving report or delivery receipt has been recorded for {po.po_number} yet.",
            note="Staff can capture RR/DR numbers in the Goods Receipt section of the purchase order form.",
            links=[{"url": f"/ap/pos/{po.pk}/", "label": f"Open {po.po_number}"}],
            module="ap",
        )
    bits = []
    if rr:
        bits.append(f"RR {rr}")
    if dr:
        bits.append(f"DR {dr}")
    if rd:
        bits.append(f"received {rd.isoformat()}")
    return Answer(
        qid="B18",
        title="Receiving/Delivery Report",
        summary=f"{po.po_number} — {' · '.join(bits)}.",
        metrics=[
            metric("Receiving Report", rr or "—", "text"),
            metric("Delivery Receipt", dr or "—", "text"),
            metric("Received", rd.isoformat() if rd else "—", "date"),
        ],
        links=[{"url": f"/ap/pos/{po.pk}/", "label": f"Open {po.po_number}"}],
        module="ap",
    )


def supplier_invoice_of(ctx, e) -> Answer:
    """B19 — which Supplier Invoice backs this purchase?

    Reads the optional capture fields on the RFP (ADR-050 Phase 3); accepts
    an RFP directly or resolves RFPs through the PO / CV.
    """
    rfps = []
    if e.rfp is not None:
        rfps = [e.rfp]
    elif e.cv is not None and e.cv.rfp is not None:
        rfps = [e.cv.rfp]
    elif e.po is not None:
        rfps = list(e.po.rfps.all().order_by("rfp_date"))
    if not rfps:
        return Answer(qid="B19", title="Supplier Invoice", summary="No RFP found for this purchase to inspect supplier invoices.", module="ap")
    rows = [
        {
            "RFP": r.ap_number,
            "Supplier Invoice": r.supplier_invoice_no or "—",
            "Invoice Date": r.supplier_invoice_date.isoformat() if r.supplier_invoice_date else "—",
        }
        for r in rfps[:8]
    ]
    filled = [r for r in rfps if r.supplier_invoice_no or r.supplier_invoice_date]
    if not filled:
        return Answer(
            qid="B19",
            title="Supplier Invoice",
            summary="No supplier invoice reference recorded for this purchase yet.",
            rows=rows,
            note="Staff can capture the supplier invoice number/date in the RFP form.",
            module="ap",
        )
    main = filled[0]
    bits = []
    if main.supplier_invoice_no:
        bits.append(f"invoice {main.supplier_invoice_no}")
    if main.supplier_invoice_date:
        bits.append(f"dated {main.supplier_invoice_date.isoformat()}")
    return Answer(
        qid="B19",
        title="Supplier Invoice",
        summary=f"{' · '.join(bits)} ({main.ap_number}).",
        metrics=[
            metric("Supplier Invoice", main.supplier_invoice_no or "—", "text"),
            metric("Invoice Date", main.supplier_invoice_date.isoformat() if main.supplier_invoice_date else "—", "date"),
        ],
        rows=rows if len(filled) > 1 else None,
        links=[{"url": f"/ap/rfps/{main.pk}/", "label": f"View RFP {main.ap_number}"}],
        module="ap",
    )