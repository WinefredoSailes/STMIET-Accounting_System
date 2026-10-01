"""Financial-report answers — K (net income, statements, trial balance).

Templates and trial-balance logic come from the reporting service (the UI's
source of truth); ``generate`` is an idempotent upsert of the same snapshot
the screens build, so figures always match. Totals are consolidated across
every company: each statement is generated per company and the GRAND columns
are summed (companies are independent books).

The cash-flow figures mirror ADR-031/CashFlowService arithmetic **read-only**
(no snapshot row is written from chat).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.cash.models import ActivityType, CashCycleActivity, WeeklyCashCycle
from apps.posting.models import GL_EFFECTIVE_STATUSES, GeneralLedger
from apps.reporting.services import FinancialStatementService, TrialBalanceService

from ..base import Answer, metric, money_metric


def _window(ctx):
    period = ctx.entities.period
    return (period.start, period.end) if period else (date.today().replace(day=1), date.today())


def _fs_lines(ctx, statement_type: str) -> list[dict]:
    """Consolidated non-hidden statement lines for the period (all companies).

    Templates are data (StatementTemplate); when they are missing the caller
    falls back to direct GL arithmetic instead of erroring the chat.
    """
    start, end = _window(ctx)
    by_key: dict[str, dict] = {}
    for company in ctx.companies:
        try:
            fs = FinancialStatementService.generate(
                company=company,
                statement_type=statement_type,
                period_start=start,
                period_end=end,
            )
        except Exception:
            continue
        for line in fs.data:
            key = line["key"]
            col = by_key.setdefault(
                key, {"title": line["title"], "line_no": line["line_no"], "is_subtotal": line["is_subtotal"], "amount": Decimal("0.00")}
            )
            try:
                col["amount"] += Decimal(line["amounts"].get("GRAND", "0"))
            except Exception:
                pass
    return [v for k, v in sorted(by_key.items(), key=lambda kv: kv[1]["line_no"])]


def _line_amount(lines, *keywords) -> Decimal | None:
    for ln in lines:
        t = (ln["title"] or "").lower()
        if all(k in t for k in keywords):
            return ln["amount"]
    return None


def _gl_signed(companies, start, end, types: tuple) -> Decimal:
    qs = GeneralLedger.objects.filter(
        entry__status__in=GL_EFFECTIVE_STATUSES,
        entry__company__in=companies,
        transaction_date__gte=start,
        transaction_date__lte=end,
        account__account_type__in=types,
    )
    rows = qs.values("account__normal_balance").annotate(d=Sum("debit"), c=Sum("credit"))
    total = Decimal("0.00")
    for r in rows:
        diff = (r["c"] or Decimal("0.00")) - (r["d"] or Decimal("0.00"))
        total += diff if r["account__normal_balance"] == "credit" else -diff
    return total


def _period_context(ctx) -> tuple[str, str, str]:
    start, end = _window(ctx)
    label = ctx.entities.period.label() if ctx.entities.period else f"{start:%B %Y}"
    return start, end, label, ctx.entities.period_note


def _statement_answer(ctx, statement_type, qid, title_label) -> Answer:
    start, end, label, note = _period_context(ctx)
    lines = _fs_lines(ctx, statement_type)
    # All template lines in order (subtotals included — they summarize the
    # statement); the card caps the visible rows.
    rows = [
        {"Line": ln["title"], "Amount": f"₱{ln['amount']:,.2f}"}
        for ln in lines[:14]
    ]
    return Answer(
        qid=qid,
        title=title_label,
        summary=f"{title_label} for {label}.",
        rows=rows,
        note=note,
        links=[{"url": f"/reports/{statement_type}/print/", "label": f"Print {title_label}"}],
        module="reporting",
    )


def net_income(ctx, e) -> Answer:
    start, end, label, note = _period_context(ctx)
    lines = _fs_lines(ctx, "is")
    total = _line_amount(lines, "net income", "loss") or _line_amount(lines, "net income") or _line_amount(lines, "net profit")
    fallback = False
    if total is None:
        fallback = True
        revenue = _gl_signed(ctx.companies, start, end, ("revenue", "contra_revenue"))
        expenses = _gl_signed(ctx.companies, start, end, ("expense", "contra_expense"))
        total = revenue - expenses
    return Answer(
        qid="K90",
        title="Net income",
        summary=(
            f"Net income for {label}: {money_metric('x', total)['value']}."
            + (" Derived from the GL (income statement template line not found)." if fallback else "")
        ),
        metrics=[money_metric("Net income", total), metric("Period", label, "text")],
        note=note,
        module="reporting",
    )


def revenue(ctx, e) -> Answer:
    start, end, label, note = _period_context(ctx)
    lines = _fs_lines(ctx, "is")
    total = (
        _line_amount(lines, "total", "revenue")
        or _line_amount(lines, "total", "sales")
        or _line_amount(lines, "gross", "revenue")
        or _gl_signed(ctx.companies, start, end, ("revenue", "contra_revenue"))
    )
    return Answer(
        qid="K91",
        title="Total revenue",
        summary=f"Total revenue for {label}: {money_metric('x', total)['value']}.",
        metrics=[money_metric("Revenue", total), metric("Period", label, "text")],
        note=note,
        module="reporting",
    )


def expenses(ctx, e) -> Answer:
    start, end, label, note = _period_context(ctx)
    lines = _fs_lines(ctx, "is")
    total = (
        _line_amount(lines, "total", "expenses")
        or _line_amount(lines, "total", "operating")
        or _line_amount(lines, "total")
        or _gl_signed(ctx.companies, start, end, ("expense", "contra_expense"))
    )
    return Answer(
        qid="K92",
        title="Total expenses",
        summary=f"Total expenses for {label}: {money_metric('x', total)['value']}.",
        metrics=[money_metric("Expenses", total), metric("Period", label, "text")],
        note=note,
        module="reporting",
    )


def total_receivable(ctx, e) -> Answer:
    from apps.ar.models import ARInvoice

    per_customer: dict = {}
    for inv in ARInvoice.objects.filter(status__in=("open", "partially_paid")).select_related("customer"):
        bal = inv.balance
        if bal <= 0:
            continue
        per_customer[inv.customer.name] = per_customer.get(inv.customer.name, Decimal("0.00")) + bal
    total = sum(per_customer.values())
    top = sorted(per_customer.items(), key=lambda kv: -kv[1])[:8]
    return Answer(
        qid="K93",
        title="Total receivable",
        summary=f"Total receivable: {money_metric('x', total)['value']} across {len(per_customer)} customer(s).",
        metrics=[money_metric("Total receivable", total), metric("Customers", len(per_customer), "count")],
        rows=[{"Customer": name, "Balance": f"₱{amount:,.2f}"} for name, amount in top],
        module="reporting",
    )


def total_payable(ctx, e) -> Answer:
    from .ap import _open_payables

    rows = _open_payables(date.today())
    total = sum(r["balance"] for r in rows)
    per_supplier: dict = {}
    for r in rows:
        per_supplier[r["payee"]] = per_supplier.get(r["payee"], Decimal("0.00")) + r["balance"]
    top = sorted(per_supplier.items(), key=lambda kv: -kv[1])[:8]
    return Answer(
        qid="K94",
        title="Total payable",
        summary=f"Total payable: {money_metric('x', total)['value']} across {len(per_supplier)} supplier(s).",
        metrics=[money_metric("Total payable", total), metric("Suppliers", len(per_supplier), "count")],
        rows=[{"Supplier": name, "Balance": f"₱{amount:,.2f}"} for name, amount in top],
        module="reporting",
    )


def trial_balance(ctx, e) -> Answer:
    end = ctx.entities.period.end if ctx.entities.period else None
    merged: dict = {}
    for company in ctx.companies:
        for row in TrialBalanceService.rows(company, as_of=end):
            code = row["code"]
            merged[code] = {
                "code": code,
                "name": row["name"],
                "account_type": row.get("account_type", ""),
                "balance": (merged.get(code, {}).get("balance", Decimal("0.00")) + row["balance"]),
            }
    nonzero = sorted(merged.values(), key=lambda r: r["code"])
    nonzero = [r for r in nonzero if r["balance"] != 0]
    return Answer(
        qid="K96",
        title="Trial balance",
        summary=f"{len(nonzero)} account(s) with a balance.",
        metrics=[metric("Accounts", len(nonzero), "count")],
        rows=[{"Code": r["code"], "Account": r["name"], "Balance": f"₱{r['balance']:,.2f}"} for r in nonzero[:14]],
        links=[{"url": "/reports/trial-balance/print/", "label": "Print trial balance"}],
        module="reporting",
    )


def income_statement(ctx, e) -> Answer:
    return _statement_answer(ctx, "is", "K97", "Income statement")


def balance_sheet(ctx, e) -> Answer:
    return _statement_answer(ctx, "sfp", "K98", "Balance sheet")


def cash_flow(ctx, e) -> Answer:
    """Read-only mirror of ADR-031 arithmetic (see CashFlowService.generate)."""
    start, end, label, note = _period_context(ctx)
    cycles = WeeklyCashCycle.objects.filter(
        segment__company__in=ctx.companies, cycle_start__gte=start, cycle_end__lte=end
    )
    totals = dict(
        CashCycleActivity.objects.filter(cycle__in=cycles)
        .values_list("activity_type")
        .annotate(total=Sum("amount"))
    )
    totals = {k: v or Decimal("0.00") for k, v in totals.items()}

    def _t(key):
        return totals.get(key, Decimal("0.00"))

    collections = _t(ActivityType.COLLECTION_DIST) + _t(ActivityType.OTHER_COLLECTION)
    operating_outflows = (
        _t(ActivityType.SUPPLIER_PAYMENT) + _t(ActivityType.RFP_AP)
        + _t(ActivityType.PCF_REPLEN) + _t(ActivityType.OTHER_PAYMENT)
    )
    capex = _t(ActivityType.CAPEX)
    borrowed = _t(ActivityType.BORROWED)
    loan_cleared = _t(ActivityType.LOAN_CLEARED)
    net_operating = collections - operating_outflows
    net_investing = -capex
    net_financing = borrowed - loan_cleared
    net_change = net_operating + net_investing + net_financing

    # opening = latest cycle ending before the period; closing = latest cycle in period
    opening_map: dict = {}
    for sid in set(
        WeeklyCashCycle.objects.filter(
            segment__company__in=ctx.companies, cycle_end__lt=start
        ).values_list("segment_id", flat=True)
    ):
        last = WeeklyCashCycle.objects.filter(
            segment_id=sid, cycle_end__lt=start
        ).order_by("-cycle_start").first()
        if last:
            opening_map[sid] = last.closing_balance
    closing_map: dict = {}
    for sid in set(cycles.values_list("segment_id", flat=True)):
        last = cycles.filter(segment_id=sid).order_by("-cycle_start").first()
        if last:
            closing_map[sid] = last.closing_balance
    beginning = sum(opening_map.values()) or Decimal("0.00")
    ending = sum(closing_map.values()) or Decimal("0.00")
    rows = [
        {"Item": "Collections", "Amount": f"₱{collections:,.2f}"},
        {"Item": "Payments (operating)", "Amount": f"₱{operating_outflows:,.2f}"},
        {"Item": "Capital acquisitions", "Amount": f"₱{capex:,.2f}"},
        {"Item": "Loans received", "Amount": f"₱{borrowed:,.2f}"},
        {"Item": "Loans cleared", "Amount": f"₱{loan_cleared:,.2f}"},
        {"Item": "Net operating", "Amount": f"₱{net_operating:,.2f}"},
        {"Item": "Net investing", "Amount": f"₱{net_investing:,.2f}"},
        {"Item": "Net financing", "Amount": f"₱{net_financing:,.2f}"},
        {"Item": "Net change", "Amount": f"₱{net_change:,.2f}"},
        {"Item": "Beginning cash", "Amount": f"₱{beginning:,.2f}"},
        {"Item": "Ending cash", "Amount": f"₱{ending:,.2f}"},
    ]
    return Answer(
        qid="K99",
        title="Cash flow statement",
        summary=f"Cash flow for {label}: net change {money_metric('x', net_change)['value']}, ending {money_metric('x', ending)['value']}.",
        metrics=[
            money_metric("Net change", net_change),
            money_metric("Ending cash", ending),
            money_metric("Beginning cash", beginning),
        ],
        rows=rows,
        note=note,
        module="reporting",
    )


def compare_periods(ctx, e) -> Answer:
    current = ctx.entities.period
    if current is None:
        return Answer(qid="K100", title="Period comparison", summary="No period could be resolved for comparison.", module="reporting")
    prev = current.previous()
    start_c, end_c = current.start, current.end
    start_p, end_p = prev.start, prev.end
    cur_net = _gl_signed(ctx.companies, start_c, end_c, ("revenue", "contra_revenue")) - _gl_signed(ctx.companies, start_c, end_c, ("expense", "contra_expense"))
    prev_net = _gl_signed(ctx.companies, start_p, end_p, ("revenue", "contra_revenue")) - _gl_signed(ctx.companies, start_p, end_p, ("expense", "contra_expense"))
    cur_rev = _gl_signed(ctx.companies, start_c, end_c, ("revenue", "contra_revenue"))
    prev_rev = _gl_signed(ctx.companies, start_p, end_p, ("revenue", "contra_revenue"))
    cur_exp = _gl_signed(ctx.companies, start_c, end_c, ("expense", "contra_expense"))
    prev_exp = _gl_signed(ctx.companies, start_p, end_p, ("expense", "contra_expense"))
    result_rows = [
        {"Measure": "Net income", "Current": f"₱{cur_net:,.2f}", "Previous": f"₱{prev_net:,.2f}", "Change": f"₱{cur_net - prev_net:,.2f}"},
        {"Measure": "Total revenue", "Current": f"₱{cur_rev:,.2f}", "Previous": f"₱{prev_rev:,.2f}", "Change": f"₱{cur_rev - prev_rev:,.2f}"},
        {"Measure": "Total expenses", "Current": f"₱{cur_exp:,.2f}", "Previous": f"₱{prev_exp:,.2f}", "Change": f"₱{cur_exp - prev_exp:,.2f}"},
    ]
    return Answer(
        qid="K100",
        title="Period comparison",
        summary=f"{current.label()} vs {prev.label()}.",
        metrics=[metric("Compared", f"{current.label()} vs {prev.label()}", "text")],
        rows=result_rows,
        note=ctx.entities.period_note,
        module="reporting",
    )