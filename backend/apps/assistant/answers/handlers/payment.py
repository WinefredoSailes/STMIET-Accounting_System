"""Payment-document trace answers — G (RFP / CV / check / actors / status).

A payment question references a document: an RFP (A####), a Check Voucher
(CV-####) or a journal entry that posted the disbursement. The handler
resolves whichever document is present and traces the chain
RFP -> CV -> check -> JE (ADR-018/ADR-020/ADR-030 chains).
"""

from __future__ import annotations

from ..base import Answer, metric, money_metric


def _primary_doc(ctx, e):
    """(rfp, cv) best pair to answer the question with."""
    if e.rfp is not None:
        return e.rfp, (e.cv or e.rfp.cv.first())
    if e.cv is not None:
        return e.cv.rfp, e.cv
    if e.je is not None:
        rfp = getattr(e.je, "rfps", None) and e.je.rfps.first()
        cv = getattr(e.je, "cv", None) and e.je.cv.first()
        return rfp, cv
    return None, None


def _user_name(u):
    if u is None:
        return "—"
    name = getattr(u, "get_full_name", lambda: "")()
    return name or u.username


def requested_by(ctx, e) -> Answer:
    rfp, _ = _primary_doc(ctx, e)
    if rfp is None:
        return Answer(qid="G55", title="Payment requester", summary="No RFP/payment document could be matched.", module="ap")
    return Answer(
        qid="G55",
        title="Payment requester",
        summary=f"RFP {rfp.ap_number} was requested by {_user_name(rfp.created_by)}.",
        metrics=[metric("Requested by", _user_name(rfp.created_by), "person"), metric("RFP", rfp.ap_number, "text")],
        links=[{"url": f"/ap/rfps/{rfp.pk}/", "label": f"View RFP {rfp.ap_number}"}],
        module="ap",
    )


def approved_by(ctx, e) -> Answer:
    rfp, cv = _primary_doc(ctx, e)
    if rfp is None:
        return Answer(qid="G56", title="Payment approval", summary="No payment document could be matched.", module="ap")
    approver = rfp.approved_by_fin or (cv.approved_by if cv else None)
    role = "Finance Head (RFP)" if rfp.approved_by_fin else ("CV approver" if cv and cv.approved_by else None)
    if approver is None:
        return Answer(
            qid="G56",
            title="Payment approval",
            summary=f"RFP {rfp.ap_number} has not been approved yet (status: {rfp.status}).",
            metrics=[metric("Status", rfp.status, "text")],
            module="ap",
        )
    return Answer(
        qid="G56",
        title="Payment approval",
        summary=f"RFP {rfp.ap_number} was approved by {_user_name(approver)} ({role}).",
        metrics=[metric("Approved by", _user_name(approver), "person"), metric("Role", role or "—", "text")],
        module="ap",
    )


def rfp_of(ctx, e) -> Answer:
    rfp, _ = _primary_doc(ctx, e)
    if rfp is None:
        return Answer(qid="G57", title="Related RFP", summary="No related RFP found for this payment.", module="ap")
    return Answer(
        qid="G57",
        title="Related RFP",
        summary=f"RFP {rfp.ap_number} — {rfp.payee.name}, {money_metric('x', rfp.amount)['value']} ({rfp.status}).",
        metrics=[
            metric("RFP", rfp.ap_number, "text"),
            money_metric("Amount", rfp.amount),
            metric("Status", rfp.status, "text"),
        ],
        links=[{"url": f"/ap/rfps/{rfp.pk}/", "label": f"View RFP {rfp.ap_number}"}],
        module="ap",
    )


def _cvs(ctx, e):
    rfp, cv = _primary_doc(ctx, e)
    if cv is not None:
        return [cv]
    if rfp is not None:
        return list(rfp.cv.all())
    return []


def cv_of(ctx, e) -> Answer:
    cvs = _cvs(ctx, e)
    if not cvs:
        return Answer(qid="G58", title="Related Check Voucher", summary="No Check Voucher found for this document.", module="ap")
    cv = cvs[0]
    return Answer(
        qid="G58",
        title="Related Check Voucher",
        summary=f"CV {cv.cv_number} — {cv.payee.name}, net {money_metric('x', cv.net_amount)['value']} (status: {cv.status}).",
        metrics=[
            metric("CV", cv.cv_number, "text"),
            money_metric("Gross", cv.gross_amount),
            money_metric("Net", cv.net_amount),
            metric("Status", cv.status, "text"),
        ],
        rows=[{"CV": c.cv_number, "Date": c.cv_date.isoformat(), "Payee": c.payee.name, "Status": c.status} for c in cvs[:5]],
        links=[{"url": f"/ap/cv/{cv.pk}/", "label": f"View CV {cv.cv_number}"}],
        module="ap",
    )


def check_issued(ctx, e) -> Answer:
    cvs = _cvs(ctx, e)
    if not cvs or not cvs[0].check_no:
        return Answer(qid="G59", title="Issued check", summary="No check number recorded for this payment yet.", module="ap")
    cv = cvs[0]
    return Answer(
        qid="G59",
        title="Issued check",
        summary=f"Check {cv.check_no} was issued for {cv.cv_number} to {cv.payee.name} ({money_metric('x', cv.net_amount)['value']}).",
        metrics=[
            metric("Check no", cv.check_no, "text"),
            money_metric("Amount", cv.net_amount),
            metric("CV", cv.cv_number, "text"),
        ],
        module="ap",
    )


def check_status(ctx, e) -> Answer:
    cvs = _cvs(ctx, e)
    if not cvs:
        return Answer(qid="G60", title="Check status", summary="No Check Voucher found for this document.", module="ap")
    cv = cvs[0]
    disb = getattr(cv, "disbursement", None)
    stage = disb.status if disb else ("cleared" if cv.status == "cleared" else "not released yet")
    return Answer(
        qid="G60",
        title="Check status",
        summary=f"Check {cv.check_no or '—'} on {cv.cv_number}: {stage}.",
        metrics=[
            metric("Status", stage, "text"),
            metric("CV", cv.cv_number, "text"),
        ],
        module="ap",
    )


def actors(ctx, e) -> Answer:
    rfp, cv = _primary_doc(ctx, e)
    if rfp is None:
        return Answer(qid="G63", title="Transaction actors", summary="No document could be matched.", module="ap")
    rows = [
        ("Prepared by", _user_name(rfp.created_by)),
        ("Checked by", _user_name(rfp.checked_by)),
        ("Accounting Head", _user_name(rfp.approved_by_acctg)),
        ("Finance Head", _user_name(rfp.approved_by_fin)),
        ("CNR", _user_name(rfp.approved_by_cnr)),
        ("CV approver", _user_name(cv.approved_by) if cv else "—"),
    ]
    return Answer(
        qid="G63",
        title="Who created and approved",
        summary=f"Approval trail for RFP {rfp.ap_number}.",
        rows=[{"Role": role, "User": name} for role, name in rows if name != "—"],
        module="ap",
    )


def status(ctx, e) -> Answer:
    rfp, cv = _primary_doc(ctx, e)
    parts = []
    if rfp is not None:
        parts.append(("RFP", rfp.ap_number, rfp.status))
    if cv is not None:
        parts.append(("CV", cv.cv_number, cv.status))
    if not parts:
        return Answer(qid="G64", title="Payment status", summary="No payment document could be matched.", module="ap")
    return Answer(
        qid="G64",
        title="Payment status",
        summary=" · ".join(f"{kind} {num}: {st}" for kind, num, st in parts),
        metrics=[metric(kind, st, "text") for kind, _, st in parts],
        module="ap",
    )