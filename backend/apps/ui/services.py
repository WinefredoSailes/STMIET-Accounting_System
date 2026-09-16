"""Query helpers for the server-rendered UI.

Thin read models over the bounded-context apps. The UI never mutates data
directly — mutations go through the context services (via views.py), exactly
as the DRF API does.
"""

from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.money import money
from apps.foundation.calendar import cycle_range_for
from apps.foundation.models import FiscalPeriod, Segment
from apps.posting.models import JournalEntry, PostingStatus
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
    from apps.ap.services import ap_payable_map, rfp_payable

    ap_map = ap_payable_map()
    total = pending = approved = posted = Decimal("0.00")
    total_n = pending_n = approved_n = 0
    for rfp in RFPDocument.objects.prefetch_related("lines"):
        payable = rfp_payable(rfp, ap_segment_map=ap_map)
        total += payable
        total_n += 1
        if rfp.status == "posted":
            posted += payable
        elif rfp.status in ("fin_approved", "cnr_approved"):
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
    posted_qs = PurchaseOrder.objects.filter(rfps__status="posted").distinct()
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


def list_pcf_funds():
    from apps.cash.models import PettyCashFund

    return PettyCashFund.objects.select_related("gl_account", "company", "custodian").order_by("fund_code")


def list_pcf_replenishments(*, limit=100):
    from apps.cash.models import PCFReplenishment

    return PCFReplenishment.objects.select_related(
        "fund__custodian", "fund__company", "requested_by"
    ).order_by("-request_date")[:limit]


def list_cv(*, limit=100):
    from apps.ap.models import CheckVoucher

    return CheckVoucher.objects.select_related("payee", "bank_account", "rfp").order_by("-cv_date")[:limit]


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

    return RFPDocument.objects.filter(
        status__in=["fin_approved", "cnr_approved"], conso__isnull=True
    ).select_related("payee", "segment")


def list_conso(*, limit=50):
    from apps.ap.models import CONSOBatch

    return CONSOBatch.objects.prefetch_related("rfps").order_by("-conso_date")[:limit]


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


def list_cash_shorts(*, limit=100):
    from apps.cash.models import CashShortExcessWorksheet

    return CashShortExcessWorksheet.objects.select_related("cycle", "segment").order_by("-cycle__cycle_start")[:limit]


def book_balance(cycle, bank):
    """Posted GL balance for the bank's GL account up to cycle end (ADR-026)."""
    from apps.posting.models import GeneralLedger

    return (
        GeneralLedger.objects.filter(
            account=bank.gl_account,
            segment=cycle.segment,
            entry__status="posted",
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
    return list(rows)


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
    return parties


def general_journal(*, start=None, end=None, segment=None, limit=500):
    """Posted entries with per-line rows: Date | Cycle | Ref | Party | PO |
    Description | CoA | Account Name | Debit | Credit. Party derives from the
    source document masters (AR receipt customer / AP payee), never stale
    copies on the JE."""
    from apps.posting.models import PostingStatus

    party_by = _source_parties()

    qs = (
        JournalEntry.objects.filter(status=PostingStatus.POSTED)
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
        "register": register,
        "register_total": sum(r["balance"] for r in register),
        "not_yet_due": not_yet_due,
        "not_yet_due_total": sum(r["balance"] for r in not_yet_due),
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
    from apps.ap.services import ap_payable_map, rfp_payable

    ap_map = ap_payable_map()

    cleared = {
        row["rfp_id"]: row["paid"] or Decimal("0.00")
        for row in (
            CheckVoucher.objects.filter(journal_entry__isnull=False)
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
        .select_related("payee", "segment")
        .prefetch_related("lines")
        .order_by("rfp_date")
    ):
        payable = rfp_payable(rfp, ap_segment_map=ap_map)
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
        "register": register,
        "register_total": sum(r["balance"] for r in register),
        "not_yet_due": not_yet_due,
        "not_yet_due_total": sum(r["balance"] for r in not_yet_due),
    }


def advances_context():
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

    banks = BankAccount.objects.filter(is_active=True).select_related("company", "gl_account").order_by("code")
    return {
        "banks": banks,
        "transfers": InterAccountTransfer.objects.select_related("from_account", "to_account", "journal_entry").order_by("-transfer_date"),
    }


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
            GeneralLedger.objects.filter(entry__status="posted", entry__company=company)
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
        entry__status=PostingStatus.POSTED, entry__company=company
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
        entry__status=PostingStatus.POSTED, entry__company=company, account=account
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
