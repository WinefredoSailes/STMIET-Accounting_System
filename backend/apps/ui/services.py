"""Query helpers for the server-rendered UI.

Thin read models over the bounded-context apps. The UI never mutates data
directly — mutations go through the context services (via views.py), exactly
as the DRF API does.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.money import money
from apps.foundation.calendar import cycle_range_for
from apps.foundation.models import FiscalPeriod, Segment
from apps.posting.models import GL_EFFECTIVE_STATUSES, JournalEntry, PostingStatus
from apps.reporting.models import StatementType
from apps.reporting.services import MonthEndCloseService, StatementTemplateService, TrialBalanceService as TBSvc


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def month_end_close_context():
    """The MonthEndClose for the current open fiscal period, if any."""
    today = date.today()
    period = (
        FiscalPeriod.objects.filter(start_date__lte=today, end_date__gte=today, is_closed=False)
        .order_by("-period_no")
        .first()
    )
    if not period:
        return None
    return MonthEndCloseService.get_or_create(period)


# ---------------------------------------------------------------------------
# Executive dashboard (4 zones)
# ---------------------------------------------------------------------------

COGS_PREFIXES = ("50", "51", "52")


def _fiscal_window(company, today):
    """(fy_start, fy_end) for the fiscal year containing today (ADR-013)."""
    from apps.foundation.models import FiscalYear

    fy = (
        FiscalYear.objects.filter(
            company=company, start_date__lte=today, end_date__gte=today
        )
        .order_by("-start_date")
        .first()
    )
    if fy:
        return fy.start_date, fy.end_date
    return date(today.year, 1, 1), date(today.year, 12, 31)


def _annual_segment_keys(balances, account_codes):
    """Sum one account group across selected accounts per GL segment key."""
    totals = {}
    for acc in account_codes:
        per_seg = balances.get(acc.code, {})
        for seg, val in per_seg.items():
            key = seg or "ALL"
            totals[key] = totals.get(key, Decimal("0.00")) + val
    return totals


def executive_dashboard_context(*, segment=None, user=None):
    """The executive finance view: 8 KPIs, 4 charts, 2 aging snapshots,
    2 operational panels — all derived live from the posted GL.

    ``segment`` filters GL-derived figures to one Segment.code (None = all).
    """
    from apps.core.approvals import pending_approval_count
    from apps.foundation.models import Account, Company
    from apps.posting.models import GeneralLedger
    from apps.posting.services import ReversalService

    company = Company.objects.first()
    today = date.today()
    fy_start, fy_end = _fiscal_window(company, today)
    period_end = min(today, fy_end)

    # ---- GL balances: activity (revenue/expense) + ending (cash position) --
    ytd = TBSvc.segment_balances(company, start=fy_start, end=period_end)
    ending = TBSvc.segment_balances(company, end=period_end)

    accounts = list(Account.objects.filter(is_postable=True))
    accounts_by_code = {a.code: a for a in accounts}
    revenue_codes = [a for a in accounts if a.account_type == "revenue"]
    expense_codes = [a for a in accounts if a.account_type == "expense"]
    cogs_codes = [a for a in expense_codes if a.code.startswith(COGS_PREFIXES)]
    cash_codes = [
        a for a in accounts
        if a.account_type == "asset" and a.code.startswith("10")
    ]

    def segment_total(bal_map, account_list):
        """Signed sum over the requested account list, honoring the segment filter."""
        total = Decimal("0.00")
        for acc in account_list:
            per_seg = bal_map.get(acc.code, {})
            if segment:
                total += per_seg.get(segment, Decimal("0.00"))
            else:
                total += sum(per_seg.values())
        return money(total)

    revenue_ytd = segment_total(ytd, revenue_codes)
    revenue_sales_ytd = segment_total(
        ytd,
        [a for a in revenue_codes if not a.code.startswith(("405", "415", "425"))],
    )
    expenses_ytd = segment_total(ytd, expense_codes)
    cogs_ytd = segment_total(ytd, cogs_codes)
    cash_position = segment_total(ending, cash_codes)
    net_income_ytd = money(revenue_ytd - expenses_ytd)
    gpm = money((revenue_sales_ytd - cogs_ytd) * 100 / revenue_sales_ytd) if revenue_sales_ytd else Decimal("0.00")
    npm = money(net_income_ytd * 100 / revenue_ytd) if revenue_ytd else Decimal("0.00")

    # ---- Monthly series (rolling 12 months ending this month) --------------
    months = []
    origin = date(today.year, today.month, 1)
    for _ in range(12):
        months.append((origin.year, origin.month))
        origin = (origin.replace(day=1) - timedelta(days=1)).replace(day=1)
    months.reverse()

    revenue_series, expense_series = [], []
    cash_in_series, cash_out_series = [], []
    for yy, mm in months:
        first = date(yy, mm, 1)
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        if first > today:
            revenue_series.append(0.0)
            expense_series.append(0.0)
            cash_in_series.append(0.0)
            cash_out_series.append(0.0)
            continue
        # This month counts as month-to-date, not zero (the old `last > today`
        # guard dropped the whole current month out of every chart).
        last = min(last, today)
        mbal = TBSvc.segment_balances(company, start=first, end=last)
        rev = segment_total(mbal, revenue_codes)
        exp = segment_total(mbal, expense_codes)
        revenue_series.append(float(rev))
        expense_series.append(float(exp))
        # Cash movement straight from GL debits/credits on 10xxx accounts.
        qs = GeneralLedger.objects.filter(
            entry__status__in=GL_EFFECTIVE_STATUSES,
            entry__company=company,
            account__code__startswith="10",
            account__account_type="asset",
            transaction_date__gte=first,
            transaction_date__lte=last,
        )
        if segment:
            qs = qs.filter(segment__code=segment)
        agg = qs.aggregate(d=Sum("debit"), c=Sum("credit"))
        cash_in_series.append(float(agg["d"] or 0))
        cash_out_series.append(float(agg["c"] or 0))

    # Prior-month trend for the KPI arrows (this month vs last month).
    last_full = revenue_series[-2] if len(revenue_series) >= 2 else None

    def trend(current, prior):
        if prior is None or not prior:
            return {"dir": "flat", "pct": 0.0}
        pct = (current - prior) / abs(prior) * 100
        return {"dir": "up" if pct > 0.1 else ("down" if pct < -0.1 else "flat"), "pct": round(pct, 1)}

    # ---- Segment performance -----------------------------------------------
    seg_rev = _annual_segment_keys(ytd, revenue_codes)
    seg_exp = _annual_segment_keys(ytd, expense_codes)
    segment_codes_list = [s.code for s in Segment.objects.order_by("code")]
    seg_revenue_series = [float(seg_rev.get(code, 0)) for code in segment_codes_list]
    seg_expense_series = [float(seg_exp.get(code, 0)) for code in segment_codes_list]

    # ---- Expense breakdown (by category name, top 6 + Other) ---------------
    def category_of(acc):
        return (acc.category or "").strip() or "Other"

    bucket = {}
    for acc in expense_codes:
        per_seg = ytd.get(acc.code, {})
        value = per_seg.get(segment, Decimal("0.00")) if segment else sum(per_seg.values())
        if not value:
            continue
        bucket[category_of(acc)] = bucket.get(category_of(acc), Decimal("0.00")) + value
    ranked = sorted(bucket.items(), key=lambda kv: kv[1], reverse=True)
    top, rest = ranked[:6], ranked[6:]
    doughnut_labels = [k for k, _ in top]
    doughnut_values = [float(v) for _, v in top]
    if rest:
        doughnut_labels.append("Other")
        doughnut_values.append(float(sum(v for _, v in rest)))

    # ---- AR / AP outstanding + aging snapshots ------------------------------
    from apps.ar.models import ARInvoice
    from apps.ap.models import CheckVoucher, RFPDocument

    ar_qs = ARInvoice.objects.filter(status__in=("open", "partially_paid"))
    if segment:
        ar_qs = ar_qs.filter(segment__code=segment)
    ar_outstanding = money(sum((inv.balance for inv in ar_qs), Decimal("0.00")))
    ar_count = ar_qs.count()

    cleared = {
        row["rfp_id"]: (row["paid"] or Decimal("0.00"))
        for row in (
            CheckVoucher.objects.filter(journal_entry__isnull=False)
            .exclude(rfp__isnull=True)
            .values("rfp_id")
            .annotate(paid=Sum("gross_amount"))
        )
    }
    rfp_qs = RFPDocument.objects.filter(status="posted")
    if segment:
        rfp_qs = rfp_qs.filter(segment__code=segment)
    ap_outstanding = money(
        sum((rfp.amount - cleared.get(rfp.id, Decimal("0.00")) for rfp in rfp_qs), Decimal("0.00"))
    )
    ap_count = rfp_qs.count()

    ar_aging = aging_context(today)
    ap_aging = ap_aging_context(today)

    # ---- Pipeline + close status -------------------------------------------
    pipeline = rfp_summary()
    close = month_end_close_context()
    reversal_pending = ReversalService.pending_count()
    waiting_on_you = pending_approval_count(user) if user else 0

    kpis = [
        {
            "key": "revenue", "label": "Revenue YTD", "value": revenue_ytd,
            "trend": trend(revenue_series[-1], last_full),
            "href_name": "ui:statement", "href_args": ["is"],
            "sub": f"FY {fy_start:%Y}",
            "icon": "trending-up", "accent": "bg-emerald-500", "bubble": "bg-emerald-50 text-emerald-600",
        },
        {
            "key": "expenses", "label": "Expenses YTD", "value": expenses_ytd,
            "trend": trend(expense_series[-1], expense_series[-2] if len(expense_series) >= 2 else None),
            "href_name": "ui:statement", "href_args": ["te"],
            "sub": f"of which COS \u20b1{cogs_ytd:,.2f}",
            "icon": "trending-down", "accent": "bg-rose-500", "bubble": "bg-rose-50 text-rose-600",
        },
        {
            "key": "net_income", "label": "Net Income YTD", "value": net_income_ytd,
            "trend": {"dir": "up" if net_income_ytd >= 0 else "down", "pct": float(npm)},
            "href_name": "ui:statement", "href_args": ["is"],
            "sub": f"{abs(npm)}% of revenue",
            "icon": "document-chart-bar", "accent": "bg-brand-500", "bubble": "bg-brand-50 text-brand-600",
        },
        {
            "key": "cash", "label": "Cash Position", "value": cash_position,
            "trend": {"dir": "flat", "pct": 0.0}, "trend_note": "Today",
            "href_name": "ui:bank_list", "href_args": [],
            "sub": "Banks + PCF + cash on hand",
            "icon": "banknotes", "accent": "bg-amber-500", "bubble": "bg-amber-50 text-amber-600",
        },
        {
            "key": "gpm", "label": "Gross Profit Margin", "value": gpm, "suffix": "%",
            "trend": {"dir": "flat", "pct": 0.0}, "trend_note": "FY ratio",
            "href_name": "ui:statement", "href_args": ["is"],
            "sub": "(Net sales − COS) ÷ net sales",
            "icon": "calculator", "accent": "bg-emerald-500", "bubble": "bg-emerald-50 text-emerald-600",
        },
        {
            "key": "npm", "label": "Net Profit Margin", "value": npm, "suffix": "%",
            "trend": {"dir": "flat", "pct": 0.0}, "trend_note": "FY ratio",
            "href_name": "ui:statement", "href_args": ["is"],
            "sub": "Net income ÷ revenue",
            "icon": "document-chart-bar", "accent": "bg-brand-500", "bubble": "bg-brand-50 text-brand-600",
        },
        {
            "key": "ar", "label": "AR Outstanding", "value": ar_outstanding,
            "trend": {"dir": "flat", "pct": 0.0}, "trend_note": "As of today",
            "href_name": "ui:ar_aging", "href_args": [],
            "sub": f"{ar_count} open invoice(s)",
            "icon": "clock", "accent": "bg-amber-500", "bubble": "bg-amber-50 text-amber-600",
        },
        {
            "key": "ap", "label": "AP Outstanding", "value": ap_outstanding,
            "trend": {"dir": "flat", "pct": 0.0}, "trend_note": "As of today",
            "href_name": "ui:ap_aging", "href_args": [],
            "sub": f"{ap_count} posted RFP(s)",
            "icon": "credit-card", "accent": "bg-rose-500", "bubble": "bg-rose-50 text-rose-600",
        },
    ]

    # Screen access (ADR-047): drill-down hrefs resolve only for screens the
    # viewer can open, so a narrowed account (e.g. dashboard-only COO) gets
    # read-only cards instead of links that would dead-end in a 403.
    from .screens import SCREEN_KEYS, effective_screens

    allowed = set(effective_screens(user)) if user is not None else set(SCREEN_KEYS)
    kpi_screens = {
        "revenue": "statement", "expenses": "statement", "net_income": "statement",
        "cash": "bank_list", "gpm": "statement", "npm": "statement",
        "ar": "ar_aging", "ap": "ap_aging",
    }
    from django.urls import NoReverseMatch, reverse

    for kpi in kpis:
        kpi["screen"] = kpi_screens[kpi["key"]]
        kpi["href"] = None
        if kpi["screen"] in allowed:
            try:
                kpi["href"] = reverse(kpi["href_name"], args=kpi["href_args"] or None)
            except NoReverseMatch:
                kpi["href"] = None

    chart = {
        "labels": [f"{yy}-{mm:02d}" for yy, mm in months],
        "month_labels": [date(yy, mm, 1).strftime("%b") for yy, mm in months],
        "revenue": revenue_series,
        "expenses": expense_series,
        "cash_in": cash_in_series,
        "cash_out": cash_out_series,
        "segment_codes": segment_codes_list,
        "segment_revenue": seg_revenue_series,
        "segment_expenses": seg_expense_series,
        "expense_labels": doughnut_labels,
        "expense_values": doughnut_values,
    }

    return {
        "kpis": kpis,
        "allowed_screens": allowed,
        "chart": chart,
        "ar_aging": ar_aging,
        "ap_aging": ap_aging,
        "pipeline": pipeline,
        "close": close,
        "reversal_pending_count": reversal_pending,
        "waiting_on_you": waiting_on_you,
        "segments": segment_codes_list,
        "segment": segment or "",
        "fy_label": f"{fy_start:%Y}",
        "fy_start": fy_start,
        "fy_end": fy_end,
        "pending_count": pending_count(),
    }


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------


def list_entries(*, limit=100):
    return list(
        JournalEntry.objects.select_related("company", "segment")
        .order_by("-transaction_date", "-id")[:limit]
    )


# ---------------------------------------------------------------------------
# Trial balance / statements
# ---------------------------------------------------------------------------


class TrialBalanceService:
    @staticmethod
    def rows(*, as_of: str, segment: str | None = None):
        """Rows + (debit_total, credit_total) for the TB screen."""
        from apps.foundation.models import Account, Company

        company = Company.objects.first()
        bal = TBSvc.segment_balances(company, end=date.fromisoformat(as_of))
        rows = []
        for acc in Account.objects.filter(is_postable=True).order_by("code"):
            if segment and acc.segment not in (segment, "ALL"):
                continue
            per_seg = bal.get(acc.code, {})
            total = sum(per_seg.values()) if per_seg else 0
            if not total:
                continue
            rows.append(
                {
                    "id": acc.id,
                    "code": acc.code,
                    "name": acc.name,
                    "segment": acc.segment,
                    "normal_balance": acc.normal_balance,
                    "balance": total,
                }
            )
        debit = sum(r["balance"] for r in rows if r["balance"] >= 0)
        credit = sum(-r["balance"] for r in rows if r["balance"] < 0)
        return rows, (debit, credit)


class StatementService:
    """Generate / view financial statements from the UI."""

    STATEMENT_LABELS = {
        "is": "Income Statement",
        "sfp": "Statement of Financial Position",
        "cos": "Statement of Cost of Sales",
        "te": "Statement of Total Expenses",
        "soce": "Statement of Changes in Equity",
    }

    @classmethod
    def generate(cls, *, statement_type, period_start, period_end, user=None, inputs=None):
        from apps.reporting.services import FinancialStatementService

        StatementTemplateService.seed_defaults()  # layouts must exist to generate
        # Chain the statements (ADR-011): the IS net profit is fed into the
        # SFP equity and the SOCE as their INPUT-mode rows, so the UI mirrors
        # the DRF run_all behavior instead of rendering zeros.
        if inputs is None and statement_type in ("sfp", "soce"):
            is_fs = FinancialStatementService.generate(
                company=cls._company(),
                statement_type=StatementType.INCOME_STATEMENT,
                period_start=date.fromisoformat(period_start),
                period_end=date.fromisoformat(period_end),
                user=user,
            )
            profited_key = "eq_net_profit" if statement_type == "sfp" else "soce_net_profit"
            inputs = {
                profited_key: is_fs.rows_by_key()["net_profit"]["amounts"]["GRAND"]
            }
        return FinancialStatementService.generate(
            company=cls._company(),
            statement_type=statement_type,
            period_start=date.fromisoformat(period_start),
            period_end=date.fromisoformat(period_end),
            inputs=inputs,
            user=user,
        )

    @classmethod
    def statement_context(cls, statement_type):
        """Latest generated snapshot for the statement, if any."""
        from apps.reporting.models import FinancialStatement

        StatementTemplateService.seed_defaults()  # ensure layouts exist
        latest = (
            FinancialStatement.objects.filter(
                statement_type=statement_type, company=cls._company(), segment=None
            )
            .order_by("-period_end")
            .first()
        )
        return {
            "statement_type": statement_type,
            "label": cls.STATEMENT_LABELS.get(statement_type, statement_type),
            "statement": latest,
            "rows": latest.rows_by_key() if latest else {},
            "segments": list(cls._company().segments.order_by("code")),
        }

    @staticmethod
    def _company():
        from apps.foundation.models import Company

        return Company.objects.first()


# ---------------------------------------------------------------------------
# AR
# ---------------------------------------------------------------------------


def list_customers():
    from apps.ar.models import Customer

    return Customer.objects.order_by("name")


def cash_accounts():
    """GL accounts usable as a collection/PCV cash account (asset postable)."""
    from apps.foundation.models import Account

    return Account.objects.filter(is_postable=True, account_type="asset").order_by("code")


def list_receipts(*, limit=100):
    from apps.ar.models import AcknowledgmentReceipt

    return AcknowledgmentReceipt.objects.select_related("customer", "segment").order_by("-transaction_date")[:limit]


def receipt_summary():
    """Counts/amounts by stage for the AR receipts stat cards."""
    from django.db.models import Sum

    from apps.ar.models import AcknowledgmentReceipt

    qs = AcknowledgmentReceipt.objects
    return {
        "total": qs.count(),
        "total_amount": qs.aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "posted": qs.filter(status="posted").count(),
        "posted_amount": qs.filter(status="posted").aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "submitted": qs.filter(status="submitted").count(),
        "submitted_amount": qs.filter(status="submitted").aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "draft": qs.filter(status="draft").count(),
        "draft_amount": qs.filter(status="draft").aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
    }


def si_summary():
    """Counts/amounts by state for the Sales Invoices stat cards."""
    from django.db.models import Sum

    from apps.ar.models import ARInvoice

    qs = ARInvoice.objects
    open_qs = qs.filter(status__in=("open", "partially_paid"))
    return {
        "total": qs.count(),
        "total_amount": qs.aggregate(t=Sum("total"))["t"] or Decimal("0.00"),
        "open": open_qs.count(),
        "overdue_count": sum(1 for inv in open_qs if (date.today() - inv.transaction_date).days > 60),
        "paid": qs.filter(status="paid").count(),
        "posted": qs.filter(status="posted").count(),
    }


# ---------------------------------------------------------------------------
# AP
# ---------------------------------------------------------------------------


def list_suppliers():
    from apps.ap.models import Supplier

    return Supplier.objects.prefetch_related("contacts").order_by("name")


def list_rfps(*, limit=100):
    from apps.ap.models import RFPDocument

    return RFPDocument.objects.select_related("payee", "segment").prefetch_related(
        "lines"
    ).order_by("-created_at")[:limit]


def rfp_summary():
    """Counts and payable amounts by stage for the RFP list stat cards.

    Amounts reflect the true A/P payable (AP-role credit lines, gross minus
    WHT) rather than the RFP's gross debit total — matching what the aging and
    CV prefill now use. RFPs without an AP line keep their gross amount.
    """
    from apps.ap.models import RFPDocument
    from apps.ap.services import ap_payable_map, finally_approved, rfp_payable

    total = pending = approved = posted = Decimal("0.00")
    total_n = pending_n = approved_n = 0
    for rfp in RFPDocument.objects.prefetch_related("lines"):
        payable = rfp_payable(rfp)
        total += payable
        total_n += 1
        if rfp.status == "posted":
            posted += payable
        elif finally_approved(rfp):
            approved += payable
            approved_n += 1
        elif rfp.status != "rejected":
            pending += payable
            pending_n += 1
    return {
        "total": total_n,
        "total_amount": total,
        "pending": pending_n,
        "pending_amount": pending,
        "approved": approved_n,
        "approved_amount": approved,
        "posted_amount": posted,
    }


def rfp_timeline(rfp):
    """[(status, label, holder)] for the RFP document screen (ADR-020 matrix)."""
    holders = {
        "prepared": getattr(rfp, "created_by", None),
        "submitted": None,
        "checked": rfp.checked_by,
        "acctg_approved": rfp.approved_by_acctg,
        "fin_approved": rfp.approved_by_fin,
        "cnr_approved": rfp.approved_by_cnr,
    }
    order = ["prepared", "submitted", "checked", "acctg_approved", "fin_approved"]
    from apps.ap.services import coo_required

    if coo_required(rfp):
        order.append("cnr_approved")
    labels = {
        "prepared": "Requested by",
        "submitted": "Submitted",
        "checked": "Checked / Recommending",
        "acctg_approved": "Accounting Head",
        "fin_approved": "Finance Head",
        "cnr_approved": "CNR Approval",
    }
    out = []
    reached = False
    for step in order:
        reached = reached or step == rfp.status
        holder = holders.get(step)
        out.append(
            {
                "step": step,
                "label": labels[step],
                "state": "done" if reached else ("current" if step == rfp.status else "todo"),
                "holder": holder.get_full_name() if holder else "",
            }
        )
    return out


def list_pos(*, limit=100):
    """Purchase Orders, newest first, for the PO screen (ADR-0XX)."""
    from apps.ap.models import PurchaseOrder

    return (
        PurchaseOrder.objects.select_related("supplier", "segment")
        .order_by("-po_date", "-po_number")[:limit]
    )


def po_summary():
    """Counts/amounts by stage for the PO list stat cards (ADR-0XX)."""
    from django.db.models import Sum

    from apps.ap.models import PurchaseOrder

    pending_qs = PurchaseOrder.objects.exclude(status__in=["approved", "closed", "rejected"])
    approved_qs = PurchaseOrder.objects.filter(status__in=["approved", "closed"])
    posted_qs = (
        PurchaseOrder.objects.filter(rfps__status="posted")
        .exclude(rfps__journal_entry__status=PostingStatus.REVERSED)
        .distinct()
    )
    return {
        "total": PurchaseOrder.objects.count(),
        "total_amount": PurchaseOrder.objects.aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "pending": pending_qs.count(),
        "pending_amount": pending_qs.aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "approved": approved_qs.count(),
        "approved_amount": approved_qs.aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "billed_amount": posted_qs.aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
    }


def po_timeline(po):
    """[(status, label, holder)] for the PO document screen (ADR-0XX matrix)."""
    holders = {
        "prepared": getattr(po, "created_by", None),
        "submitted": None,
        "checked": po.checked_by,
        "acctg_approved": po.approved_by_acctg,
        "fin_approved": po.approved_by_fin,
        "cnr_approved": po.approved_by_cnr,
    }
    order = ["prepared", "submitted", "checked", "acctg_approved", "fin_approved"]
    from apps.ap.services import po_coo_required

    if po_coo_required(po):
        order.append("cnr_approved")
    labels = {
        "prepared": "Prepared by",
        "submitted": "Submitted",
        "checked": "Checked / Recommending",
        "acctg_approved": "Accounting Head",
        "fin_approved": "Finance Head",
        "cnr_approved": "CNR Approval",
    }
    out = []
    reached = False
    for step in order:
        reached = reached or step == po.status
        holder = holders.get(step)
        out.append(
            {
                "step": step,
                "label": labels[step],
                "state": "done" if reached else ("current" if step == po.status else "todo"),
                "holder": holder.get_full_name() if holder else "",
            }
        )
    # The PO's terminal markers shown after the chain steps.
    if po.status == "approved":
        out.append({"step": "approved", "label": "Approved (void for RFP funding)", "state": "current", "holder": ""})
    elif po.status == "closed":
        out.append({"step": "approved", "label": "Approved (void for RFP funding)", "state": "done", "holder": ""})
        out.append({"step": "closed", "label": "Closed by Finance Head", "state": "current", "holder": po.closed_by.get_full_name() if po.closed_by else ""})
    elif po.status == "rejected":
        out.append({"step": "rejected", "label": "Rejected — returned to preparer", "state": "current", "holder": po.rejected_by.get_full_name() if po.rejected_by else ""})
    return out


# ---------------------------------------------------------------------------
# Cash
# ---------------------------------------------------------------------------


def list_banks():
    from apps.cash.models import BankAccount

    return BankAccount.objects.order_by("bank_name", "name")


def list_cycles(*, limit=20):
    from apps.cash.models import WeeklyCashCycle

    return WeeklyCashCycle.objects.order_by("-cycle_start")[:limit]


def cycle_summary():
    """Counts by lock state for the Weekly Cycle stat cards."""
    from apps.cash.models import WeeklyCashCycle

    qs = WeeklyCashCycle.objects
    return {
        "total": qs.count(),
        "open": qs.filter(status="open").count(),
        "reconciled": qs.filter(status="reconciled").count(),
        "locked": qs.filter(status="locked").count(),
    }


def list_pcf_funds():
    from apps.cash.models import PettyCashFund

    return PettyCashFund.objects.select_related("gl_account", "company", "custodian").order_by("fund_code")


def list_pcf_replenishments(*, limit=100):
    from apps.cash.models import PCFReplenishment

    return PCFReplenishment.objects.select_related(
        "fund__custodian", "fund__company", "requested_by"
    ).order_by("-request_date")[:limit]


def pcf_replenishment_summary():
    """Counts/amounts by stage for the PCF Vouchers stat cards."""
    from django.db.models import Sum

    from apps.cash.models import PCFReplenishment

    qs = PCFReplenishment.objects
    return {
        "total": qs.count(),
        "total_amount": qs.aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "requested": qs.filter(status="requested").count(),
        "requested_amount": qs.filter(status="requested").aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "approved": qs.filter(status="approved").count(),
        "posted": qs.filter(status="posted").count(),
        "posted_amount": qs.filter(status="posted").aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
    }


def list_cv(*, limit=100):
    from apps.ap.models import CheckVoucher

    return CheckVoucher.objects.select_related("payee", "bank_account", "rfp").order_by("-cv_date")[:limit]


def cv_summary():
    """Counts/amounts by stage for the Check Voucher stat cards."""
    from django.db.models import Sum

    from apps.ap.models import CheckVoucher

    qs = CheckVoucher.objects
    return {
        "total": qs.count(),
        "total_gross": qs.aggregate(t=Sum("gross_amount"))["t"] or Decimal("0.00"),
        "created": qs.filter(status="created").count(),
        "created_gross": qs.filter(status="created").aggregate(t=Sum("gross_amount"))["t"] or Decimal("0.00"),
        "approved": qs.filter(status="approved").count(),
        "cleared": qs.filter(status="cleared").count(),
        "cleared_net": qs.filter(status="cleared").aggregate(t=Sum("net_amount"))["t"] or Decimal("0.00"),
    }


def bank_accounts():
    """GL accounts linked to a BankAccount (all active banks, not just 100xx)."""
    from apps.cash.models import BankAccount
    from apps.foundation.models import Account

    return Account.objects.filter(
        is_postable=True, bank_account__isnull=False,
        bank_account__is_active=True,
    ).order_by("code")


def approved_rfps():
    """RFPs ready to be paid by a check voucher (no CV issued yet).

    Only RFPs whose CONSO batch has already posted (status 'posted') are
    payable: the RFP's expense/liability entry must be in the GL before a
    check voucher settles it.
    """
    from apps.ap.models import RFPDocument

    return RFPDocument.objects.filter(
        status="posted", cv__isnull=True
    ).select_related("payee", "segment")


def unassigned_approved_rfps():
    """Approved RFPs not yet in a CONSO batch (for CONSO add)."""
    from apps.ap.models import RFPDocument
    from apps.ap.services import finally_approved

    candidates = RFPDocument.objects.filter(
        status__in=["fin_approved", "cnr_approved"], conso__isnull=True
    ).select_related("payee", "segment")
    return [rfp for rfp in candidates if finally_approved(rfp)]


def list_conso(*, limit=50):
    from apps.ap.models import CONSOBatch

    return CONSOBatch.objects.prefetch_related("rfps").order_by("-conso_date")[:limit]


def conso_summary():
    """Counts/amounts by stage for the CONSO batch stat cards."""
    from django.db.models import Sum

    from apps.ap.models import CONSOBatch

    qs = CONSOBatch.objects
    return {
        "total": qs.count(),
        "open": qs.filter(status="open").count(),
        "open_amount": qs.filter(status="open").aggregate(t=Sum("total_amount"))["t"] or Decimal("0.00"),
        "reviewed": qs.filter(status="reviewed").count(),
        "posted": qs.filter(status="posted").count(),
        "posted_amount": qs.filter(status="posted").aggregate(t=Sum("total_amount"))["t"] or Decimal("0.00"),
    }


def pending_documents():
    """Documents in flight that have no JournalEntry yet (ADR-043).

    These are the source documents that only become a JE when posted, so they
    never appear on the Journal Entries register. Surfaced on its Pending /
    Unposted tab. AP pipeline first: RFP awaiting/in CONSO, open CONSO batches,
    PCF replenishments awaiting posting.
    """
    from apps.ap.models import CONSOBatch, RFPDocument
    from apps.cash.models import PCFReplenishment

    rows = []
    rfps = (
        RFPDocument.objects.filter(status__in=("fin_approved", "cnr_approved"))
        .select_related("payee", "conso")
        .order_by("ap_number")
    )
    for rfp in rfps:
        rows.append(
            {
                "kind": "RFP",
                "number": rfp.ap_number,
                "date": rfp.rfp_date,
                "party": rfp.payee.name if rfp.payee_id else "",
                "description": rfp.particulars or "",
                "amount": rfp.amount,
                "status_label": "In CONSO" if rfp.conso_id else "Awaiting CONSO",
                "conso": rfp.conso.batch_no if rfp.conso_id else "",
                "detail_url": ("ui:rfp_detail", rfp.id),
            }
        )
    for batch in (
        CONSOBatch.objects.filter(status__in=("open", "reviewed"))
        .prefetch_related("rfps")
        .order_by("batch_no")
    ):
        rows.append(
            {
                "kind": "CONSO",
                "number": batch.batch_no,
                "date": batch.conso_date,
                "party": "",
                "description": f"{batch.rfps.count()} RFP(s) awaiting posting",
                "amount": batch.total_amount,
                "status_label": batch.status.title(),
                "conso": "",
                "detail_url": ("ui:conso_detail", batch.id),
            }
        )
    for replen in (
        PCFReplenishment.objects.filter(status__in=("requested", "approved"))
        .select_related("fund")
        .order_by("id")
    ):
        fund = replen.fund
        rows.append(
            {
                "kind": "PCF",
                "number": replen.voucher_no or f"PCF#{replen.id}",
                "date": replen.request_date,
                "party": (fund.name or fund.fund_code) if fund else "",
                "description": replen.payee_name or "",
                "amount": replen.amount,
                "status_label": "Awaiting CONSO" if replen.status == "approved" else "Requested",
                "conso": "",
                "detail_url": ("ui:pcf_replenishment_detail", replen.id),
            }
        )
    from apps.billing.models import BillingDocument, BillingStatus

    for billing in (
        BillingDocument.objects.filter(
            status__in=(BillingStatus.DRAFT, BillingStatus.SUBMITTED, BillingStatus.APPROVED)
        )
        .select_related("rfp")
        .order_by("billing_no")
    ):
        rows.append(
            {
                "kind": "BILLING",
                "number": billing.billing_no,
                "date": billing.billing_date,
                "party": billing.party_name,
                "description": billing.particulars or "",
                "amount": billing.amount,
                "status_label": (
                    "Awaiting approval" if billing.status == BillingStatus.SUBMITTED
                    else "Approved - for posting" if billing.status == BillingStatus.APPROVED
                    else "Draft"
                ),
                "conso": "",
                "detail_url": ("ui:billing_detail", billing.id),
            }
        )
    rows.sort(key=lambda r: (r["date"] or date.min, r["number"]))
    return rows


def pending_count():
    """Number of in-flight (not-yet-posted) documents for the dashboard badge."""
    return len(pending_documents())


def list_billings(*, limit=100):
    """Billing transactions register, newest first."""
    from apps.billing.models import BillingDocument

    return (
        BillingDocument.objects.select_related("segment", "rfp", "created_by", "approved_by")
        .prefetch_related("lines")
        .order_by("-billing_date", "-billing_no")[:limit]
    )


def billing_summary():
    """Counts/amounts by stage for the Billing stat cards."""
    from django.db.models import Sum

    from apps.billing.models import BillingDocument

    qs = BillingDocument.objects
    return {
        "total": qs.count(),
        "total_amount": qs.aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "draft": qs.filter(status="draft").count(),
        "submitted": qs.filter(status="submitted").count(),
        "submitted_amount": qs.filter(status="submitted").aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "approved": qs.filter(status="approved").count(),
        "posted": qs.filter(status="posted").count(),
        "posted_amount": qs.filter(status="posted").aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
    }


def billing_basis_rfps():
    """Posted RFPs that can serve as the basis of a billing transaction.

    An RFP is a valid billing basis once its own JE is in the GL (status
    "posted"); the resulting billing traces back to it.
    """
    from apps.ap.models import RFPDocument

    return RFPDocument.objects.filter(status="posted").select_related("payee", "segment")


def conso_context(batch):
    """Members (RFPs + PCF replenishments) with their posting state + total."""
    members = list(batch.rfps.select_related("payee", "segment").order_by("ap_number"))
    pcf_members = list(batch.pcf_replenishments.select_related("fund", "fund__custodian").order_by("id"))
    total = sum((m.amount for m in members), Decimal("0.00")) + sum(
        (r.amount for r in pcf_members), Decimal("0.00")
    )
    return {
        "batch": batch,
        "members": members,
        "pcf_members": pcf_members,
        "total": total,
    }


def list_recons(*, limit=100):
    from apps.cash.models import BankReconciliation

    return BankReconciliation.objects.select_related("cycle", "bank_account").order_by("-cycle__cycle_start")[:limit]


def recon_summary():
    """Counts by stage for the Bank Reconciliation stat cards."""
    from apps.cash.models import BankReconciliation

    qs = BankReconciliation.objects
    return {
        "total": qs.count(),
        "open": qs.filter(status="open").count(),
        "resolved": qs.filter(status="resolved").count(),
        "escalated": qs.filter(status="escalated").count(),
    }


def cash_short_summary():
    """Counts/variance by stage for the Cash Short stat cards."""
    from django.db.models import Sum
    from apps.cash.models import CashShortExcessWorksheet

    qs = CashShortExcessWorksheet.objects
    return {
        "total": qs.count(),
        "open": qs.filter(status="open").count(),
        "open_variance": qs.filter(status="open").aggregate(t=Sum("variance"))["t"] or Decimal("0.00"),
        "approved": qs.filter(status="approved").count(),
        "adjusted": qs.filter(status="adjusted").count(),
    }


def list_cash_shorts(*, limit=100):
    from apps.cash.models import CashShortExcessWorksheet

    return CashShortExcessWorksheet.objects.select_related("cycle", "segment").order_by("-cycle__cycle_start")[:limit]


def book_balance(cycle, bank):
    """GL balance for the bank's GL account up to cycle end (ADR-026).

    Includes REVERSED originals so a reversal nets against the original."""
    from apps.posting.models import GeneralLedger

    return (
        GeneralLedger.objects.filter(
            account=bank.gl_account,
            segment=cycle.segment,
            entry__status__in=GL_EFFECTIVE_STATUSES,
            transaction_date__lte=cycle.cycle_end,
        ).aggregate(bal=Sum("debit") - Sum("credit"))["bal"]
    ) or Decimal("0.00")


def pcf_gl_candidates():
    """Cash/PCF asset GL accounts a fund can point to (PCF aggregates on 10000)."""
    from apps.foundation.models import Account

    return Account.objects.filter(
        is_postable=True, account_type="asset", code__startswith="100"
    ).order_by("code")


# ---------------------------------------------------------------------------
# Daily Collections Journal Entries Summary (cashier worksheet)
# ---------------------------------------------------------------------------

# Canonical bank column order from the cashier reference sheet
# (DAILY COLLECTION JOURNAL ENTRIES SUMMARY ... (FINAL VERSION).xlsx).
BANK_ORDER = ["PNB", "MBTC", "BDO", "EW", "E.TAN", "FVB", "KB", "GCASH", "PSBC"]


def daily_collections(cycle):
    """Rows for the Daily Collections JE Summary, one per AR receipt in the cycle.

    Matches the cashier worksheet layout:
      DATE | AR/SI # | OUTLET'S NAME | PARTICULARS | PO NUMBER
      CASH ON HAND (DR/CR) | DUE FROM OTHER BANKS & OTHERS (DR) per bank
      ACCOUNTS RECEIVABLE (DR/CR) | ACCOUNTS PAYABLE (DR/CR)
      TOTAL COLLECTIONS FOR THE DAY | REMARKS
    Collections not applied to an invoice credit AP (their unearned convention);
    applied collections credit AR (matches the sheet's usage of the AP/AR columns).
    """
    from apps.ar.models import AcknowledgmentReceipt
    from apps.cash.models import BankAccount

    bank_lookup = {b.gl_account_id: (b.bank_code or b.code) for b in BankAccount.objects.all()}
    bank_cols = sorted(
        set(v for v in bank_lookup.values() if v),
        key=lambda c: (BANK_ORDER.index(c) if c in BANK_ORDER else 99, c),
    )

    receipts = (
        AcknowledgmentReceipt.objects.filter(
            journal_entry__isnull=False,
            transaction_date__gte=cycle.cycle_start,
            transaction_date__lte=cycle.cycle_end,
        )
        .select_related("customer", "cash_account", "applied_to", "journal_entry")
        .order_by("transaction_date", "receipt_no")
    )

    rows = []
    daily = {}
    bank_totals = {col: Decimal("0.00") for col in bank_cols}
    totals = {
        "cash_debit": Decimal("0.00"), "cash_credit": Decimal("0.00"),
        "ar_debit": Decimal("0.00"), "ar_credit": Decimal("0.00"),
        "ap_debit": Decimal("0.00"), "ap_credit": Decimal("0.00"),
        "total": Decimal("0.00"),
    }
    for r in receipts:
        banks = {}
        if r.cash_account and r.cash_account.code == "10010":
            cash_debit = r.amount
        else:
            cash_debit = Decimal("0.00")
            col = bank_lookup.get(r.cash_account_id, r.cash_account.code if r.cash_account else "")
            if col:
                banks[col] = r.amount
        if r.applied_to:
            ar_credit, ap_credit = r.amount, Decimal("0.00")
            line = r.applied_to.lines.first()
            particulars = line.description if line else f"Applied to {r.applied_to.invoice_no}"
            remarks = f"Applied to {r.applied_to.invoice_no}"
        else:
            ar_credit, ap_credit = Decimal("0.00"), r.amount
            particulars = r.journal_entry.description if r.journal_entry else ""
            remarks = r.check_no or ""

        row = {
            "date": r.transaction_date,
            "ar_no": r.receipt_no,
            "transaction_no": r.transaction_no or "",
            "outlet": r.customer.name,
            "particulars": particulars,
            "po_number": "",
            "cash_debit": cash_debit,
            "cash_credit": Decimal("0.00"),
            "bank_amounts": [banks.get(col, Decimal("0.00")) for col in bank_cols],
            "ar_debit": Decimal("0.00"),
            "ar_credit": ar_credit,
            "ap_debit": Decimal("0.00"),
            "ap_credit": ap_credit,
            "total": r.amount,
            "remarks": remarks,
        }
        rows.append(row)
        bucket = daily.setdefault(
            r.transaction_date,
            {"cash_debit": Decimal("0.00"), "cash_credit": Decimal("0.00"),
             "ar_debit": Decimal("0.00"), "ar_credit": Decimal("0.00"),
             "ap_debit": Decimal("0.00"), "ap_credit": Decimal("0.00"),
             "total": Decimal("0.00"), "bank_amounts": [Decimal("0.00")] * len(bank_cols)},
        )
        for key in ("cash_debit", "cash_credit", "ar_debit", "ar_credit",
                    "ap_debit", "ap_credit", "total"):
            totals[key] += row[key]
            bucket[key] += row[key]
        for idx, amt in enumerate(row["bank_amounts"]):
            bank_totals[bank_cols[idx]] += amt
            bucket["bank_amounts"][idx] += amt

    debit_total = (
        totals["cash_debit"] + totals["ar_debit"] + totals["ap_debit"]
        + sum(bank_totals.values())
    )
    credit_total = totals["cash_credit"] + totals["ar_credit"] + totals["ap_credit"]

    daily_values = [
        {"date": d, **bucket, "bank_amounts": bucket["bank_amounts"]}
        for d, bucket in sorted(daily.items())
    ]

    return {
        "cycle": cycle,
        "bank_cols": bank_cols,
        "rows": rows,
        "daily_values": daily_values,
        "bank_totals": [bank_totals[col] for col in bank_cols],
        "totals": totals,
        "debit_total": debit_total,
        "credit_total": credit_total,
        "variance": debit_total - credit_total,
    }


# ---------------------------------------------------------------------------
# Foundation — Chart of Accounts (read-only)
# ---------------------------------------------------------------------------


def coa_rows(*, q="", segment="", account_type=""):
    """Filterable COA listing (code, name, segment, type, normal balance)."""
    from apps.foundation.models import Account

    rows = Account.objects.filter(is_postable=True).order_by("code")
    if q:
        rows = rows.filter(Q(code__icontains=q) | Q(name__icontains=q))
    if segment:
        rows = rows.filter(segment=segment)
    if account_type:
        rows = rows.filter(account_type=account_type)
    return rows


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


def list_assets(*, limit=100, q="", category="", segment="", status=""):
    from apps.assets.models import Asset

    rows = Asset.objects.select_related("category", "segment").order_by("asset_no")
    if q:
        rows = rows.filter(Q(name__icontains=q) | Q(asset_no__icontains=q))
    if category:
        rows = rows.filter(category_id=category)
    if segment:
        rows = rows.filter(segment_id=segment)
    if status:
        rows = rows.filter(status=status)
    return rows[:limit]


def asset_summary():
    """Counts/net cost by register state for the Fixed Assets stat cards."""
    from apps.assets.models import Asset
    from django.db.models import Sum

    qs = Asset.objects
    return {
        "total": qs.count(),
        "total_cost": qs.aggregate(t=Sum("cost"))["t"] or Decimal("0.00"),
        "active": qs.filter(status="active").count(),
        "fully_depreciated": qs.filter(status="fully_depreciated").count(),
        "disposed": qs.filter(status="disposed").count(),
    }


def asset_context(asset):
    """Detail facts for the asset screen: schedule rows + net book value."""
    return {
        "asset": asset,
        "schedule": asset.depreciation_schedule.order_by("period_start"),
        "accumulated": asset.accumulated_depreciation,
        "nbv": asset.cost - asset.accumulated_depreciation,
    }


# ---------------------------------------------------------------------------
# General Journal register (workbook: PAYMENT RECEIPTS / UPON DELIVERY sheets)
# ---------------------------------------------------------------------------


def _source_parties():
    """Map source_doc_no -> party name from the AR/AP document masters.

    Register/ledger rows always resolve the counterparty from the current
    master record (AR receipt customer / RFP & CV payee), never a stale copy
    held on the journal entry.
    """
    from apps.ap.models import CheckVoucher, RFPDocument
    from apps.ar.models import AcknowledgmentReceipt

    parties = {}
    for r in AcknowledgmentReceipt.objects.exclude(journal_entry__isnull=True).select_related("customer"):
        parties[r.receipt_no] = r.customer.name
    for doc in RFPDocument.objects.exclude(journal_entry__isnull=True).select_related("payee"):
        if doc.payee:
            parties[doc.ap_number] = doc.payee.name
    for cv in CheckVoucher.objects.exclude(journal_entry__isnull=True).select_related("payee"):
        if cv.payee:
            parties[cv.cv_number] = cv.payee.name
    from apps.billing.models import BillingDocument

    for billing in BillingDocument.objects.exclude(journal_entry__isnull=True):
        if billing.party_name:
            parties[billing.billing_no] = billing.party_name
    return parties


def general_journal(*, start=None, end=None, segment=None, limit=500):
    """Posted entries with per-line rows: Date | Cycle | Ref | Party | PO |
    Description | CoA | Account Name | Debit | Credit. Party derives from the
    source document masters (AR receipt customer / AP payee), never stale
    copies on the JE."""
    from apps.posting.models import PostingStatus

    party_by = _source_parties()

    qs = (
        JournalEntry.objects.filter(status__in=GL_EFFECTIVE_STATUSES)
        .select_related("segment", "company")
        .prefetch_related("lines__account")
    )
    if start:
        qs = qs.filter(transaction_date__gte=start)
    if end:
        qs = qs.filter(transaction_date__lte=end)
    if segment:
        qs = qs.filter(segment=segment)
    entries = list(qs.order_by("transaction_date", "entry_no")[:limit])

    rows = []
    total_debit = total_credit = Decimal("0.00")
    for entry in entries:
        cycle_start, cycle_end = cycle_range_for(entry.transaction_date, company=entry.company)
        if cycle_start.month == cycle_end.month:
            cycle_label = f"{cycle_start:%b} {cycle_start.day}-{cycle_end.day}, {cycle_start:%Y}"
        else:
            cycle_label = f"{cycle_start:%b} {cycle_start.day} - {cycle_end:%b} {cycle_end.day}, {cycle_end:%Y}"
        party = party_by.get(entry.source_doc_no, "") if entry.source_doc_no else ""
        # Manual voucher JEs carry their party/PO on the header (supplier_name
        # / po); master-derived parties still win when the entry has one.
        party = party or entry.supplier_name or ""
        po = entry.po or ""
        balanced = entry.is_balanced
        for line in entry.lines.all():
            rows.append(
                {
                    "new_entry": True,
                    "entry_pk": entry.id,
                    "date": entry.transaction_date,
                    "cycle": cycle_label,
                    "ref": entry.entry_no,
                    "source_type": entry.source_doc_type,
                    "party": party,
                    "po": po,
                    "description": line.description or entry.description,
                    "coa": line.account.code,
                    "account_name": line.account.name,
                    "cost_center": line.cost_center or "",
                    # Note/Reference: the per-line reference (e.g. the RFP number
                    # + amount billed on a 15550/15560 credit) or the entry's
                    # REF # when the line has none.
                    "note": line.reference or entry.ref_number or "",
                    "debit": line.debit,
                    "credit": line.credit,
                    "entry_balanced": balanced,
                    "segment": entry.segment.code,
                    "status": entry.status,
                }
            )
            total_debit += line.debit
            total_credit += line.credit

    for i, row in enumerate(rows):
        row["new_entry"] = i == 0 or rows[i - 1]["ref"] != row["ref"]

    return {
        "rows": rows,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "variance": total_debit - total_credit,
        "segments": list(Segment.objects.order_by("code")),
    }


# ---------------------------------------------------------------------------
# Cash flow / collectibles / aging / advances / transfers
# ---------------------------------------------------------------------------


def cash_flow_options():
    """Picker options for the Cash Flow screen (monthly cadence, ADR-031)."""
    this_year = date.today().year
    return {
        "segments": list(Segment.objects.order_by("code")),
        "months": list(range(1, 13)),
        "years": list(range(this_year, this_year - 3, -1)),
    }


def collectibles_cycle_options():
    """Cycles that can be rendered on the COLLECTIBLES worksheet."""
    from apps.cash.models import WeeklyCashCycle

    return WeeklyCashCycle.objects.select_related("segment").order_by("-cycle_start")[:24]


def aging_context(as_of: date) -> dict:
    """AR aging buckets + per-invoice register for an as-of date."""
    from apps.ar.models import ARInvoice
    from apps.ar.services import CycleLedgerService

    buckets = CycleLedgerService.aging(as_of)
    register = []
    not_yet_due = []
    for inv in (
        ARInvoice.objects.filter(status__in=("open", "partially_paid"))
        .select_related("customer", "segment")
        .order_by("transaction_date")
    ):
        balance = inv.balance
        if balance <= 0:
            continue
        if inv.transaction_date > as_of:
            not_yet_due.append(
                {
                    "invoice_no": inv.invoice_no,
                    "customer": inv.customer.name,
                    "date": inv.transaction_date,
                    "segment": inv.segment.code,
                    "status": inv.status.replace("_", " ").title(),
                    "balance": balance,
                    "age_days": None,
                }
            )
            continue
        age_days = (as_of - inv.transaction_date).days
        register.append(
            {
                "invoice_no": inv.invoice_no,
                "customer": inv.customer.name,
                "date": inv.transaction_date,
                "segment": inv.segment.code,
                "status": inv.status.replace("_", " ").title(),
                "balance": balance,
                "age_days": age_days,
            }
        )
    return {
        "as_of": as_of,
        "buckets": buckets,
        "bucket_total": sum(b["amount"] for b in buckets),
        "bucket_max": max([b["amount"] for b in buckets] + [Decimal("0.01")]),
        "register": register,
        "register_total": sum(r["balance"] for r in register),
        "not_yet_due": not_yet_due,
        "not_yet_due_total": sum(r["balance"] for r in not_yet_due),
    }


def customer_aging_context(customer: Any, as_of: date) -> dict:
    """AR aging buckets + per-invoice register for a specific customer and as-of date."""

    from django.db.models import Q
    from apps.ar.models import ARInvoice

    buckets = {"0-30": Decimal("0.00"), "31-60": Decimal("0.00"),
               "61-90": Decimal("0.00"), "91-120": Decimal("0.00"),
               "120+": Decimal("0.00")}
    register = []
    not_yet_due = []
    invoices = ARInvoice.objects.filter(
        customer=customer,
        status__in=("open", "partially_paid"),
        transaction_date__lte=as_of,
    )
    for inv in invoices:
        balance = inv.balance
        if balance <= 0:
            continue
        age_days = (as_of - inv.transaction_date).days
        if age_days <= 30:
            buckets["0-30"] += balance
        elif age_days <= 60:
            buckets["31-60"] += balance
        elif age_days <= 90:
            buckets["61-90"] += balance
        elif age_days <= 120:
            buckets["91-120"] += balance
        else:
            buckets["120+"] += balance
        register.append(
            {
                "invoice_no": inv.invoice_no,
                "customer": inv.customer.name,
                "date": inv.transaction_date,
                "segment": inv.segment.code,
                "status": inv.status.replace("_", " ").title(),
                "balance": balance,
                "age_days": age_days,
            }
        )
    not_yet_due_invoices = ARInvoice.objects.filter(
        customer=customer,
        transaction_date__gt=as_of,
    )
    for inv in not_yet_due_invoices:
        not_yet_due.append(
            {
                "invoice_no": inv.invoice_no,
                "customer": inv.customer.name,
                "date": inv.transaction_date,
                "segment": inv.segment.code,
                "status": inv.status.replace("_", " ").title(),
                "balance": inv.balance,
            }
        )
    return {
        "as_of": as_of,
        "buckets": buckets,
        "bucket_total": sum(buckets.values()),
        "register": register,
        "register_total": sum(r["balance"] for r in register),
        "not_yet_due": not_yet_due,
        "not_yet_due_total": sum(r["balance"] for r in not_yet_due),
    }


def ar_customer_summary(*, q: str = "", outstanding_only: bool = False) -> dict:
    """Return rows for the Customer Subsidiary Ledger Summary screen.

    Columns: Code | Customer Name | Total Billed | Total Paid | Outstanding Balance.
    Billed = Σ AR invoice totals (all invoice statuses — billing-side truth).
    Paid   = Σ posted ack receipts (posted JE; reversed collections excluded).
    Mirror of ``ap_supplier_summary`` for the AR receivable track (ADR-005).
    """

    from django.db.models import Q, Sum
    from apps.ar.models import AcknowledgmentReceipt, ARInvoice, Customer
    from apps.posting.models import PostingStatus

    customers = Customer.objects.order_by("name")
    if q:
        customers = customers.filter(Q(code__icontains=q) | Q(name__icontains=q))

    # --- Billed: Σ invoice totals per customer ---
    billed_by_customer: dict = dict(
        ARInvoice.objects.values("customer_id")
        .annotate(total=Sum("total"))
        .values_list("customer_id", "total")
    )

    # --- Paid: posted ack receipts (posted JE, reversed excluded) per customer ---
    paid_by_customer: dict = dict(
        AcknowledgmentReceipt.objects.filter(
            journal_entry__status=PostingStatus.POSTED
        )
        .values("customer_id")
        .annotate(total=Sum("amount"))
        .values_list("customer_id", "total")
    )

    rows = []
    total_billed = Decimal("0.00")
    total_paid = Decimal("0.00")
    total_outstanding = Decimal("0.00")
    total_advance = Decimal("0.00")
    for c in customers:
        billed = billed_by_customer.get(c.id, Decimal("0.00"))
        paid = paid_by_customer.get(c.id, Decimal("0.00"))
        outstanding = billed - paid
        advance = -outstanding if outstanding < 0 else Decimal("0.00")
        if outstanding < 0:
            outstanding = Decimal("0.00")
        if outstanding_only and outstanding <= 0:
            continue
        rows.append(
            {
                "pk": c.pk,
                "code": c.code,
                "name": c.name,
                "billed": billed,
                "paid": paid,
                "outstanding": outstanding,
                "advance": advance,
            }
        )
        total_billed += billed
        total_paid += paid
        total_outstanding += outstanding
        total_advance += advance

    return {
        "rows": rows,
        "total_billed": total_billed,
        "total_paid": total_paid,
        "total_outstanding": total_outstanding,
        "total_advance": total_advance,
    }


def ar_customer_ledger(*, customer, start=None, end=None) -> dict:
    """Return the per-customer AR subsidiary ledger rows with running balance.

    Columns: Date | Ref # | Type | Description/Particulars | Debit | Credit | Balance (Dr/Cr).
    Debit rows = AR invoices (receivable recognized). Credit rows = posted ack
    receipts (collections), reversal-excluded. Mirror of ``ap_supplier_ledger``
    with a debit-normal receivable running balance (ADR-005).
    """

    from datetime import datetime
    from decimal import Decimal

    from apps.ar.models import AcknowledgmentReceipt, ARInvoice
    from apps.posting.models import PostingStatus
    from apps.ui.services import _balance_cell

    # --- Debit rows: AR invoices (all statuses — billing-side truth) ---
    debit_rows = []
    for inv in ARInvoice.objects.filter(customer=customer).select_related("segment"):
        debit_rows.append(
            {
                "date": inv.transaction_date,
                "ref": inv.invoice_no,
                "ref_pk": inv.id,
                # No UI invoice-detail route yet — the ref renders as plain text.
                "ref_url": "",
                "type": "Invoice",
                "description": f"{inv.segment.code} — {inv.total:.2f} billed",
                "debit": inv.total,
                "credit": Decimal("0.00"),
            }
        )

    # --- Credit rows: posted ack receipts (collections) ---
    credit_rows = []
    for r in (
        AcknowledgmentReceipt.objects.filter(
            customer=customer, journal_entry__status=PostingStatus.POSTED
        )
        .select_related("segment", "applied_to")
    ):
        if r.applied_to_id:
            desc = f"Applied to {r.applied_to.invoice_no}"
        else:
            desc = "Collection (Unearned revenue)"
        credit_rows.append(
            {
                "date": r.transaction_date,
                "ref": r.receipt_no,
                "ref_pk": r.id,
                "ref_url": "ui:receipt_detail",
                "type": "Receipt (Collection)",
                "description": desc,
                "debit": Decimal("0.00"),
                "credit": r.amount,
            }
        )

    # --- Merge and sort (before the date window so the opening balance below
    # can reference all activity, not just the visible window) ---
    all_rows = debit_rows + credit_rows
    all_rows.sort(key=lambda r: (r["date"], r["ref_pk"]))

    # Views pass raw ISO strings from request.GET; normalise once so the date
    # comparisons below never mix date objects and strings.
    def _as_date(value):
        if isinstance(value, str) and value:
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                return None
        return value

    start_d = _as_date(start)
    end_d = _as_date(end)

    # Date window filter
    if start_d:
        all_rows = [r for r in all_rows if r["date"] >= start_d]
    if end_d:
        all_rows = [r for r in all_rows if r["date"] <= end_d]

    # --- Running balance ---
    # Opening balance = sum of (debit - credit) for rows before the window start
    opening = Decimal("0.00")
    if start_d:
        opening = sum(
            (r["debit"] - r["credit"]) for r in debit_rows + credit_rows if r["date"] < start_d
        )

    running = opening
    opening_dr = _balance_cell(opening, "debit", "debit") or Decimal("0.00")
    opening_cr = _balance_cell(opening, "debit", "credit") or Decimal("0.00")

    rows = []
    period_debit = Decimal("0.00")
    period_credit = Decimal("0.00")
    for r in all_rows:
        period_debit += r["debit"]
        period_credit += r["credit"]
        running += r["debit"] - r["credit"]  # cumulative running balance
        balance_dr = _balance_cell(running, "debit", "debit") or Decimal("0.00")
        balance_cr = _balance_cell(running, "debit", "credit") or Decimal("0.00")
        rows.append(
            {
                "date": r["date"].isoformat() if hasattr(r["date"], "isoformat") else str(r["date"]),
                "ref": r["ref"],
                "ref_pk": r["ref_pk"],
                "ref_url": r["ref_url"],
                "type": r["type"],
                "description": r["description"],
                "debit": r["debit"],
                "credit": r["credit"],
                "balance_dr": balance_dr,
                "balance_cr": balance_cr,
            }
        )

    closing = running
    closing_dr = _balance_cell(closing, "debit", "debit")
    closing_cr = _balance_cell(closing, "debit", "credit")

    return {
        "customer": customer,
        "start": start,
        "end": end,
        "opening": opening,
        "opening_dr": opening_dr,
        "opening_cr": opening_cr,
        "rows": rows,
        "period_debit": period_debit,
        "period_credit": period_credit,
        "closing": closing,
        "closing_dr": closing_dr,
        "closing_cr": closing_cr,
    }


def ap_aging_context(as_of: date) -> dict:
    """AP aging buckets + per-RFP open-payable register for an as-of date.

    Open AP = the RFP's true payable (AP-role credit lines: gross minus WHT and
    other non-AP credits) minus the gross of check vouchers that actually
    posted their clearing JEs (POSTING_RULES 7.4). Buckets 30/60/90/120+ by
    RFP date. It reconciles with the GL A/P account because both sides derive
    from the same two inputs: payable booked at the RFP and CV gross at clear.

    Only RFPs dated on or before as_of are included in aging buckets.
    Future-dated RFPs are listed separately as "not_yet_due".
    """
    from apps.ap.models import CheckVoucher, RFPDocument
    from apps.ap.services import rfp_payable

    cleared = {
        row["rfp_id"]: row["paid"] or Decimal("0.00")
        for row in (
            CheckVoucher.objects.filter(journal_entry__status=PostingStatus.POSTED)
            .exclude(rfp__isnull=True)
            .values("rfp_id")
            .annotate(paid=Sum("gross_amount"))
        )
    }

    buckets = {
        "0-30": Decimal("0.00"),
        "31-60": Decimal("0.00"),
        "61-90": Decimal("0.00"),
        "91-120": Decimal("0.00"),
        "120+": Decimal("0.00"),
    }
    register = []
    not_yet_due = []
    for rfp in (
        RFPDocument.objects.filter(status="posted")
        .exclude(journal_entry__status=PostingStatus.REVERSED)
        .select_related("payee", "segment")
        .prefetch_related("lines")
        .order_by("rfp_date")
    ):
        payable = rfp_payable(rfp)
        paid = cleared.get(rfp.id, Decimal("0.00"))
        balance = payable - paid
        if balance <= 0:
            continue
        if rfp.rfp_date > as_of:
            not_yet_due.append(
                {
                    "ap_number": rfp.ap_number,
                    "payee": rfp.payee.name,
                    "date": rfp.rfp_date,
                    "segment": rfp.segment.code,
                    "status": rfp.status.replace("_", " ").title(),
                    "amount": payable,
                    "paid": paid,
                    "balance": balance,
                    "age_days": None,
                }
            )
            continue
        age_days = (as_of - rfp.rfp_date).days
        key = (
            "0-30" if age_days <= 30
            else "31-60" if age_days <= 60
            else "61-90" if age_days <= 90
            else "91-120" if age_days <= 120
            else "120+"
        )
        buckets[key] += balance
        register.append(
            {
                "ap_number": rfp.ap_number,
                "payee": rfp.payee.name,
                "date": rfp.rfp_date,
                "segment": rfp.segment.code,
                "status": rfp.status.replace("_", " ").title(),
                "amount": payable,
                "paid": paid,
                "balance": balance,
                "age_days": age_days,
            }
        )
    return {
        "as_of": as_of,
        "buckets": [{"bucket": k, "amount": money(v)} for k, v in buckets.items()],
        "bucket_total": sum(buckets.values()),
        "bucket_max": max(list(buckets.values()) + [Decimal("0.01")]),
        "register": register,
        "register_total": sum(r["balance"] for r in register),
        "not_yet_due": not_yet_due,
        "not_yet_due_total": sum(r["balance"] for r in not_yet_due),
    }


def ap_supplier_summary(*, q: str = "", outstanding_only: bool = False) -> dict:
    """Return rows for the Supplier / Payee Ledger Summary screen.

    Columns: Code | Supplier/Payee Name | Total Billed | Total Paid | Outstanding Balance.
    Billed = Σ RFP payables (posted, credit to 20000/21100).
    Paid   = Σ cleared CVs (posted JE) gross.
    """
    from django.db.models import Q, Sum
    from apps.ap.models import RFPDocument, CheckVoucher, Supplier
    from apps.posting.models import PostingStatus

    suppliers = Supplier.objects.order_by("name")
    if q:
        suppliers = suppliers.filter(Q(code__icontains=q) | Q(name__icontains=q))

    # --- Billed: posted RFP AP payables per supplier ---
    billed_by_supplier: dict = {}
    for rfp in (
        RFPDocument.objects.filter(status="posted")
        .exclude(journal_entry__status=PostingStatus.REVERSED)
        .prefetch_related("payee", "lines")
    ):
        
        payable = Decimal("0.00")
        for line in rfp.lines.all():
            if line.side != "cr":
                continue
            if line.account.code in ("20000", "21100"):
                payable += line.amount
        if payable:
            billed_by_supplier[rfp.payee_id] = billed_by_supplier.get(rfp.payee_id, Decimal("0.00")) + payable

    # --- Paid: cleared CVs (posted JE) per supplier ---
    paid_by_supplier: dict = {}
    for cv in CheckVoucher.objects.filter(journal_entry__status=PostingStatus.POSTED).select_related("payee"):
        paid_by_supplier[cv.payee_id] = paid_by_supplier.get(cv.payee_id, Decimal("0.00")) + cv.gross_amount

    rows = []
    total_billed = Decimal("0.00")
    total_paid = Decimal("0.00")
    total_outstanding = Decimal("0.00")
    total_advance = Decimal("0.00")
    for s in suppliers:
        billed = billed_by_supplier.get(s.id, Decimal("0.00"))
        paid = paid_by_supplier.get(s.id, Decimal("0.00"))
        outstanding = billed - paid
        advance = -outstanding if outstanding < 0 else Decimal("0.00")
        if outstanding < 0:
            outstanding = Decimal("0.00")
        if outstanding_only and outstanding <= 0:
            continue
        rows.append(
            {
                "pk": s.pk,
                "code": s.code,
                "name": s.name,
                "billed": billed,
                "paid": paid,
                "outstanding": outstanding,
                "advance": advance,
            }
        )
        total_billed += billed
        total_paid += paid
        total_outstanding += outstanding
        total_advance += advance

    return {
        "rows": rows,
        "total_billed": total_billed,
        "total_paid": total_paid,
        "total_outstanding": total_outstanding,
        "total_advance": total_advance,
    }


def ap_supplier_ledger(*, supplier, start=None, end=None) -> dict:
    """Return the per-supplier AP subsidiary ledger rows with running balance.

    Columns: Date | Ref # | Type | Description/Particulars | Debit | Credit | Balance (Dr/Cr).
    """
    from decimal import Decimal
    from datetime import datetime
    from django.db.models import Q
    from apps.ap.models import RFPDocument, CheckVoucher
    from apps.posting.models import PostingStatus, GeneralLedger
    from apps.ui.services import _balance_cell

    # --- Credit rows: posted RFPs ---
    credit_rows = []
    for rfp in (
        RFPDocument.objects.filter(status="posted", payee=supplier)
        .exclude(journal_entry__status=PostingStatus.REVERSED)
        .select_related("segment")
        .prefetch_related("lines")
    ):
        payable = Decimal("0.00")
        for line in rfp.lines.all():
            if line.side == "cr" and line.account.code in ("20000", "21100"):
                payable += line.amount
        if payable == 0:
            continue
        credit_rows.append(
            {
                "date": rfp.rfp_date,
                "ref": rfp.ap_number,
                "ref_pk": rfp.id,
                "ref_url": "ui:rfp_detail",
                "type": "RFP (Payable)",
                "description": rfp.particulars or rfp.purpose or "",
                "debit": Decimal("0.00"),
                "credit": payable,
            }
        )

    # --- Debit rows: cleared CVs (posted JE) ---
    debit_rows = []
    for cv in CheckVoucher.objects.filter(journal_entry__status=PostingStatus.POSTED, payee=supplier).select_related("rfp"):
        # Determine description: linked RFP particulars if available, else check payment text
        desc = ""
        if cv.rfp_id:
            rfp_obj = cv.rfp
            desc = rfp_obj.particulars or rfp_obj.purpose or ""
        else:
            desc = f"Check payment — {cv.check_no}" if cv.check_no else "Check payment"

        # Determine reference link: cv_number → cv_detail
        debit_rows.append(
            {
                "date": cv.cv_date,
                "ref": cv.cv_number,
                "ref_pk": cv.id,
                "ref_url": "ui:cv_detail",
                "type": "CV (Payment)",
                "description": desc,
                "debit": cv.gross_amount,
                "credit": Decimal("0.00"),
            }
        )

    # --- Merge and sort (before the date window so the opening balance below
    # can reference all activity, not just the visible window) ---
    all_rows = credit_rows + debit_rows
    all_rows.sort(key=lambda r: (r["date"], r["ref_pk"]))

    # Views pass raw ISO strings from request.GET; normalise once so the date
    # comparisons below never mix date objects and strings.
    def _as_date(value):
        if isinstance(value, str) and value:
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                return None
        return value

    start_d = _as_date(start)
    end_d = _as_date(end)

    # Date window filter
    if start_d:
        all_rows = [r for r in all_rows if r["date"] >= start_d]
    if end_d:
        all_rows = [r for r in all_rows if r["date"] <= end_d]

    # --- Running balance ---
    # Opening balance = sum of (credit - debit) for rows before the window start
    opening = Decimal("0.00")
    if start_d:
        opening = sum(
            (r["credit"] - r["debit"]) for r in credit_rows + debit_rows if r["date"] < start_d
        )

    running = opening
    opening_dr = _balance_cell(opening, "credit", "debit") or Decimal("0.00")
    opening_cr = _balance_cell(opening, "credit", "credit") or Decimal("0.00")

    rows = []
    period_debit = Decimal("0.00")
    period_credit = Decimal("0.00")
    for r in all_rows:
        period_debit += r["debit"]
        period_credit += r["credit"]
        running += r["credit"] - r["debit"]  # cumulative running balance
        balance_dr = _balance_cell(running, "credit", "debit") or Decimal("0.00")
        balance_cr = _balance_cell(running, "credit", "credit") or Decimal("0.00")
        rows.append(
            {
                "date": r["date"].isoformat() if hasattr(r["date"], "isoformat") else str(r["date"]),
                "ref": r["ref"],
                "ref_pk": r["ref_pk"],
                "ref_url": r["ref_url"],
                "type": r["type"],
                "description": r["description"],
                "debit": r["debit"],
                "credit": r["credit"],
                "balance_dr": balance_dr,
                "balance_cr": balance_cr,
            }
        )

    closing = running
    closing_dr = _balance_cell(closing, "credit", "debit")
    closing_cr = _balance_cell(closing, "credit", "credit")

    return {
        "supplier": supplier,
        "start": start,
        "end": end,
        "opening": opening,
        "opening_dr": opening_dr,
        "opening_cr": opening_cr,
        "rows": rows,
        "period_debit": period_debit,
        "period_credit": period_credit,
        "closing": closing,
        "closing_dr": closing_dr,
        "closing_cr": closing_cr,
    }
    """AdvanceToEmployee ledger rows with outstanding balances."""
    from apps.ap.models import AdvanceToEmployee

    rows = []
    for adv in AdvanceToEmployee.objects.select_related("segment", "rfp").order_by("-granted_date"):
        rows.append(
            {
                "advance": adv,
                "kind": adv.get_kind_display(),
                "segment_code": adv.segment.code,
                "outstanding": adv.outstanding,
                "status_label": adv.status.replace("_", " ").title(),
            }
        )
    return {
        "rows": rows,
        "total_outstanding": sum(r["outstanding"] for r in rows),
        "segments": list(Segment.objects.order_by("code")),
    }


def transfers_context():
    """Inter-account transfers + bank accounts for the transfer form."""
    from apps.cash.models import BankAccount, InterAccountTransfer

    from django.db.models import Sum

    banks = BankAccount.objects.filter(is_active=True).select_related("company", "gl_account").order_by("code")
    transfers = InterAccountTransfer.objects.select_related("from_account", "to_account", "journal_entry")
    summary = {
        "total": transfers.count(),
        "total_amount": transfers.aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "requested": transfers.filter(status__in=("requested", "rejected")).count(),
        "submitted": transfers.filter(status="submitted").count(),
        "submitted_amount": transfers.filter(status="submitted").aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "approved": transfers.filter(status="approved").count(),
        "approved_amount": transfers.filter(status="approved").aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
    }
    return {
        "banks": banks,
        "summary": summary,
        "transfers": transfers.order_by("-transfer_date"),
    }


def transfer_timeline(transfer):
    """[(step, label, state, holder)] for the FTV document screen (ADR-030).

    requested -> submitted -> approved; a rejected transfer is shown back at
    the requested step (returned to the preparer)."""
    holders = {
        "requested": transfer.initiated_by,
        "submitted": None,
        "approved": transfer.approved_by,
    }
    labels = {
        "requested": "Requested by",
        "submitted": "Submitted",
        "approved": "Approved (head) — JE posted",
    }
    order = ["requested", "submitted", "approved"]
    if transfer.status == "rejected":
        current = "requested"
    else:
        current = transfer.status if transfer.status in order else "requested"
    current_idx = order.index(current)
    approved = transfer.status == "approved"

    out = []
    for i, step in enumerate(order):
        if approved:
            state = "done"
        elif i < current_idx:
            state = "done"
        elif i == current_idx:
            state = "current"
        else:
            state = "todo"
        holder = holders.get(step)
        out.append(
            {
                "step": step,
                "label": labels[step],
                "state": state,
                "holder": holder.get_full_name() if holder else "",
            }
        )
    return out


# ---------------------------------------------------------------------------
# Tax & compliance (Phase 9)
# ---------------------------------------------------------------------------


def tax_calendar_context():
    """TaxCalendar rows: upcoming + filed obligations, grouped by status."""
    from apps.tax.models import TaxCalendar

    from apps.foundation.models import Company

    company = Company.objects.first()
    qs = TaxCalendar.objects.filter(company=company).order_by("due_date", "form")
    return {
        "calendar": list(qs),
        "due": qs.filter(status__in=["due", "overdue"]).count(),
    }


# ---------------------------------------------------------------------------
# General Ledger (classic per-account running balance + COA-grouped index)
# ---------------------------------------------------------------------------

LEDGER_GROUP_ORDER = [
    "asset", "contra_asset",
    "liability", "contra_liability",
    "equity", "contra_equity", "drawing",
    "revenue", "contra_revenue",
    "expense",
]


def _period_for_month(company, month):
    """Find the FiscalPeriod whose month matches `YYYY-MM` for the company."""
    if not month or len(month) != 7:
        return None
    try:
        year, mon = int(month[:4]), int(month[5:7])
    except ValueError:
        return None
    if not 1 <= mon <= 12:
        return None
    return FiscalPeriod.objects.filter(
        fiscal_year__company=company, start_date__year=year, start_date__month=mon
    ).first()


def ledger_window(params):
    """Resolve a Ledger run's window + segment from GET params.

    `month=YYYY-MM` (fiscal-period mode) wins over explicit start/end (date
    range, like the General Journal register). With neither given, the window
    defaults to the period containing the latest posted GL date — the same
    "most recent activity" default as the Trial Balance screen.
    """
    from apps.foundation.models import Company
    from apps.posting.models import GeneralLedger

    company = Company.objects.first()
    segment = (params.get("segment") or "").strip()
    month = (params.get("month") or "").strip()
    start = end = None
    mode = "range"

    period = _period_for_month(company, month) if month else None
    if period:
        start, end = period.start_date, period.end_date
        mode = "month"

    if not start and not end:
        raw_start = (params.get("start") or "").strip()
        raw_end = (params.get("end") or "").strip()
        if raw_start:
            try:
                start = date.fromisoformat(raw_start)
            except ValueError:
                start = None
        if raw_end:
            try:
                end = date.fromisoformat(raw_end)
            except ValueError:
                end = None
        if start or end:
            mode = "range"

    if not start and not end:
        latest = (
            GeneralLedger.objects.filter(
                entry__status__in=GL_EFFECTIVE_STATUSES, entry__company=company
            )
            .order_by("-transaction_date")
            .values_list("transaction_date", flat=True)
            .first()
        )
        period = None
        if latest:
            period = (
                FiscalPeriod.objects.filter(start_date__lte=latest, end_date__gte=latest)
                .order_by("-period_no")
                .first()
            )
        if period:
            start, end = period.start_date, period.end_date
            month = f"{period.start_date:%Y-%m}"
            mode = "month"

    return {
        "company": company,
        "start": start,
        "end": end,
        "month": month,
        "mode": mode,
        "segment": segment,
        "segments": list(Segment.objects.order_by("code")),
    }


def _gl_per_account(qs):
    """{account_id: {"debit":..., "credit":...}} over a GL queryset."""
    out = {}
    rows = qs.values("account_id").annotate(debit=Sum("debit"), credit=Sum("credit"))
    for r in rows:
        out[r["account_id"]] = {
            "debit": r["debit"] or Decimal("0.00"),
            "credit": r["credit"] or Decimal("0.00"),
        }
    return out


def _signed(dr, cr, normal_balance):
    """ADR-005 signed balance: positive toward the account's normal column."""
    if normal_balance == "credit":
        return (cr or Decimal("0.00")) - (dr or Decimal("0.00"))
    return (dr or Decimal("0.00")) - (cr or Decimal("0.00"))


def ledger_index(*, company, start=None, end=None, segment=None):
    """COA-grouped ledger index: opening | period Dr | period Cr | closing.

    Query-time projection over the posted GL (ADR-005) — no stored balances.
    Accounts are presented in classic order (Assets -> Liabilities -> Equity ->
    Revenue -> Expenses), each type sub-grouped by the COA's CLASSIFICATION
    column. Closing = signed opening + period movement.
    """
    from apps.foundation.models import Account, AccountType
    from apps.posting.models import GeneralLedger

    gs = GeneralLedger.objects.filter(
        entry__status__in=GL_EFFECTIVE_STATUSES, entry__company=company
    )
    if segment:
        gs = gs.filter(segment__code=segment)

    period_qs = gs
    if start:
        period_qs = period_qs.filter(transaction_date__gte=start)
    if end:
        period_qs = period_qs.filter(transaction_date__lte=end)
    period = _gl_per_account(period_qs)

    opening = {}
    if start:
        opening = _gl_per_account(gs.filter(transaction_date__lt=start))

    ids = set(period) | set(opening)
    accounts = {a.id: a for a in Account.objects.filter(id__in=ids)}
    labels = {t: label for t, label in AccountType.choices}

    by_type: dict[str, list] = {}
    for aid in ids:
        acc = accounts.get(aid)
        if not acc:
            continue
        o = opening.get(aid, {"debit": Decimal("0.00"), "credit": Decimal("0.00")})
        p = period.get(aid, {"debit": Decimal("0.00"), "credit": Decimal("0.00")})
        normal = acc.normal_balance or "debit"
        closing = _signed(o["debit"] + p["debit"], o["credit"] + p["credit"], normal)
        by_type.setdefault(acc.account_type, []).append(
            {
                "id": acc.id,
                "code": acc.code,
                "name": acc.name,
                "segment": acc.segment,
                "classification": acc.classification or "",
                "account_type": acc.account_type,
                "normal_balance": normal,
                "opening": _signed(o["debit"], o["credit"], normal),
                "debit": p["debit"],
                "credit": p["credit"],
                "closing": closing,
            }
        )

    groups = []
    for atype in LEDGER_GROUP_ORDER:
        rows = by_type.get(atype)
        if not rows:
            continue
        rows.sort(key=lambda r: (not r["classification"], r["classification"], r["code"]))
        sections, current = [], None
        for r in rows:
            cls = r["classification"]
            if current is None or current["classification"] != cls:
                current = {"classification": cls, "rows": []}
                sections.append(current)
            current["rows"].append(r)
        groups.append(
            {"account_type": atype, "label": labels.get(atype, atype), "sections": sections}
        )

    return {
        "groups": groups,
        "total_debit": sum(
            r["debit"] for g in groups for s in g["sections"] for r in s["rows"]
        ),
        "total_credit": sum(
            r["credit"] for g in groups for s in g["sections"] for r in s["rows"]
        ),
        "count": len(ids),
    }


def ledger_account(*, account, company, start=None, end=None, segment=None):
    """The classic per-account register: balance brought forward, then every
    posted GL line in the window with a running balance, then period totals.

    Running balance is ADR-005 signed (positive toward the account's normal
    column). Each row carries the source document, cost center and the party
    resolved from the source-document masters (matching General Journal).
    """
    from apps.posting.models import GeneralLedger

    gs = GeneralLedger.objects.filter(
        entry__status__in=GL_EFFECTIVE_STATUSES, entry__company=company, account=account
    )
    if segment:
        gs = gs.filter(segment__code=segment)

    normal = account.normal_balance or "debit"
    opening_dr = opening_cr = Decimal("0.00")
    if start:
        agg = gs.filter(transaction_date__lt=start).aggregate(
            debit=Sum("debit"), credit=Sum("credit")
        )
        opening_dr, opening_cr = agg["debit"] or Decimal("0.00"), agg["credit"] or Decimal("0.00")
    opening = _signed(opening_dr, opening_cr, normal)

    window_qs = gs
    if start:
        window_qs = window_qs.filter(transaction_date__gte=start)
    if end:
        window_qs = window_qs.filter(transaction_date__lte=end)
    gl_rows = list(
        window_qs.order_by("transaction_date", "id")
        .select_related("entry", "line__account", "segment")
    )

    parties = _source_parties()
    running = opening
    period_dr = period_cr = Decimal("0.00")
    rows = []
    for gl in gl_rows:
        period_dr += gl.debit
        period_cr += gl.credit
        running += _signed(gl.debit, gl.credit, normal)
        entry = gl.entry
        party = (
            parties.get(entry.source_doc_no, "") if entry.source_doc_no else ""
        )
        party = party or entry.supplier_name or ""
        rows.append(
            {
                "date": gl.transaction_date,
                "entry_no": entry.entry_no,
                "entry_pk": entry.id,
                "source_type": entry.source_doc_type or "",
                "source_doc_no": entry.source_doc_no or "",
                "party": party,
                "particulars": gl.line.description or entry.description,
                "cost_center": gl.line.cost_center or "",
                "segment": gl.segment.code if gl.segment else (account.segment or ""),
                "debit": gl.debit,
                "credit": gl.credit,
                "balance": running,
                "balance_dr": _balance_cell(running, normal, "debit"),
                "balance_cr": _balance_cell(running, normal, "credit"),
            }
        )

    return {
        "account": account,
        "start": start,
        "end": end,
        "opening": opening,
        "opening_dr": _balance_cell(opening, normal, "debit"),
        "opening_cr": _balance_cell(opening, normal, "credit"),
        "rows": rows,
        "period_debit": period_dr,
        "period_credit": period_cr,
        "closing": running,
        "closing_dr": _balance_cell(running, normal, "debit"),
        "closing_cr": _balance_cell(running, normal, "credit"),
        "normal_balance": normal,
    }


def _balance_cell(balance, normal_balance, column):
    """Amount for a classic Dr/Cr balance column, or `None` when the running
    balance sits on the opposite side (an overdrawn account shows up there)."""
    side = "debit" if balance >= 0 else "credit"
    if column == side:
        return abs(balance)
    return None


def advances_context():
    """Legacy compatibility import — returns empty context; original impl lived
    in this module before the Phase-3 AP services split."""
    from apps.ap.models import AdvanceToEmployee

    rows = []
    for adv in AdvanceToEmployee.objects.select_related("segment", "rfp").order_by("-granted_date"):
        rows.append(
            {
                "advance": adv,
                "kind": adv.get_kind_display(),
                "segment_code": adv.segment.code,
                "outstanding": adv.outstanding,
                "status_label": adv.status.replace("_", " ").title(),
            }
        )
    outstanding = sum(r["outstanding"] for r in rows)
    return {
        "rows": rows,
        "total_outstanding": outstanding,
        "segments": list(Segment.objects.order_by("code")),
        "summary": {
            "total": len(rows),
            "active": sum(1 for r in rows if r["outstanding"] > 0),
            "liquidated": sum(1 for r in rows if r["outstanding"] <= 0),
            "total_outstanding": outstanding,
        },
    }
