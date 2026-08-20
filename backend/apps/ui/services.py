"""Query helpers for the server-rendered UI.

Thin read models over the bounded-context apps. The UI never mutates data
directly — mutations go through the context services (via views.py), exactly
as the DRF API does.
"""

from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from apps.foundation.calendar import cycle_range_for
from apps.foundation.models import FiscalPeriod, Segment
from apps.posting.models import JournalEntry, PostingStatus
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
    def generate(cls, *, statement_type, period_start, period_end, user=None):
        from apps.reporting.services import FinancialStatementService

        StatementTemplateService.seed_defaults()  # layouts must exist to generate
        return FinancialStatementService.generate(
            company=cls._company(),
            statement_type=statement_type,
            period_start=date.fromisoformat(period_start),
            period_end=date.fromisoformat(period_end),
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

    return Supplier.objects.order_by("name")


def list_rfps(*, limit=100):
    from apps.ap.models import RFPDocument

    return RFPDocument.objects.select_related("payee", "segment").order_by("-created_at")[:limit]


def rfp_summary():
    """Counts/amounts by stage for the RFP list stat cards."""
    from django.db.models import Sum

    from apps.ap.models import RFPDocument

    pending_qs = RFPDocument.objects.exclude(status__in=["posted", "rejected"])
    approved_qs = RFPDocument.objects.filter(status__in=["fin_approved", "cnr_approved"])
    return {
        "total": RFPDocument.objects.count(),
        "total_amount": RFPDocument.objects.aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "pending": pending_qs.count(),
        "pending_amount": pending_qs.aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "approved": approved_qs.count(),
        "approved_amount": approved_qs.aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
        "posted_amount": RFPDocument.objects.filter(status="posted").aggregate(t=Sum("amount"))["t"] or Decimal("0.00"),
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
    if rfp.amount > Decimal("100000.00"):
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

    return PettyCashFund.objects.select_related("gl_account", "segment", "custodian").order_by("fund_code")


def list_pcf_replenishments(*, limit=100):
    from apps.cash.models import PCFReplenishment

    return PCFReplenishment.objects.select_related("fund__custodian", "fund__segment").order_by("-request_date")[:limit]


def list_cv(*, limit=100):
    from apps.ap.models import CheckVoucher

    return CheckVoucher.objects.select_related("payee", "bank_account", "rfp").order_by("-cv_date")[:limit]


def bank_accounts():
    """GL accounts usable as CV/transfer bank accounts (100xx, postable)."""
    from apps.foundation.models import Account

    return Account.objects.filter(
        is_postable=True, account_type="asset", code__startswith="100"
    ).order_by("code")


def approved_rfps():
    """RFPs ready to be paid by a check voucher (no CV issued yet)."""
    from apps.ap.models import RFPDocument

    return RFPDocument.objects.filter(
        status__in=["fin_approved", "cnr_approved"], cv__isnull=True
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
    """Members (with their per-RFP posting state) + running total."""
    members = list(batch.rfps.select_related("payee", "segment").order_by("ap_number"))
    total = sum((m.amount for m in members), Decimal("0.00"))
    return {"batch": batch, "members": members, "total": total}


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
    """Asset GL accounts not yet claimed by a PCF fund (OneToOne)."""
    from apps.foundation.models import Account

    return Account.objects.filter(
        is_postable=True, account_type="asset", pcf_fund__isnull=True
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


def list_assets(*, limit=100):
    from apps.assets.models import Asset

    return Asset.objects.select_related("category", "segment").order_by("asset_no")[:limit]


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


def general_journal(*, start=None, end=None, segment=None, limit=500):
    """Posted entries with per-line rows: Date | Cycle | Ref | Party | PO |
    Description | CoA | Account Name | Debit | Credit. Party derives from the
    source document masters (AR receipt customer / AP payee), never stale
    copies on the JE."""
    from apps.ap.models import CheckVoucher, RFPDocument
    from apps.ar.models import AcknowledgmentReceipt
    from apps.posting.models import PostingStatus

    party_by = {}
    for r in AcknowledgmentReceipt.objects.exclude(journal_entry__isnull=True).select_related("customer"):
        party_by[r.receipt_no] = r.customer.name
    for doc in RFPDocument.objects.exclude(journal_entry__isnull=True).select_related("payee"):
        party_by[doc.ap_number] = doc.payee.name if doc.payee else ""
    for cv in CheckVoucher.objects.exclude(journal_entry__isnull=True).select_related("payee"):
        party_by[cv.cv_number] = cv.payee.name if cv.payee else ""

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
        cycle_start, cycle_end = cycle_range_for(entry.transaction_date)
        if cycle_start.month == cycle_end.month:
            cycle_label = f"{cycle_start:%b} {cycle_start.day}-{cycle_end.day}, {cycle_start:%Y}"
        else:
            cycle_label = f"{cycle_start:%b} {cycle_start.day} - {cycle_end:%b} {cycle_end.day}, {cycle_end:%Y}"
        party = party_by.get(entry.source_doc_no, "") if entry.source_doc_no else ""
        balanced = entry.is_balanced
        for line in entry.lines.all():
            rows.append(
                {
                    "new_entry": True,
                    "date": entry.transaction_date,
                    "cycle": cycle_label,
                    "ref": entry.entry_no,
                    "source_type": entry.source_doc_type,
                    "party": party,
                    "po": "",
                    "description": line.description or entry.description,
                    "coa": line.account.code,
                    "account_name": line.account.name,
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
    """Segments pickable on the Cash Flow screen."""
    return {"segments": list(Segment.objects.order_by("code"))}


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
    for inv in (
        ARInvoice.objects.filter(status__in=("open", "partially_paid"))
        .select_related("customer", "segment")
        .order_by("transaction_date")
    ):
        balance = inv.balance
        if balance <= 0:
            continue
        age_days = max((as_of - inv.transaction_date).days, 0)
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

    banks = BankAccount.objects.filter(is_active=True).select_related("segment", "gl_account").order_by("code")
    return {
        "banks": banks,
        "transfers": InterAccountTransfer.objects.select_related("from_account", "to_account", "journal_entry").order_by("-transfer_date"),
    }
