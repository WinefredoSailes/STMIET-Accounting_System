"""Cash & bank computed answers — F (bank/cash)."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from apps.cash.models import BankAccount, BankReconciliation, CheckDisbursement, InterAccountTransfer
from apps.posting.models import GL_EFFECTIVE_STATUSES, GeneralLedger

from ..base import Answer, metric, money_metric


def _bank_balance(bank: BankAccount, end=None) -> Decimal:
    qs = GeneralLedger.objects.filter(
        account=bank.gl_account,
        entry__status__in=GL_EFFECTIVE_STATUSES,
    )
    if end:
        qs = qs.filter(transaction_date__lte=end)
    agg = qs.aggregate(debit=Sum("debit"), credit=Sum("credit"))
    return (agg["debit"] or Decimal("0.00")) - (agg["credit"] or Decimal("0.00"))


def bank_balance(ctx, e) -> Answer:
    bank = e.bank
    bal = _bank_balance(bank)
    return Answer(
        qid="F46",
        title="Bank balance",
        summary=f"{bank.code} — {bank.bank_name} {bank.account_number}: {money_metric('x', bal)['value']}.",
        metrics=[
            money_metric("Book balance", bal),
            metric("Bank", f"{bank.code} {bank.bank_name}".strip(), "text"),
        ],
        links=[{"url": "/ui/cash/banks/", "label": "Bank accounts"}],
        module="cash",
    )


def total_cash(ctx, e) -> Answer:
    banks = BankAccount.objects.filter(is_active=True).order_by("code")
    per_bank = []
    total = Decimal("0.00")
    for b in banks:
        bal = _bank_balance(b)
        per_bank.append((b, bal))
        total += bal
    if not per_bank:
        return Answer(
            qid="F47",
            title="Total cash",
            summary="No active bank accounts found.",
            metrics=[money_metric("Total cash", Decimal("0.00"))],
            module="cash",
        )
    return Answer(
        qid="F47",
        title="Total cash",
        summary=f"Total cash across {len(per_bank)} active account(s): {money_metric('x', total)['value']}.",
        metrics=[money_metric("Total cash", total), metric("Accounts", len(per_bank), "count")],
        rows=[{"Bank": f"{b.code} — {b.bank_name}".strip(), "Balance": f"₱{bal:,.2f}"} for b, bal in per_bank],
        module="cash",
    )


def _bank_gl(bank, ctx, side: str):
    start, end = _windows(ctx)
    qs = GeneralLedger.objects.filter(
        account=bank.gl_account,
        entry__status__in=GL_EFFECTIVE_STATUSES,
        **({f"{side}__gt": Decimal("0.00")}),
    ).select_related("entry")
    if start:
        qs = qs.filter(transaction_date__gte=start)
    if end:
        qs = qs.filter(transaction_date__lte=end)
    return qs.order_by("-transaction_date", "-id")


def _windows(ctx):
    period = ctx.entities.period
    return (period.start, period.end) if period else (None, None)


def bank_payments(ctx, e) -> Answer:
    rows = list(_bank_gl(e.bank, ctx, "credit")[:10])
    total = sum(r.credit for r in rows)
    return Answer(
        qid="F48",
        title="Bank payments",
        summary=f"{len(rows)} payment line(s) from {e.bank.code} shown, totaling {money_metric('x', total)['value']} in this window.",
        metrics=[money_metric("Payments (shown)", total)],
        rows=[
            {"Date": r.transaction_date.isoformat(), "Entry": r.entry.entry_no, "Doc": r.entry.source_doc_no or "—", "Amount": f"₱{r.credit:,.2f}"}
            for r in rows
        ],
        module="cash",
    )


def bank_deposits(ctx, e) -> Answer:
    rows = list(_bank_gl(e.bank, ctx, "debit")[:10])
    total = sum(r.debit for r in rows)
    return Answer(
        qid="F49",
        title="Bank deposits",
        summary=f"{len(rows)} deposit line(s) into {e.bank.code} totaling {money_metric('x', total)['value']} in this window.",
        metrics=[money_metric("Deposits (shown)", total)],
        rows=[
            {"Date": r.transaction_date.isoformat(), "Entry": r.entry.entry_no, "Doc": r.entry.source_doc_no or "—", "Amount": f"₱{r.debit:,.2f}"}
            for r in rows
        ],
        module="cash",
    )


def outstanding_checks(ctx, e) -> Answer:
    qs = CheckDisbursement.objects.select_related("cv", "cv__payee", "cv__bank_account").exclude(status="cleared")
    if e.bank is not None:
        qs = qs.filter(clearing_bank_account=e.bank)
    rows = list(qs[:15])
    total = sum(r.cv.gross_amount for r in rows)
    return Answer(
        qid="F50",
        title="Outstanding checks",
        summary=f"{len(rows)} check(s) not yet cleared, totaling {money_metric('x', total)['value']}.",
        metrics=[money_metric("Outstanding total", total), metric("Checks", len(rows), "count")],
        rows=[
            {"CV": r.cv.cv_number, "Check": r.cv.check_no or "—", "Payee": r.cv.payee.name, "Date": r.cv.cv_date.isoformat(), "Status": r.status, "Amount": f"₱{r.cv.gross_amount:,.2f}"}
            for r in rows
        ],
        module="cash",
    )


def cleared_checks(ctx, e) -> Answer:
    qs = CheckDisbursement.objects.filter(status="cleared").select_related("cv", "cv__payee").order_by("-cleared_at")
    if e.bank is not None:
        qs = qs.filter(clearing_bank_account=e.bank)
    rows = list(qs[:15])
    total = sum(r.cv.gross_amount for r in rows)
    return Answer(
        qid="F51",
        title="Cleared checks",
        summary=f"{len(rows)} cleared check(s), totaling {money_metric('x', total)['value']}.",
        metrics=[money_metric("Cleared total", total), metric("Checks", len(rows), "count")],
        rows=[
            {"CV": r.cv.cv_number, "Check": r.cv.check_no or "—", "Payee": r.cv.payee.name, "Cleared": r.cleared_at.date().isoformat() if r.cleared_at else "—", "Amount": f"₱{r.cv.gross_amount:,.2f}"}
            for r in rows
        ],
        module="cash",
    )


def unreconciled(ctx, e) -> Answer:
    qs = BankReconciliation.objects.filter(status="open").select_related("bank_account", "cycle").exclude(difference=Decimal("0.00"))
    if e.bank is not None:
        qs = qs.filter(bank_account=e.bank)
    rows = list(qs.order_by("-cycle__cycle_end")[:12])
    return Answer(
        qid="F52",
        title="Unreconciled transactions",
        summary=f"{len(rows)} open bank reconciliation(s) with a difference.",
        metrics=[metric("Open recons", len(rows), "count")],
        rows=[
            {"Bank": r.bank_account.code, "Cycle": f"{r.cycle.cycle_start} — {r.cycle.cycle_end}", "Book": f"₱{r.book_balance:,.2f}", "Bank": f"₱{r.bank_statement_balance:,.2f}", "Diff": f"₱{r.difference:,.2f}"}
            for r in rows
        ],
        module="cash",
    )


def book_vs_bank(ctx, e) -> Answer:
    qs = BankReconciliation.objects.select_related("bank_account", "cycle")
    if e.bank is not None:
        qs = qs.filter(bank_account=e.bank)
    latest: dict = {}
    for r in qs.order_by("-cycle__cycle_end"):
        if r.bank_account_id not in latest:
            latest[r.bank_account_id] = r
    rows = list(latest.values())
    return Answer(
        qid="F53",
        title="Book vs bank",
        summary=f"Latest reconciliation difference for each bank account.",
        metrics=[metric("Accounts", len(rows), "count")],
        rows=[
            {"Bank": r.bank_account.code, "Book": f"₱{r.book_balance:,.2f}", "Bank stmt": f"₱{r.bank_statement_balance:,.2f}", "Diff": f"₱{r.difference:,.2f}", "Status": r.status}
            for r in rows[:10]
        ],
        module="cash",
    )


def transfers(ctx, e) -> Answer:
    qs = InterAccountTransfer.objects.select_related("from_account", "to_account").order_by("-transfer_date")
    rows = list(qs[:15])
    total = sum(r.amount for r in rows)
    return Answer(
        qid="F54",
        title="Bank transfers",
        summary=f"{len(rows)} fund transfer(s) shown, totaling {money_metric('x', total)['value']}.",
        metrics=[money_metric("Transfers (shown)", total), metric("Transfers", len(rows), "count")],
        rows=[
            {"Date": r.transfer_date.isoformat(), "From": r.from_account.code, "To": r.to_account.code, "Amount": f"₱{r.amount:,.2f}", "Status": r.status}
            for r in rows
        ],
        links=[{"url": "/ui/cash/transfers/", "label": "Transfer list"}],
        module="cash",
    )