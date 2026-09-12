"""Server-rendered UI views (Django templates + HTMX).

Every screen here is a thin HTML layer over the bounded-context services —
no business logic lives in this app (ADR-009). Forms post to the same
service functions the DRF API uses, so the UI and the API can never drift.
"""

from datetime import date, timedelta
from decimal import Decimal
import json

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponseRedirect, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.exceptions import AccountingError, ValidationError
from apps.core.approvals import get_approval_role, require_can_create_master, require_can_edit_master
from apps.core.money import approve_threshold, money
from apps.foundation.models import Account, AccountType, Company, CostCenter, FiscalPeriod, Segment
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService
from apps.sequences.models import DocumentSequence

from .services import (
    StatementService,
    TrialBalanceService,
    advances_context,
    aging_context,
    approved_rfps,
    asset_context,
    book_balance,
    cash_flow_options,
    collectibles_cycle_options,
    conso_context,
    daily_collections,
    list_assets,
    list_banks,
    list_cash_shorts,
    list_conso,
    list_customers,
    list_cv,
    list_cycles,
    list_entries,
    list_pcf_funds,
    list_pcf_replenishments,
    list_receipts,
    list_recons,
    list_rfps,
    list_suppliers,
    month_end_close_context,
    rfp_summary,
    rfp_timeline,
    transfers_context,
    unassigned_approved_rfps,
)

AUDIT_ACTION_LABELS = {
    "created": "Created",
    "submitted": "Submitted",
    "checked": "Checked / Recommending approval",
    "acctg_approved": "Approved — Accounting",
    "fin_approved": "Approved — Finance",
    "cnr_approved": "Approved — COO (CNR)",
    "rejected": "Rejected",
    "revised": "Revised & resubmitted",
    "posted": "Posted to GL (CONSO)",
    "approved": "Approved",
    "cleared": "Cleared — JE posted to GL",
}


def _audit_trail(doc_type, doc_id):
    """Immutable action history for an RFP or Check Voucher, newest first."""
    from apps.ap.models import ActionLog

    return [
        {
            "label": AUDIT_ACTION_LABELS.get(
                e.action, e.action.replace("_", " ").title()
            ),
            "actor": e.actor.get_full_name() if e.actor else "",
            "at": e.created_at,
            "note": e.note,
        }
        for e in ActionLog.objects.filter(doc_type=doc_type, doc_id=doc_id)
    ]


def _coo_name() -> str:
    """Display name of the current COO role holder for the CV approval line.

    Pulled from the approval-role mapping (never hard-coded): the "Approved
    By" signature on the Check Voucher is the COO, not the Finance & Accounts
    Head (ACCTG-FOR-010 signatory layout)."""
    from apps.core.approvals import role_assignee

    return role_assignee("coo")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _page(request, seq, per_page=100):
    """Paginate a list for a list screen; page_obj + querystring to preserve."""
    page_obj = Paginator(list(seq), per_page).get_page(request.GET.get("page"))
    page_obj.pagination_params = {k: v for k, v in request.GET.items() if k != "page"}
    return page_obj


def login_view(request):
    if request.user.is_authenticated:
        return redirect("ui:dashboard")
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        return redirect("ui:dashboard")
    return render(request, "ui/login.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("ui:login")


# ---------------------------------------------------------------------------
# My Approvals (ADR-036): the named-person inbox, grouped by role
# ---------------------------------------------------------------------------


@login_required
def my_approvals(request):
    from apps.core.approvals import (
        get_approval_role,
        group_by_role,
        pending_approval_queue,
        role_assignee,
        ROLE_LABELS,
    )

    queues = pending_approval_queue(request.user)
    my_role = get_approval_role(request.user)
    return render(
        request,
        "ui/approvals.html",
        {
            "grouped": group_by_role(queues),
            "total": len(queues),
            "my_role": ROLE_LABELS.get(my_role, "no approval role"),
            "assignees": {r: role_assignee(r) for r in ("staff", "head", "coo")},
        },
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@login_required
def dashboard(request):
    today = date.today()
    period = (
        FiscalPeriod.objects.filter(
            start_date__lte=today, end_date__gte=today, is_closed=False
        )
        .order_by("-period_no")
        .first()
    )
    counts = dict(
        JournalEntry.objects.aggregate(
            total=Count("id"),
            posted=Count("id", filter=Q(status=PostingStatus.POSTED)),
            draft=Count("id", filter=Q(status=PostingStatus.DRAFT)),
        )
    )
    close = month_end_close_context()
    recent = list_entries(limit=8)
    return render(
        request,
        "ui/dashboard.html",
        {
            "current_period": period,
            "entry_counts": counts,
            "close": close,
            "recent_entries": recent,
        },
    )


# ---------------------------------------------------------------------------
# Posting (Journal Entries)
# ---------------------------------------------------------------------------


@login_required
def je_list(request):
    return render(request, "ui/posting/je_list.html", {"page_obj": _page(request, list_entries(limit=None))})


@login_required
def je_detail(request, pk):
    entry = get_object_or_404(
        JournalEntry.objects.prefetch_related("lines__account", "lines__segment"), pk=pk
    )
    return render(request, "ui/posting/je_detail.html", {"entry": entry})


@login_required
def je_create(request):
    company = Company.objects.first()
    if request.method == "POST":
        try:
            entry = _create_entry_from_form(request)
            messages.success(request, f"Entry {entry.entry_no} saved as draft.")
            return redirect("ui:je_detail", pk=entry.id)
        except (AccountingError, ValueError, KeyError) as exc:
            messages.error(request, str(exc))
    ctx = {
        "company": company,
        "segments": Segment.objects.order_by("code"),
        "today": date.today(),
    }
    return render(request, "ui/posting/je_form.html", ctx)


def _create_entry_from_form(request):
    """Build a draft JE from the form POST (lines as parallel arrays)."""
    company_id = request.POST.get("company")
    company = (
        Company.objects.filter(pk=company_id).first()
        if company_id
        else Company.objects.first()
    )
    if company is None:
        raise ValueError("No company configured.")
    transaction_date = date.fromisoformat(request.POST["transaction_date"])
    source_doc_type = request.POST.get("source_doc_type", "").strip()[:16]
    source_doc_no = request.POST.get("source_doc_no", "").strip()[:32]

    period = (
        FiscalPeriod.objects.filter(
            start_date__lte=transaction_date, end_date__gte=transaction_date
        ).first()
    )

    accounts = request.POST.getlist("account")
    seg_ids = request.POST.getlist("line_segment")
    debits = request.POST.getlist("debit")
    credits = request.POST.getlist("credit")
    descs = request.POST.getlist("line_description")

    parsed = []
    for i, account_id in enumerate(accounts):
        if not account_id:
            continue
        debit = money((debits[i] if i < len(debits) else "") or 0)
        credit = money((credits[i] if i < len(credits) else "") or 0)
        if not debit and not credit:
            continue
        account = Account.objects.filter(pk=account_id).first()
        if account is None:
            raise ValueError("Unknown account in line.")
        seg_id = seg_ids[i] if i < len(seg_ids) else ""
        line_segment = Segment.objects.filter(pk=seg_id).first() if seg_id else None
        if not line_segment:
            legacy = request.POST.get("segment")
            line_segment = Segment.objects.filter(pk=legacy).first() if legacy else None
        if line_segment is None:
            raise ValueError(f"Line {i + 1}: select a segment.")
        parsed.append(
            {
                "account": account,
                "segment": line_segment,
                "description": (descs[i] if i < len(descs) else "")[:500],
                "debit": debit,
                "credit": credit,
            }
        )
    if not parsed:
        raise ValueError("Add at least one line with an amount.")

    header_segment = parsed[0]["segment"]
    header_description = next((p["description"].strip() for p in parsed if p["description"].strip()), "")[:500]
    if not header_description:
        header_description = f"{source_doc_type} {source_doc_no}".strip() or f"Journal entry {transaction_date.isoformat()}"
    legacy_description = request.POST.get("description", "").strip()[:500]
    if legacy_description:
        header_description = legacy_description

    # Concurrent submissions can allocate the same entry number (SQLite ignores
    # SELECT ... FOR UPDATE; PostgreSQL races on the fresh sequence row). The
    # number is allocated in its own committed transaction so the counter
    # advances even if the insert below fails — the retry then picks up the next
    # available number instead of re-allocating the same one forever.
    last_exc = None
    for _ in range(8):
        entry_no = DocumentSequence.next_number(
            company=company, form_code="JE", year=transaction_date.year
        )
        try:
            with transaction.atomic():
                entry = JournalEntry.objects.create(
                    entry_no=entry_no,
                    company=company,
                    segment=header_segment,
                    fiscal_period=period,
                    transaction_date=transaction_date,
                    status=PostingStatus.DRAFT,
                    description=header_description,
                    source_doc_type=source_doc_type,
                    source_doc_no=source_doc_no,
                    created_by=request.user,
                )
                for i, p in enumerate(parsed, start=1):
                    JournalEntryLine.objects.create(
                        entry=entry,
                        line_no=i,
                        account=p["account"],
                        segment=p["segment"],
                        description=p["description"],
                        debit=p["debit"],
                        credit=p["credit"],
                    )
                entry.recalc_totals()
                return entry
        except IntegrityError as exc:
            last_exc = exc
    raise last_exc


def _rfp_lines_from_form(request):
    """Parse the RFP Dr/Cr line grid (parallel arrays) into line dicts.

    Each row is a single RFP line (RFPLine carries one side + amount): the
    amount must be entered in exactly one of the Debit or Credit columns. A
    row with both filled is rejected rather than split across two lines.
    """
    seg_ids = request.POST.getlist("line_segment")
    codes = request.POST.getlist("line_account")
    debits = request.POST.getlist("line_debit")
    credits = request.POST.getlist("line_credit")
    descs = request.POST.getlist("line_description")
    lines = []
    for i, code in enumerate(codes):
        seg_id = seg_ids[i] if i < len(seg_ids) else ""
        if not code or not seg_id:
            continue
        debit = money((debits[i] if i < len(debits) else 0) or 0)
        credit = money((credits[i] if i < len(credits) else 0) or 0)
        if not debit and not credit:
            continue
        if debit and credit:
            raise ValidationError(
                f"Line {i + 1}: enter the amount in only one of Debit or Credit."
            )
        lines.append(
            {
                "side": "dr" if debit else "cr",
                "segment": Segment.objects.get(pk=seg_id),
                "account_code": code,
                "amount": debit or credit,
                "description": (descs[i] if i < len(descs) else "")[:500],
            }
        )
    return lines


@login_required
@require_POST
def je_submit(request, pk):
    """Staff submits a draft JE for head approval."""
    entry = get_object_or_404(JournalEntry, pk=pk)
    if entry.created_by_id != request.user.id:
        messages.error(request, "Only the preparer may submit this entry.")
        return redirect("ui:je_detail", pk=pk)
    if entry.status != PostingStatus.DRAFT:
        messages.error(request, "Only draft entries can be submitted.")
        return redirect("ui:je_detail", pk=pk)
    if not entry.lines.exists():
        messages.error(request, "Entry has no lines.")
        return redirect("ui:je_detail", pk=pk)
    try:
        entry.status = PostingStatus.SUBMITTED
        entry.approved_by = None
        entry.approved_at = None
        entry.rejected_by = None
        entry.rejected_at = None
        entry.rejection_note = ""
        entry.save(update_fields=["status", "approved_by", "approved_at", "rejected_by", "rejected_at", "rejection_note", "updated_at"])
        from apps.ap.services import log_action
        log_action(entry, "submitted", actor=request.user)
        messages.success(request, f"Entry {entry.entry_no} submitted for approval.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("ui:je_detail", pk=pk)


@login_required
@require_POST
def je_approve(request, pk):
    """Head approves a submitted JE (head self-approve allowed)."""
    entry = get_object_or_404(JournalEntry, pk=pk)
    from apps.core.approvals import require_approval_role
    try:
        require_approval_role(request.user, "head")
        if entry.status != PostingStatus.SUBMITTED:
            raise ValueError("Only submitted entries can be approved.")
        entry.status = PostingStatus.APPROVED
        entry.approved_by = request.user
        entry.approved_at = timezone.now()
        entry.rejected_by = None
        entry.rejected_at = None
        entry.rejection_note = ""
        entry.save(update_fields=["status", "approved_by", "approved_at", "rejected_by", "rejected_at", "rejection_note", "updated_at"])
        from apps.ap.services import log_action
        log_action(entry, "approved", actor=request.user)
        messages.success(request, f"Entry {entry.entry_no} approved.")
    except (ValueError, AccountingError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:je_detail", pk=pk)


@require_POST
@login_required
def je_reject(request, pk):
    """Head rejects a submitted JE, returning it to draft with a note."""
    entry = get_object_or_404(JournalEntry, pk=pk)
    from apps.core.approvals import require_approval_role
    try:
        require_approval_role(request.user, "head")
        if entry.status != PostingStatus.SUBMITTED:
            raise ValueError("Only submitted entries can be rejected.")
        note = request.POST.get("note", "").strip()
        if not note:
            raise ValueError("Rejection note is required.")
        entry.status = PostingStatus.DRAFT
        entry.rejected_by = request.user
        entry.rejected_at = timezone.now()
        entry.rejection_note = note
        entry.approved_by = None
        entry.approved_at = None
        entry.save(update_fields=["status", "rejected_by", "rejected_at", "rejection_note", "approved_by", "approved_at", "updated_at"])
        from apps.ap.services import log_action
        log_action(entry, "rejected", actor=request.user, note=note)
        messages.success(request, f"Entry {entry.entry_no} rejected and returned to draft.")
    except (ValueError, AccountingError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:je_detail", pk=pk)


@require_POST
@login_required
def je_post(request, pk):
    """Post an approved JE. Only approved entries may be posted."""
    entry = get_object_or_404(JournalEntry, pk=pk)
    from apps.ap.models import CheckVoucher

    cv = CheckVoucher.objects.filter(journal_entry_id=entry.id).first()
    if cv and cv.status != "cleared":
        messages.error(
            request,
            f"CV {cv.cv_number} posts only when the Accounting Head clears the "
            "voucher — its entry must not be posted manually.",
        )
        return redirect("ui:je_detail", pk=pk)
    if entry.status != PostingStatus.APPROVED:
        messages.error(request, "Only approved entries can be posted.")
        return redirect("ui:je_detail", pk=pk)
    try:
        posted = PostingService.post(entry, approver=request.user, user=request.user)
        messages.success(request, f"Entry {posted.entry_no} posted.")
    except AccountingError as exc:
        messages.error(request, str(exc))
    return redirect("ui:je_detail", pk=pk)


@login_required
def je_edit(request, pk):
    """Creator edits a draft JE (reuses je_form.html)."""
    entry = get_object_or_404(JournalEntry, pk=pk)
    if entry.status != PostingStatus.DRAFT:
        messages.error(request, "Only draft entries can be edited.")
        return redirect("ui:je_detail", pk=pk)
    if entry.created_by_id != request.user.id and not request.user.is_superuser:
        messages.error(request, "Only the creator or a super admin may edit this entry.")
        return redirect("ui:je_detail", pk=pk)
    if request.method == "POST":
        try:
            updated_entry = _update_entry_from_form(request, entry)
            messages.success(request, f"Entry {updated_entry.entry_no} updated.")
            return redirect("ui:je_detail", pk=updated_entry.id)
        except (AccountingError, ValueError, KeyError) as exc:
            messages.error(request, str(exc))
    ctx = {
        "company": entry.company,
        "segments": Segment.objects.order_by("code"),
        "accounts": Account.objects.filter(is_postable=True).order_by("code"),
        "today": entry.transaction_date,
        "editing": entry,
    }
    return render(request, "ui/posting/je_form.html", ctx)


@login_required
def je_print(request, pk):
    """Print-optimized Journal Entry (RFP 3-signature style)."""
    from apps.core.approvals import signatory_name
    entry = get_object_or_404(
        JournalEntry.objects.select_related("company", "segment", "approved_by")
            .prefetch_related("lines__account", "lines__segment"),
        pk=pk,
    )
    lines = list(entry.lines.order_by("line_no"))
    requested_by = signatory_name(entry.created_by)
    checked_by = signatory_name(entry.approved_by) if entry.approved_by else ""
    # For approved entries without explicit approved_by, use the head role assignee
    if not checked_by and entry.status == PostingStatus.APPROVED:
        from apps.core.approvals import role_assignee
        checked_by = role_assignee("head")
    return render(
        request,
        "ui/posting/je_print.html",
        {
            "entry": entry,
            "lines": lines,
            "total": entry.total_debit,
            "requested_by": requested_by,
            "checked_by": checked_by,
            "approved_by": checked_by,  # Same as checked for 3-sig
        },
    )


def _update_entry_from_form(request, entry):
    """Update an existing draft JE from form POST (mirrors _create_entry_from_form)."""
    transaction_date = date.fromisoformat(request.POST["transaction_date"])
    source_doc_type = request.POST.get("source_doc_type", "").strip()[:16]
    source_doc_no = request.POST.get("source_doc_no", "").strip()[:32]

    period = (
        FiscalPeriod.objects.filter(
            start_date__lte=transaction_date, end_date__gte=transaction_date
        ).first()
    )

    accounts = request.POST.getlist("account")
    seg_ids = request.POST.getlist("line_segment")
    debits = request.POST.getlist("debit")
    credits = request.POST.getlist("credit")
    descs = request.POST.getlist("line_description")

    parsed = []
    for i, account_id in enumerate(accounts):
        if not account_id:
            continue
        debit = money((debits[i] if i < len(debits) else "") or 0)
        credit = money((credits[i] if i < len(credits) else "") or 0)
        if not debit and not credit:
            continue
        account = Account.objects.filter(pk=account_id).first()
        if account is None:
            raise ValueError("Unknown account in line.")
        seg_id = seg_ids[i] if i < len(seg_ids) else ""
        line_segment = Segment.objects.filter(pk=seg_id).first() if seg_id else None
        if not line_segment:
            raise ValueError(f"Line {i + 1}: select a segment.")
        parsed.append(
            {
                "account": account,
                "segment": line_segment,
                "description": (descs[i] if i < len(descs) else "")[:500],
                "debit": debit,
                "credit": credit,
            }
        )
    if not parsed:
        raise ValueError("Add at least one line with an amount.")

    header_segment = parsed[0]["segment"]
    header_description = next((p["description"].strip() for p in parsed if p["description"].strip()), "")[:500]
    if not header_description:
        header_description = f"{source_doc_type} {source_doc_no}".strip() or f"Journal entry {transaction_date.isoformat()}"

    with transaction.atomic():
        entry.transaction_date = transaction_date
        entry.segment = header_segment
        entry.description = header_description
        entry.source_doc_type = source_doc_type
        entry.source_doc_no = source_doc_no
        entry.fiscal_period = period
        entry.save(update_fields=["transaction_date", "segment", "description", "source_doc_type", "source_doc_no", "fiscal_period", "updated_at"])

        # Delete existing lines and recreate
        entry.lines.all().delete()
        for i, p in enumerate(parsed, start=1):
            JournalEntryLine.objects.create(
                entry=entry,
                line_no=i,
                account=p["account"],
                segment=p["segment"],
                description=p["description"],
                debit=p["debit"],
                credit=p["credit"],
            )
        entry.recalc_totals()
    return entry


@login_required
def je_reverse(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk)
    # Reversal not yet exposed as a service action in v1; show the rules page.
    messages.info(request, "Reversal is planned; corrections follow ADR-004 via a reversing entry.")
    return redirect("ui:je_detail", pk=pk)


# ---------------------------------------------------------------------------
# Trial Balance / Statements
# ---------------------------------------------------------------------------


@login_required
def trial_balance(request):
    as_of = request.GET.get("as_of") or date.today().isoformat()
    segment = request.GET.get("segment") or ""
    rows, totals = TrialBalanceService.rows(as_of=as_of, segment=segment or None)
    return render(
        request,
        "ui/reporting/trial_balance.html",
        {
            "rows": rows,
            "totals": totals,
            "as_of": as_of,
            "segment": segment,
            "segments": Segment.objects.order_by("code"),
        },
    )


@login_required
def trial_balance_export(request):
    """Download trial balance as XLSX / CSV / PDF."""
    fmt = request.GET.get("format", "xlsx")
    company = Company.objects.first()
    year = int(request.GET.get("year") or date.today().year)

    from apps.ui.services import TrialBalanceService
    rows, (debit, credit) = TrialBalanceService.rows(as_of=f"{year}-12-31")

    if fmt == "csv":
        header = ["Code", "Account", "Segment", "Normal Balance", "Balance"]
        data = [[r["code"], r["name"], r["segment"], r["normal_balance"], r["balance"]] for r in rows]
        return csv_response(data, f"TRIAL-BALANCE-{year}.csv", header=header)

    if fmt == "pdf":
        column_labels = ["Code", "Account", "Segment", "Normal Balance", "Balance"]
        data = [[r["code"], r["name"], r["segment"], r["normal_balance"], r["balance"]] for r in rows]
        return pdf_response("Trial Balance", column_labels, data, f"TRIAL-BALANCE-{year}.pdf")

    # default: XLSX (existing builder)
    from apps.reporting.excel_export import build_trial_balance, xlsx_response
    return xlsx_response(build_trial_balance(company, year), f"TRIAL-BALANCE-{year}.xlsx")


@login_required
def trial_balance_print(request):
    """Print‑optimized page for the trial balance (browser print dialog)."""
    as_of = request.GET.get("as_of") or date.today().isoformat()
    segment = request.GET.get("segment") or ""
    from apps.ui.services import TrialBalanceService

    rows, (debit, credit) = TrialBalanceService.rows(as_of=as_of, segment=segment or None)
    ctx = {
        "rows": rows,
        "debit": debit,
        "credit": credit,
        "as_of": as_of,
        "segment": segment,
    }
    return render(request, "ui/reporting/trial_balance_print.html", ctx)


@login_required
def statement_export(request, statement_type):
    """Download a financial statement (sfp/soce/cos/te) as XLSX / CSV / PDF."""
    from apps.reporting.excel_export import (
        build_statement_of_changes_in_equity,
        build_statement_of_cost_of_sales,
        build_statement_of_financial_position,
        build_statement_of_total_expenses,
        xlsx_response,
    )
    from apps.reporting.exports import csv_response, pdf_response
    from apps.reporting.models import StatementType
    from apps.reporting.services import StatementTemplateService

    StatementTemplateService.seed_defaults()
    fmt = request.GET.get("format", "xlsx")
    company = Company.objects.first()
    period_start = date.fromisoformat(request.GET.get("period_start") or f"{date.today().year - 1}-01-01")
    period_end = date.fromisoformat(request.GET.get("period_end") or date.today().replace(month=12, day=31))

    builders = {
        "sfp": ("STATEMENT-OF-FINANCIAL-POSITION", build_statement_of_financial_position),
        "soce": ("STATEMENT-OF-CHANGES-IN-EQUITY", build_statement_of_changes_in_equity),
        "cos": ("STATEMENT-OF-COST-OF-SALES", build_statement_of_cost_of_sales),
        "te": ("STATEMENT-OF-TOTAL-EXPENSES", build_statement_of_total_expenses),
    }
    if statement_type not in builders:
        raise Http404

    if fmt == "csv":
        stem, builder = builders[statement_type]
        wb = builder(company, period_start, period_end)
        from apps.reporting.services import FinancialStatementService
        StatementTemplateService.seed_defaults()
        fs = FinancialStatementService.generate(
            company=company, statement_type=StatementType(statement_type),
            period_start=period_start, period_end=period_end,
        )
        rows = fs.rows_by_key()
        header = ["Account"]
        for seg in fs.segments:
            header.append(seg.code)
        header.append("GRAND")
        data = []
        for key in sorted(rows.keys()):
            row = [fs.row_title(key)] if fs.row_title(key) else []
            for seg in fs.segments:
                row.append(rows[key]["amounts"].get(seg, "0.00"))
            row.append(rows[key]["amounts"].get("GRAND", "0.00"))
            data.append(row)
        return csv_response(data, f"{stem}-{period_start:%Y%m%d}-{period_end:%Y%m%d}.csv", header=header)

    if fmt == "pdf":
        stem, builder = builders[statement_type]
        wb = builder(company, period_start, period_end)
        from apps.reporting.services import FinancialStatementService
        StatementTemplateService.seed_defaults()
        fs = FinancialStatementService.generate(
            company=company, statement_type=StatementType(statement_type),
            period_start=period_start, period_end=period_end,
        )
        rows = fs.rows_by_key()
        column_labels = ["Account"] + [seg.code for seg in fs.segments] + ["GRAND"]
        data = []
        for key in sorted(rows.keys()):
            row = [fs.row_title(key)] if fs.row_title(key) else []
            for seg in fs.segments:
                row.append(rows[key]["amounts"].get(seg, "0.00"))
            row.append(rows[key]["amounts"].get("GRAND", "0.00"))
            data.append(row)
        return pdf_response(stem, column_labels, data, f"{stem}-{period_start:%Y%m%d}-{period_end:%Y%m%d}.pdf")

    # default: XLSX (existing builder with net_profit if needed)
    stem, builder = builders[statement_type]
    if statement_type in ("cos", "te"):
        wb = builder(company, period_start, period_end)
    else:
        wb = builder(company, period_start, period_end, request.GET.get("net_profit"))
    return xlsx_response(wb, f"{stem}-{period_start:%Y%m%d}-{period_end:%Y%m%d}.xlsx")


@login_required
def statement_print(request, statement_type):
    """Print‑optimized page for a financial statement (browser print dialog)."""
    from apps.foundation.models import Company
    from apps.reporting.models import StatementType
    from apps.reporting.services import FinancialStatementService, StatementTemplateService
    from apps.foundation.models import Segment

    company = Company.objects.first()
    StatementTemplateService.seed_defaults()
    period_start = request.GET.get("period_start") or f"{date.today().year - 1}-01-01"
    period_end = request.GET.get("period_end") or date.today().replace(month=12, day=31)

    fs = FinancialStatementService.generate(
        company=company, statement_type=StatementType(statement_type),
        period_start=period_start, period_end=period_end,
    )
    rows = fs.rows_by_key()
    segments = list(company.segments.order_by("code")) if company else []

    ctx = {
        "statement_type": statement_type,
        "label": StatementService.STATEMENT_LABELS.get(statement_type, statement_type),
        "rows": rows,
        "segments": segments,
        "period_start": period_start,
        "period_end": period_end,
    }
    return render(request, "ui/reporting/statement_print.html", ctx)


@login_required
def month_end_close(request):
    """Print‑optimized page for the trial balance (browser print dialog)."""
    as_of = request.GET.get("as_of") or date.today().isoformat()
    segment = request.GET.get("segment") or ""
    from apps.ui.services import TrialBalanceService

    rows, (debit, credit) = TrialBalanceService.rows(as_of=as_of, segment=segment or None)
    ctx = {
        "rows": rows,
        "debit": debit,
        "credit": credit,
        "as_of": as_of,
        "segment": segment,
        "segments": ...,  # placeholder; template only uses rows/debit/credit
    }
    return render(request, "ui/reporting/trial_balance_print.html", ctx)


@login_required
def cash_flow_export(request):
    """Download STATEMENT-OF-CASH-FLOW.xlsx CF mirror for a cycle period."""
    from apps.foundation.models import Company
    from apps.reporting.excel_export import build_cash_flow_statement, xlsx_response

    company = Company.objects.get(pk=request.GET.get("company"))
    period_start = date.fromisoformat(request.GET.get("period_start"))
    period_end = date.fromisoformat(request.GET.get("period_end"))
    wb = build_cash_flow_statement(company, period_start, period_end)
    return xlsx_response(
        wb, f"STATEMENT-OF-CASH-FLOW-{period_start:%Y%m%d}-{period_end:%Y%m%d}.xlsx"
    )


@login_required
def statement(request, statement_type):
    if request.method == "POST":
        try:
            fs = StatementService.generate(
                statement_type=statement_type,
                period_start=request.POST["period_start"],
                period_end=request.POST["period_end"],
                user=request.user,
            )
            messages.success(request, f"Statement generated: {fs}.")
        except (AccountingError, ValueError) as exc:
            messages.error(request, str(exc))
    ctx = StatementService.statement_context(statement_type)
    return render(request, "ui/reporting/statement.html", ctx)


@login_required
def month_end_close(request):
    ctx = month_end_close_context()
    return render(request, "ui/reporting/month_end_close.html", {"close": ctx})


@login_required
@require_POST
def month_end_advance(request):
    step = request.POST.get("step")
    try:
        close = month_end_close_context()
        from apps.reporting.services import MonthEndCloseService

        # The 'close' and 'appropriations' steps are not just checkboxes: they
        # post the §13 closing journal entries. Only mark the step done when
        # its posting succeeded, so a failed close blocks the final 'Close'.
        if step == "close":
            close = MonthEndCloseService.close_period(close, user=request.user)
        elif step == "appropriations":
            close = MonthEndCloseService.apply_appropriations(close, user=request.user)
        close = MonthEndCloseService.advance(close, step, user=request.user)
        messages.success(request, f"Step '{step}' marked done.")
    except (ValueError, AccountingError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:month_end_close")


@login_required
@require_POST
def month_end_complete(request):
    try:
        close = month_end_close_context()
        from apps.reporting.services import MonthEndCloseService

        MonthEndCloseService.complete(close, user=request.user)
        messages.success(request, "Period closed.")
    except (ValueError, AccountingError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:month_end_close")


# ---------------------------------------------------------------------------
# AR / AP / Cash / Assets — list screens
# ---------------------------------------------------------------------------


@login_required
def customer_list(request):
    return render(request, "ui/ar/customer_list.html", {"page_obj": _page(request, list_customers())})


@login_required
def receipt_list(request):
    return render(request, "ui/ar/receipt_list.html", {"page_obj": _page(request, list_receipts(limit=None))})


@login_required
def supplier_list(request):
    return render(request, "ui/ap/supplier_list.html", {"page_obj": _page(request, list_suppliers())})


def _rfp_approval_info(rfp, role):
    """Inline-approval facts for one RFP row (HTMX row swap).

    Mirror of apps.core.approvals.RFP_NEXT_ROLE / rfp_queue: `can_act` is true
    only when the caller holds the role the RFP is waiting on.
    """
    from apps.core.approvals import RFP_NEXT_ROLE
    from apps.ap.services import coo_required

    next_role = RFP_NEXT_ROLE.get(rfp.status)
    if rfp.status == "fin_approved" and coo_required(rfp):
        next_role = "coo"
    can_act = bool(next_role) and role == next_role
    label = "Check" if rfp.status in ("prepared", "submitted") else "Approve"
    return {
        "has_action": can_act,
        "next_role": next_role,
        "label": label,
    }


@login_required
def rfp_list(request):
    from apps.core.approvals import approval_role_of

    role = approval_role_of(request.user)
    page = _page(request, list_rfps(limit=None))
    for rfp in page.object_list:
        rfp.approval_info = _rfp_approval_info(rfp, role)
    return render(
        request,
        "ui/ap/rfp_list.html",
        {"page_obj": page, "summary": rfp_summary()},
    )


@login_required
def bank_list(request):
    return render(request, "ui/cash/bank_list.html", {"page_obj": _page(request, list_banks())})


@login_required
def cycle_list(request):
    return render(request, "ui/cash/cycle_list.html", {"page_obj": _page(request, list_cycles(limit=None))})


@login_required
def asset_list(request):
    """Fixed Assets register — search + category/segment/status filters (HTMX)."""
    from apps.assets.models import AssetCategory, AssetStatus

    ctx = {
        "page_obj": _page(
            request,
            list_assets(
                limit=None,
                q=request.GET.get("q", "").strip(),
                category=request.GET.get("category", "").strip(),
                segment=request.GET.get("segment", "").strip(),
                status=request.GET.get("status", "").strip(),
            ),
        ),
        "q": request.GET.get("q", "").strip(),
        "category_sel": request.GET.get("category", "").strip(),
        "segment_sel": request.GET.get("segment", "").strip(),
        "status_sel": request.GET.get("status", "").strip(),
        "categories": AssetCategory.objects.filter(is_active=True).order_by("code"),
        "segments": Segment.objects.order_by("code"),
        "statuses": AssetStatus.choices,
    }
    template = (
        "ui/assets/_asset_rows.html"
        if request.headers.get("HX-Request")
        else "ui/assets/asset_list.html"
    )
    return render(request, template, ctx)


# ---------------------------------------------------------------------------
# AR — customer master + acknowledgment receipts (ACCTG-FOR-005)
# ---------------------------------------------------------------------------


@login_required
def customer_create(request):
    require_can_create_master(request.user)
    if request.method == "POST":
        try:
            from apps.ar.models import Customer

            Customer.objects.create(
                code=request.POST["code"].strip(),
                name=request.POST["name"].strip(),
                group=request.POST["group"],
                segment=Segment.objects.get(pk=request.POST["segment"]),
                pricing_tier=request.POST["pricing_tier"],
                tin=request.POST.get("tin", ""),
                address=request.POST.get("address", ""),
                contact_no=request.POST.get("contact_no", ""),
                owner_name=request.POST.get("owner_name", ""),
                notes=request.POST.get("notes", ""),
            )
            messages.success(request, "Customer created.")
            return redirect("ui:customer_list")
        except (IntegrityError, ValueError, ObjectDoesNotExist) as exc:
            messages.error(request, str(exc))
    return render(request, "ui/ar/customer_form.html", {"segments": Segment.objects.order_by("code")})


@login_required
def customer_update(request, pk):
    from apps.ar.models import Customer

    require_can_edit_master(request.user)
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == "POST":
        try:
            customer.code = request.POST["code"].strip()
            customer.name = request.POST["name"].strip()
            customer.group = request.POST["group"]
            customer.segment = Segment.objects.get(pk=request.POST["segment"])
            customer.pricing_tier = request.POST["pricing_tier"]
            customer.tin = request.POST.get("tin", "")
            customer.address = request.POST.get("address", "")
            customer.contact_no = request.POST.get("contact_no", "")
            customer.owner_name = request.POST.get("owner_name", "")
            customer.notes = request.POST.get("notes", "")
            customer.save()
            messages.success(request, "Customer updated.")
            return redirect("ui:customer_list")
        except (IntegrityError, ValueError, ObjectDoesNotExist) as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "ui/ar/customer_form.html",
        {"segments": Segment.objects.order_by("code"), "customer": customer, "editing": True},
    )


@login_required
def receipt_create(request):
    from apps.ar.models import Customer
    from apps.ar.services import CollectionService
    from apps.sequences.models import DocumentSequence

    if request.method == "POST":
        try:
            customer = Customer.objects.get(pk=request.POST["customer"])
            cash_account = Account.objects.get(pk=request.POST["cash_account"])
            receipt_no = DocumentSequence.next_number(
                company=customer.segment.company,
                form_code="AR",
                year=int(request.POST["transaction_date"][:4]),
            )
            receipt = CollectionService.record_collection(
                receipt_no=receipt_no,
                customer=customer,
                transaction_date=date.fromisoformat(request.POST["transaction_date"]),
                amount=request.POST["amount"],
                cash_account=cash_account,
                payment_method=request.POST["payment_method"],
                check_no=request.POST.get("check_no", ""),
                user=request.user,
            )
            messages.success(request, f"Receipt {receipt.receipt_no} posted.")
            return redirect("ui:receipt_list")
        except AccountingError as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "ui/ar/receipt_form.html",
        {
            "customers": list_customers(),
            "today": date.today(),
        },
    )


# ---------------------------------------------------------------------------
# AP — supplier master + RFP document (ACCTG-FOR-012)
# ---------------------------------------------------------------------------


@login_required
def supplier_create(request):
    require_can_create_master(request.user)
    if request.method == "POST":
        try:
            from apps.ap.models import Supplier
            from apps.ap.services import SupplierService

            segment = request.POST.get("default_segment")
            supplier = Supplier.objects.create(
                code=request.POST["code"].strip(),
                name=request.POST["name"].strip(),
                supplier_type=request.POST["supplier_type"],
                tin=request.POST.get("tin", ""),
                address=request.POST.get("address", ""),
                contact_no=request.POST.get("contact_no", ""),
                owner_name=request.POST.get("owner_name", ""),
                email=request.POST.get("email", ""),
                contact_person=request.POST.get("contact_person", ""),
                position=request.POST.get("position", ""),
                attachments_required=bool(request.POST.get("attachments_required")),
                default_segment=Segment.objects.get(pk=segment) if segment else None,
            )
            SupplierService.save_contacts(supplier, _supplier_contacts_from_post(request.POST))
            messages.success(request, "Supplier created.")
            return redirect("ui:supplier_list")
        except (IntegrityError, ValueError, ObjectDoesNotExist) as exc:
            messages.error(request, str(exc))
    return render(request, "ui/ap/supplier_form.html", {"segments": Segment.objects.order_by("code")})


@login_required
def supplier_update(request, pk):
    """Update an existing supplier (Accounting & Finance Head + admins only)."""
    require_can_edit_master(request.user)
    from apps.ap.models import Supplier
    from apps.ap.services import SupplierService

    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == "POST":
        try:
            supplier.code = request.POST.get("code") or supplier.code
            supplier.name = request.POST["name"].strip()
            supplier.supplier_type = request.POST["supplier_type"]
            supplier.tin = request.POST.get("tin", "")
            supplier.address = request.POST.get("address", "")
            supplier.contact_no = request.POST.get("contact_no", "")
            supplier.owner_name = request.POST.get("owner_name", "")
            supplier.email = request.POST.get("email", "")
            supplier.contact_person = request.POST.get("contact_person", "")
            supplier.position = request.POST.get("position", "")
            supplier.attachments_required = bool(request.POST.get("attachments_required"))
            segment = request.POST.get("default_segment")
            supplier.default_segment = Segment.objects.get(pk=segment) if segment else None
            supplier.save()
            SupplierService.save_contacts(supplier, _supplier_contacts_from_post(request.POST))
            messages.success(request, f"Supplier {supplier.code} updated.")
            return redirect("ui:supplier_list")
        except (IntegrityError, ValueError, ObjectDoesNotExist) as exc:
            messages.error(request, str(exc))
    return render(request, "ui/ap/supplier_form.html", {
        "supplier": supplier,
        "segments": Segment.objects.order_by("code"),
    })


def _supplier_contacts_from_post(post):
    """Parse repeated contact rows from the supplier form into row dicts."""
    names = post.getlist("contact_name")
    positions = post.getlist("contact_position")
    phones = post.getlist("contact_phone")
    rows = []
    for i, name in enumerate(names):
        name = (name or "").strip()
        if not name:
            continue
        rows.append({
            "name": name,
            "position": (positions[i] if i < len(positions) else "").strip(),
            "phone": (phones[i] if i < len(phones) else "").strip(),
        })
    return rows


@login_required
def rfp_create(request):
    from apps.ap.models import Supplier
    from apps.ap.services import RFPService
    from apps.sequences.models import DocumentSequence

    if request.method == "POST":
        try:
            payee = Supplier.objects.get(pk=request.POST["payee"])
            segment = Segment.objects.get(pk=request.POST["segment"])
            rfp_date = request.POST.get("rfp_date", "")
            if not rfp_date:
                raise ValidationError("Enter the date of request.")
            ap_number = DocumentSequence.next_number(
                company=payee.default_segment.company if payee.default_segment else segment.company,
                form_code="RFP",
                year=int(rfp_date[:4]),
            )
            lines = _rfp_lines_from_form(request)
            if not lines:
                raise ValueError("Add at least one charge line.")
            rfp = RFPService.create_rfp(
                ap_number=ap_number,
                rfp_date=date.fromisoformat(rfp_date),
                payee=payee,
                segment=segment,
                purpose=request.POST.get("purpose", ""),
                lines=lines,
                user=request.user,
            )
            messages.success(request, f"RFP {rfp.ap_number} created (prepared).")
            return redirect("ui:rfp_detail", pk=rfp.id)
        except AccountingError as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "ui/ap/rfp_form.html",
        {
            "segments": Segment.objects.order_by("code"),
            "accounts": Account.objects.filter(is_postable=True).order_by("code"),
        },
    )


@login_required
def rfp_detail(request, pk):
    from apps.ap.models import RFPDocument
    from apps.core.approvals import (
        approval_role_of,
        role_assignee,
        ROLE_LABELS,
        RFP_NEXT_ROLE,
    )

    rfp = get_object_or_404(
        RFPDocument.objects.prefetch_related("lines__account", "lines__segment"), pk=pk
    )
    cr_total = sum((l.amount for l in rfp.lines.all() if l.side == "cr"), Decimal("0.00"))

    awaiting = None
    from apps.ap.services import pending_final_check
    role = RFP_NEXT_ROLE.get(rfp.status)
    if pending_final_check(rfp):
        role = "coo"
    if role:
        awaiting = {
            "role": role,
            "label": ROLE_LABELS[role],
            "assignee": role_assignee(role),
            "you_hold": approval_role_of(request.user) == role,
        }
    return render(
        request,
        "ui/ap/rfp_detail.html",
        {
            "rfp": rfp,
            "timeline": rfp_timeline(rfp),
            "cr_total": cr_total,
            "awaiting": awaiting,
            "audit_trail": _audit_trail("rfp", rfp.id),
        },
    )


@login_required
def rfp_print(request, pk):
    """Print-optimized Request for Payment matching the RFP-TEMPLATES.xlsx
    layout (ACCTG-FOR-012): logo header, payee info, distribution charges and
    the Dr./Cr. chart with the three-column signature section."""
    from apps.ap.models import RFPDocument

    def _name(user):
        from apps.core.approvals import signatory_name

        return signatory_name(user)

    rfp = get_object_or_404(
        RFPDocument.objects.select_related(
            "payee", "segment", "created_by", "checked_by",
            "approved_by_acctg", "approved_by_fin",
        ),
        pk=pk,
    )
    lines = list(rfp.lines.select_related("account", "segment").order_by("line_no"))
    dr_lines = [line for line in lines if line.side == "dr"]
    cr_lines = [line for line in lines if line.side == "cr"]
    total = sum((line.amount for line in dr_lines), Decimal("0.00")) or rfp.amount
    return render(
        request,
        "ui/ap/rfp_print.html",
        {
            "rfp": rfp,
            "lines": lines,
            "dr_lines": dr_lines,
            "cr_lines": cr_lines,
            "total": total,
            "position": rfp.payee.position or "",
            "contact_no": rfp.payee.contact_no or "",
            "address": rfp.payee.address or f"{rfp.segment.name} ({rfp.segment.code})",
            "requested_by": _name(rfp.created_by),
            "checked_by": _name(rfp.checked_by),
            "approved_acctg": _name(rfp.approved_by_acctg),
            "approved_fin": _name(rfp.approved_by_fin),
        },
    )


@login_required
@require_POST
def rfp_submit(request, pk):
    from apps.ap.models import RFPDocument

    rfp = get_object_or_404(RFPDocument, pk=pk)
    try:
        if rfp.status != "prepared":
            raise ValueError("Only prepared RFPs can be submitted.")
        rfp.status = "submitted"
        rfp.save(update_fields=["status", "updated_at"])
        from apps.ap.services import log_action

        log_action(rfp, "submitted", actor=request.user)
        messages.success(request, f"RFP {rfp.ap_number} submitted.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("ui:rfp_detail", pk=pk)


@login_required
@require_POST
def rfp_approve(request, pk):
    from apps.ap.models import RFPDocument
    from apps.ap.services import RFPService
    from apps.core.approvals import approval_role_of, require_approval_role

    rfp = get_object_or_404(RFPDocument, pk=pk)
    is_hx = bool(request.headers.get("HX-Request"))
    try:
        require_approval_role(request.user, "head")
        rfp = RFPService.approve_head(rfp, user=request.user)
        msg = f"RFP {rfp.ap_number} approved."
        messages.success(request, msg)
    except (AccountingError, ValueError) as exc:
        msg = str(exc)
        messages.error(request, msg)
    if is_hx:
        rfp.approval_info = _rfp_approval_info(rfp, approval_role_of(request.user))
        response = render(request, "ui/ap/_rfp_row.html", {"rfp": rfp})
        response["HX-Trigger"] = json.dumps({"showToast": msg})
        return response
    return redirect("ui:rfp_detail", pk=pk)


@login_required
@require_POST
def rfp_finance_notes(request, pk):
    """Finance Head writes issuance notes for Ellen/COO (ADR-038 §10e).

    Revised RFPs cannot complete finance approval until these notes exist.
    """
    from apps.ap.models import RFPDocument
    from apps.core.approvals import require_approval_role

    rfp = get_object_or_404(RFPDocument, pk=pk)
    try:
        require_approval_role(request.user, "fin_approved")
        notes = request.POST.get("finance_notes", "").strip()
        if not notes:
            raise ValueError("Notes cannot be blank.")
        rfp.finance_notes = notes
        rfp.save(update_fields=["finance_notes", "updated_at"])
        messages.success(request, "Finance notes saved for issuance.")
    except (AccountingError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:rfp_detail", pk=pk)


@login_required
@require_POST
def rfp_approve_cnr(request, pk):
    from apps.ap.models import RFPDocument
    from apps.ap.services import RFPService
    from apps.core.approvals import require_approval_role

    rfp = get_object_or_404(RFPDocument, pk=pk)
    try:
        require_approval_role(request.user, "coo")
        rfp = RFPService.approve_cnr(rfp, user=request.user)
        messages.success(request, f"RFP {rfp.ap_number} approved by CNR.")
    except AccountingError as exc:
        messages.error(request, str(exc))
    return redirect("ui:rfp_detail", pk=pk)


@login_required
@require_POST
def rfp_reject(request, pk):
    """An approver returns the RFP to the preparer with a note (ADR-020
    reject/revise cycle). Role-gated to whoever holds the current step."""
    from apps.ap.models import RFPDocument
    from apps.ap.services import RFPService
    from apps.core.approvals import ROLE_LABELS, RFP_NEXT_ROLE, role_assignee, require_approval_role

    rfp = get_object_or_404(RFPDocument, pk=pk)
    from apps.ap.services import pending_final_check
    role = RFP_NEXT_ROLE.get(rfp.status)
    if pending_final_check(rfp):
        role = "coo"
    note = request.POST.get("note", "")
    try:
        # Rejection is valid on any in-flight step (submitted..fin_approved);
        # if there is no current role the service will reject the status.
        if role:
            require_approval_role(request.user, role)
        rfp = RFPService.reject(rfp, user=request.user, note=note)
        messages.success(request, f"RFP {rfp.ap_number} rejected and returned to {rfp.created_by}.")
    except (AccountingError, ValidationError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:rfp_detail", pk=pk)


@login_required
def rfp_revise(request, pk):
    """The preparer revises a rejected RFP and resubmits it. GET shows a
    prefilled edit form; POST runs RFPService.revise (preparer-only)."""
    from apps.ap.models import RFPDocument
    from apps.ap.services import RFPService

    rfp = get_object_or_404(
        RFPDocument.objects.select_related("payee").prefetch_related("lines"), pk=pk
    )
    if request.user.id != rfp.created_by_id:
        messages.error(request, "Only the preparer may revise this RFP.")
        return redirect("ui:rfp_detail", pk=pk)

    if request.method == "POST":
        try:
            lines = _rfp_lines_from_form(request)
            if not lines:
                raise ValidationError("Add at least one charge line.")
            rfp = RFPService.revise(
                rfp,
                user=request.user,
                lines=lines,
                purpose=request.POST.get("purpose", ""),
            )
            messages.success(request, f"RFP {rfp.ap_number} revised and resubmitted.")
            return redirect("ui:rfp_detail", pk=pk)
        except (AccountingError, ValidationError) as exc:
            messages.error(request, str(exc))

    return render(
        request,
        "ui/ap/rfp_form.html",
        {
            "editing": rfp,
            "segments": Segment.objects.order_by("code"),
            "accounts": Account.objects.filter(is_postable=True).order_by("code"),
        },
    )


# ---------------------------------------------------------------------------
# Cash — bank master + weekly cycle generation
# ---------------------------------------------------------------------------


@login_required
def bank_create(request):
    require_can_create_master(request.user)
    if request.method == "POST":
        try:
            from apps.cash.models import BankAccount
            from apps.foundation.models import Company

            BankAccount.objects.create(
                code=request.POST["code"].strip(),
                name=request.POST["name"].strip(),
                account_type=request.POST["account_type"],
                bank_name=request.POST.get("bank_name", ""),
                bank_code=request.POST.get("bank_code", ""),
                gl_account=Account.objects.get(pk=request.POST["gl_account"]),
                company=Company.objects.first(),
                adb_required=money(request.POST.get("adb_required") or 0),
            )
            messages.success(request, "Bank account created.")
            return redirect("ui:bank_list")
        except (IntegrityError, ValueError, ObjectDoesNotExist) as exc:
            messages.error(request, str(exc))
    return render(request, "ui/cash/bank_form.html", {})


@login_required
def bank_update(request, pk):
    """Update an existing bank account (Accounting & Finance Head + admins only)."""
    require_can_edit_master(request.user)
    from apps.cash.models import BankAccount

    bank = get_object_or_404(BankAccount.objects.select_related("gl_account"), pk=pk)
    if request.method == "POST":
        try:
            bank.code = request.POST["code"].strip()
            bank.name = request.POST["name"].strip()
            bank.account_type = request.POST["account_type"]
            bank.bank_name = request.POST.get("bank_name", "")
            bank.bank_code = request.POST.get("bank_code", "")
            bank.gl_account = Account.objects.get(pk=request.POST["gl_account"])
            bank.adb_required = money(request.POST.get("adb_required") or 0)
            bank.save()
            messages.success(request, f"Bank account {bank.code} updated.")
            return redirect("ui:bank_list")
        except (IntegrityError, ValueError, Account.DoesNotExist) as exc:
            messages.error(request, str(exc))
    return render(request, "ui/cash/bank_form.html", {"bank": bank})


@login_required
def cycle_generate(request):
    from apps.cash.services import CashCycleService

    if request.method == "POST":
        try:
            segment = Segment.objects.get(pk=request.POST["segment"])
            cycles = CashCycleService.generate_range(
                segment,
                start_date=date.fromisoformat(request.POST["start_date"]),
                end_date=date.fromisoformat(request.POST["end_date"]),
            )
            messages.success(request, f"Generated {len(cycles)} weekly cycle(s).")
            return redirect("ui:cycle_list")
        except AccountingError as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "ui/cash/cycle_form.html",
        {
            "segments": Segment.objects.order_by("code"),
            "today": date.today(),
        },
    )


# ---------------------------------------------------------------------------
# Fixed assets — acquisition (9.1), depreciation (9.2), disposal (9.3)
# ---------------------------------------------------------------------------


@login_required
def asset_create(request):
    from apps.assets.models import AssetCategory
    from apps.assets.services import AssetService
    from apps.sequences.models import DocumentSequence

    if request.method == "POST":
        try:
            company = Company.objects.first()
            segment = Segment.objects.get(pk=request.POST["segment"])
            category = AssetCategory.objects.get(pk=request.POST["category"])
            asset_no = DocumentSequence.next_number(
                company=company, form_code="FA", year=int(request.POST["acquisition_date"][:4]),
                pattern="FA-{YYYY}-{SEQ:04d}",
            )
            asset = AssetService.acquire(
                asset_no=asset_no,
                name=request.POST["name"].strip(),
                category=category,
                segment=segment,
                acquisition_date=date.fromisoformat(request.POST["acquisition_date"]),
                cost=request.POST["cost"],
                residual_value=request.POST.get("residual_value", "0.00"),
                funding_source=request.POST["funding_source"],
                financed_loan_reference=request.POST.get("financed_loan_reference", ""),
                acquisition_fees=request.POST.get("acquisition_fees", "0.00"),
                user=request.user,
            )
            messages.success(request, f"Asset {asset.asset_no} acquired and posted.")
            return redirect("ui:asset_detail", pk=asset.id)
        except AccountingError as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "ui/assets/asset_form.html",
        {
            "categories": AssetCategory.objects.filter(is_active=True).order_by("code"),
            "segments": Segment.objects.order_by("code"),
        },
    )


@login_required
def asset_detail(request, pk):
    from apps.assets.models import Asset

    asset = get_object_or_404(Asset.objects.select_related("category", "segment"), pk=pk)
    return render(request, "ui/assets/asset_detail.html", asset_context(asset))


@login_required
@require_POST
def asset_depreciate(request, pk):
    from apps.assets.models import Asset
    from apps.assets.services import DepreciationService

    asset = get_object_or_404(Asset, pk=pk)
    try:
        row = DepreciationService.post_month(
            asset, period_start=date.fromisoformat(request.POST["period_start"]), user=request.user
        )
        messages.success(request, f"Depreciation posted for {row.period_start.strftime('%b %Y')}.")
    except AccountingError as exc:
        messages.error(request, str(exc))
    return redirect("ui:asset_detail", pk=pk)


@login_required
@require_POST
def asset_depreciate_all(request):
    """Month-end batch (ADR-038): post one period's depreciation for every
    active asset from the month-end close screen (idempotent)."""
    from apps.assets.services import DepreciationService

    try:
        period_start = date.fromisoformat(request.POST.get("period_start") or "")
    except ValueError:
        period_start = date.today()
    summary = DepreciationService.post_all(period_start=period_start, user=request.user)
    messages.success(
        request,
        f"Depreciation for {summary['period_start'].strftime('%b %Y')}: "
        f"{len(summary['posted'])} posted, {len(summary['skipped'])} skipped/already posted.",
    )
    return redirect("ui:month_end_close")


@login_required
def asset_dispose(request, pk):
    from apps.assets.models import Asset
    from apps.assets.services import DisposalService

    asset = get_object_or_404(Asset, pk=pk)
    if request.method == "POST":
        try:
            cash_account = None
            if request.POST.get("cash_account"):
                cash_account = Account.objects.get(pk=request.POST["cash_account"])
            disposal = DisposalService.dispose(
                asset=asset,
                disposal_date=date.fromisoformat(request.POST["disposal_date"]),
                proceeds=request.POST.get("proceeds", "0.00"),
                reason=request.POST.get("reason", ""),
                cash_account=cash_account,
                user=request.user,
            )
            messages.success(request, f"Disposal {disposal.id} recorded for {asset.asset_no}.")
            return redirect("ui:asset_detail", pk=pk)
        except AccountingError as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "ui/assets/asset_dispose_form.html",
        {"asset": asset},
    )


@login_required
def asset_reverse(request, pk):
    """Overstated-asset reversal form/submit (ADR-038 §2.c): Dr funding |
    Cr asset for the overstated amount; prospective only."""
    from apps.assets.models import Asset
    from apps.assets.services import ReversalService

    asset = get_object_or_404(Asset, pk=pk)
    if request.method == "POST":
        try:
            funding_account = None
            if request.POST.get("funding_account"):
                funding_account = Account.objects.get(pk=request.POST["funding_account"])
            reversal = ReversalService.reverse(
                asset=asset,
                reversal_date=date.fromisoformat(request.POST["reversal_date"]),
                amount=request.POST.get("amount", "0.00"),
                reason=request.POST.get("reason", ""),
                funding_account=funding_account,
                user=request.user,
            )
            messages.success(
                request,
                f"Overstatement of {reversal.amount} reversed for {asset.asset_no} "
                f"(prospective from {reversal.reversal_date}).",
            )
            return redirect("ui:asset_detail", pk=pk)
        except (AccountingError, ValueError) as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "ui/assets/asset_reverse_form.html",
        {"asset": asset},
    )


# ---------------------------------------------------------------------------
# AP — check voucher (ACCTG-FOR-010)
# ---------------------------------------------------------------------------


@login_required
def cv_list(request):
    return render(request, "ui/ap/cv_list.html", {"page_obj": _page(request, list_cv(limit=None))})


@login_required
def cv_create(request):
    from apps.ap.models import RFPDocument
    from apps.ap.services import CVPaymentService

    if request.method == "POST":
        try:
            rfp = RFPDocument.objects.get(pk=request.POST["rfp"])
            bank_account = Account.objects.get(pk=request.POST["bank_account"])
            cv_number = DocumentSequence.next_number(
                company=rfp.segment.company,
                form_code="CV",
                year=int(request.POST["cv_date"][:4]),
                pattern="CV-{YYYY}-{SEQ:04d}",
            )
            cv = CVPaymentService.create_cv(
                cv_number=cv_number,
                cv_date=date.fromisoformat(request.POST["cv_date"]),
                payee=rfp.payee,
                bank_account=bank_account,
                gross_amount=request.POST["gross_amount"],
                withheld_tax=request.POST.get("withheld_tax", "0.00"),
                rfp=rfp,
                check_no=request.POST.get("check_no", ""),
                user=request.user,
            )
            messages.success(request, f"Check voucher {cv.cv_number} issued.")
            return redirect("ui:cv_detail", pk=cv.id)
        except (AccountingError, ValueError, KeyError) as exc:
            messages.error(request, str(exc))
    selected_rfp = None
    rfp_id = request.GET.get("rfp")
    if rfp_id:
        from django.db.models import Prefetch
        from apps.ap.models import RFPLine

        try:
            rfp_qs = RFPDocument.objects.filter(pk=rfp_id).select_related("payee", "segment")
            selected_rfp = rfp_qs.prefetch_related(
                Prefetch(
                    "lines",
                    queryset=RFPLine.objects.select_related("account", "segment"),
                )
            ).get()
        except (ValueError, RFPDocument.DoesNotExist):
            messages.error(request, "Selected RFP not found.")
    return render(
        request,
        "ui/ap/cv_form.html",
        {
            "rfps": approved_rfps(),
            "today": date.today(),
            "selected_rfp": selected_rfp,
        },
    )


@login_required
def cv_detail(request, pk):
    from apps.ap.models import CheckVoucher

    def _name(user):
        from apps.core.approvals import signatory_name

        return signatory_name(user)

    cv = get_object_or_404(
        CheckVoucher.objects.select_related("payee", "bank_account", "rfp"),
        pk=pk,
    )
    if cv.rfp_id:
        list(cv.rfp.lines.select_related("account", "segment"))
    rfp = cv.rfp
    # Same 5 signatory cells as the print layout (ACCTG-FOR-010): prepared by
    # is whoever issued the CV, requested by is the RFP creator, checked by is
    # the RFP checker, approved by is the COO role holder, and the payee signs
    # as receiver.
    signatories = {
        "prepared": _name(cv.created_by),
        "requested": _name(rfp.created_by) if rfp else "",
        "checked": _name(rfp.checked_by) if rfp else _name(cv.approved_by),
        "approved": _coo_name(),
        "received": cv.payee.name if cv.payee else "",
    }
    return render(request, "ui/ap/cv_detail.html", {
        "cv": cv,
        "signatories": signatories,
        "audit_trail": _audit_trail("cv", cv.id),
    })


@login_required
def cv_print(request, pk):
    """Print-optimized Check Voucher (ACCTG-FOR-010) matching the
    VOUCHER-FORMS-CASH-AND-CHECK-10.xlsx signatory layout."""
    from apps.ap.models import CheckVoucher

    def _name(user):
        from apps.core.approvals import signatory_name

        return signatory_name(user)

    cv = get_object_or_404(
        CheckVoucher.objects.select_related("payee", "bank_account", "approved_by", "rfp"),
        pk=pk,
    )
    rfp = cv.rfp
    lines = list(rfp.lines.select_related("account", "segment")) if rfp else []
    dr_lines = [line for line in lines if line.side == "dr"]
    total = sum((line.amount for line in dr_lines), Decimal("0.00"))
    position = cv.payee.position or cv.payee.get_supplier_type_display()
    date_of_request = (rfp.rfp_date if rfp and rfp.rfp_date else cv.cv_date) if rfp else cv.cv_date
    signatories = {
        "prepared": _name(cv.created_by),
        "requested": _name(rfp.created_by) if rfp else "",
        "checked": _name(rfp.checked_by) if rfp else _name(cv.approved_by),
        "approved": _coo_name(),
        "received": cv.payee.name if cv.payee else "",
    }
    return render(
        request,
        "ui/ap/cv_print.html",
        {
            "cv": cv,
            "rfp": rfp,
            "lines": lines,
            "dr_lines": dr_lines,
            "total": total,
            "position": position,
            "signatories": signatories,
            "date_of_request": date_of_request,
        },
    )


@login_required
@require_POST
def cv_approve(request, pk):
    """created -> approved (Accounting & Finance Head signs off the check).
    The head's approval clears the way for clear (which books the JE)."""
    from apps.ap.models import CheckVoucher
    from apps.ap.services import CVPaymentService
    from apps.core.approvals import require_approval_role

    cv = get_object_or_404(
        CheckVoucher.objects.select_related("payee", "bank_account", "rfp"), pk=pk
    )
    is_htmx = request.headers.get("HX-Request")
    try:
        require_approval_role(request.user, "head")
        cv = CVPaymentService.approve(cv, user=request.user)
        msg = f"CV {cv.cv_number} approved."
        messages.success(request, msg)
    except AccountingError as exc:
        msg = str(exc)
        messages.error(request, msg)
    if is_htmx:
        response = render(request, "ui/ap/_cv_row.html", {"cv": cv})
        response["HX-Trigger"] = json.dumps({"showToast": msg})
        return response
    return redirect("ui:cv_detail", pk=pk)


@login_required
@require_POST
def cv_clear(request, pk):
    """approved -> cleared (Accounting & Finance Head books the encashment).

    The CV's journal entry is posted to the GL here — the head's clear is the
    approval gate that moves the DRAFT entry into the books (ADR-033)."""
    from apps.ap.models import CheckVoucher
    from apps.ap.services import CVPaymentService
    from apps.core.approvals import require_approval_role

    cv = get_object_or_404(CheckVoucher, pk=pk)
    try:
        require_approval_role(request.user, "head")
        cv = CVPaymentService.clear(cv, user=request.user)
        messages.success(request, f"CV {cv.cv_number} cleared — entry in GL.")
    except AccountingError as exc:
        messages.error(request, str(exc))
    return redirect("ui:cv_detail", pk=pk)


@login_required
@require_POST
def cv_reject(request, pk):
    """The current actor returns the CV to its issuer with a note (reject/
    revise cycle mirroring the RFP path). Role-gated to whoever holds the
    current action — the Accounting & Finance Head at 'created' and
    'approved'."""
    from apps.ap.models import CheckVoucher
    from apps.ap.services import CVPaymentService
    from apps.core.approvals import require_approval_role

    cv = get_object_or_404(CheckVoucher, pk=pk)
    role = "head" if cv.status in ("created", "approved") else None
    note = request.POST.get("note", "")
    try:
        if role:
            require_approval_role(request.user, role)
        cv = CVPaymentService.reject(cv, user=request.user, note=note)
        messages.success(request, f"CV {cv.cv_number} rejected and returned to {cv.created_by}.")
    except AccountingError as exc:
        messages.error(request, str(exc))
    return redirect("ui:cv_detail", pk=pk)


@login_required
def cv_revise(request, pk):
    """The issuer corrects a rejected CV and resubmits it. GET shows a
    prefilled correction form; POST runs CVPaymentService.revise (issuer-only)."""
    from apps.ap.models import CheckVoucher
    from apps.ap.services import CVPaymentService

    cv = get_object_or_404(
        CheckVoucher.objects.select_related("payee", "rfp", "bank_account"), pk=pk
    )
    if request.user.id != cv.created_by_id:
        messages.error(request, "Only the issuer may revise this CV.")
        return redirect("ui:cv_detail", pk=pk)

    if request.method == "POST":
        try:
            cv = CVPaymentService.revise(
                cv,
                user=request.user,
                bank_account=Account.objects.get(pk=request.POST["bank_account"]),
                gross_amount=request.POST["gross_amount"],
                withheld_tax=request.POST.get("withheld_tax", "0.00"),
                check_no=request.POST.get("check_no", ""),
                cv_date=date.fromisoformat(request.POST["cv_date"]),
            )
            messages.success(request, f"CV {cv.cv_number} revised and resubmitted.")
            return redirect("ui:cv_detail", pk=pk)
        except (AccountingError, ValidationError, ValueError, KeyError) as exc:
            messages.error(request, str(exc))

    return render(
        request,
        "ui/ap/cv_revise_form.html",
        {
            "cv": cv,
            "rfps": approved_rfps(),
            "today": date.today(),
        },
    )


# ---------------------------------------------------------------------------
# Cash — petty cash vouchers (ACCTG-FOR-002) / PCF replenishment
# ---------------------------------------------------------------------------


@login_required
def pcf_list(request):
    return render(request, "ui/cash/pcf_list.html", {"page_obj": _page(request, list_pcf_funds())})


@login_required
def pcf_replenish(request):
    from apps.cash.models import PettyCashFund
    from apps.cash.services import PCFService

    if request.method == "POST":
        try:
            fund = PettyCashFund.objects.get(pk=request.POST["fund"])
            expenses = []
            accounts = request.POST.getlist("exp_account")
            segments = request.POST.getlist("exp_segment")
            debits = request.POST.getlist("exp_debit")
            credits = request.POST.getlist("exp_credit")
            descs = request.POST.getlist("exp_description")
            cost_centers = request.POST.getlist("exp_cost_center")
            for i, acc_id in enumerate(accounts):
                if not acc_id:
                    continue
                debit = money((debits[i] if i < len(debits) else 0) or 0)
                credit = money((credits[i] if i < len(credits) else 0) or 0)
                if not debit and not credit:
                    continue
                if debit and credit:
                    raise ValidationError(
                        f"Line {i + 1}: enter the amount in only one of Debit or Credit."
                    )
                expenses.append(
                    {
                        "account_code": Account.objects.get(code=acc_id).code,
                        "side": "dr" if debit else "cr",
                        "amount": str(debit or credit),
                        "description": (descs[i] if i < len(descs) else "")[:500],
                        "segment": segments[i] if i < len(segments) else "",
                        "cost_center": cost_centers[i] if i < len(cost_centers) else "",
                    }
                )
            if not expenses:
                raise ValueError("Add at least one expense line.")
            replen = PCFService.request_replenishment(
                fund,
                expenses,
                user=request.user,
            )
            replen.payee_name = request.POST.get("payee_name", "")
            replen.reference = request.POST.get("reference", "")
            replen.customer_name = request.POST.get("customer_name", "")
            if request.POST.get("request_date"):
                replen.request_date = date.fromisoformat(request.POST["request_date"])
            replen.save(update_fields=["payee_name", "reference", "customer_name", "request_date", "updated_at"])
            messages.success(request, f"PCF replenishment {replen.id} requested (₱{replen.amount}).")
            return redirect("ui:pcf_replenishment_list")
        except (AccountingError, ValueError, KeyError) as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "ui/cash/pcf_replenish_form.html",
        {
            "funds": list_pcf_funds(),
            "segments": Segment.objects.order_by("code"),
            "accounts": Account.objects.filter(is_postable=True).order_by("code"),
            "cost_centers": CostCenter.objects.filter(is_active=True).order_by("code"),
            "today": date.today(),
        },
    )


@login_required
def pcf_replenishment_list(request):
    return render(request, "ui/cash/pcf_replenishment_list.html", {"page_obj": _page(request, list_pcf_replenishments(limit=None))})


@login_required
def pcf_replenishment_detail(request, pk):
    from apps.cash.models import PCFReplenishment

    replen = get_object_or_404(
        PCFReplenishment.objects.select_related("fund__custodian", "fund__company", "conso"),
        pk=pk,
    )
    return render(request, "ui/cash/pcf_replenishment_detail.html", {"replen": replen})


@login_required
def pcf_replenishment_print(request, pk):
    """Print-optimized Petty Cash Replenishment report (landscape) matching the
    PETTY CASH REPLENISHMENT.xlsx columns. Columns the app does not capture
    yet (Type, DATE, Vendor/Customer, REF., TIN, Address, VAT, AP NO) print blank."""
    from apps.cash.models import PCFReplenishment
    from apps.foundation.models import Account

    replen = get_object_or_404(
        PCFReplenishment.objects.select_related("fund__custodian", "fund__company", "requested_by"),
        pk=pk,
    )
    rows = []
    for exp in replen.expenses or []:
        acct = Account.objects.filter(code=exp.get("account_code", "")).first()
        rows.append(
            {
                "coa": exp.get("account_code", ""),
                "title": acct.name if acct else exp.get("account_code", ""),
                "dr": exp.get("amount", 0),
                "cr": exp.get("amount", 0),
                "side": str(exp.get("side", "dr")).lower(),
                "segment": exp.get("segment", ""),
                "cost_center": exp.get("cost_center", ""),
                "remarks": exp.get("description", ""),
                "classification": acct.classification if acct else "",
                "category": acct.category if acct else "",
                "sub_accounts": acct.sub_accounts if acct else "",
                "major_accounts": acct.major_accounts if acct else "",
                "behavior": acct.behavior if acct else "",
                "traceability": acct.traceability if acct else "",
                "controllability": acct.controllability if acct else "",
            }
        )
    total = sum((Decimal(str(row["dr"])) for row in rows), Decimal("0.00"))
    fund = replen.fund
    custodian = fund.custodian
    return render(
        request,
        "ui/cash/pcf_replenishment_print.html",
        {
            "replen": replen,
            "rows": rows,
            "total": total,
            "fund_label": fund.name or fund.fund_code,
            "custodian_label": custodian.get_full_name() or custodian.username if custodian else "—",
        },
    )


@login_required
@require_POST
def pcf_replenishment_post(request, pk):
    from apps.cash.models import PCFReplenishment
    from apps.cash.services import PCFService

    replen = get_object_or_404(PCFReplenishment, pk=pk)
    try:
        PCFService.post_replenishment(replen, user=request.user)
        messages.success(request, f"Replenishment {replen.id} posted to GL.")
    except (AccountingError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:pcf_replenishment_detail", pk=pk)


@login_required
@require_POST
def pcf_replenishment_approve(request, pk):
    """Approve a PCF replenishment; this auto-creates its CONSO batch entry
    (ADR-038 §7c). The JE posts when the CONSO batch is posted."""
    from apps.cash.models import PCFReplenishment
    from apps.cash.services import PCFService

    replen = get_object_or_404(PCFReplenishment, pk=pk)
    try:
        PCFService.approve_replenishment(replen, user=request.user)
        messages.success(request, f"Replenishment {replen.id} approved and batched to {replen.conso.batch_no}.")
    except (AccountingError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:pcf_replenishment_detail", pk=pk)


@login_required
def pcf_create(request):
    from apps.cash.models import PettyCashFund

    if request.method == "POST":
        try:
            from apps.foundation.models import Company

            custodian = None
            if request.POST.get("custodian"):
                custodian = get_user_model().objects.get(pk=request.POST["custodian"])
            PettyCashFund.objects.create(
                fund_code=request.POST["fund_code"].strip(),
                name=request.POST["name"].strip(),
                custodian_name=request.POST.get("custodian_name", "").strip(),
                custodian=custodian,
                imprest_amount=money(request.POST.get("imprest_amount") or 0),
                gl_account=Account.objects.get(pk=request.POST["gl_account"]),
                company=Company.objects.first(),
            )
            messages.success(request, "Petty cash fund created.")
            return redirect("ui:pcf_list")
        except (IntegrityError, ValueError, ObjectDoesNotExist) as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "ui/cash/pcf_form.html",
        {"custodians": get_user_model().objects.order_by("username")},
    )


@login_required
def pcf_update(request, pk):
    """Edit an existing petty cash fund: imprest amount, custodian (re-assign
    or remove), name, GL account, replenish trigger, and active state."""
    from apps.cash.models import PettyCashFund

    fund = get_object_or_404(PettyCashFund.objects.select_related("gl_account"), pk=pk)
    if request.method == "POST":
        try:
            custodian = None
            if request.POST.get("custodian"):
                custodian = get_user_model().objects.get(pk=request.POST["custodian"])
            fund.name = request.POST["name"].strip()
            fund.custodian_name = request.POST.get("custodian_name", "").strip()
            fund.custodian = custodian
            fund.imprest_amount = money(request.POST.get("imprest_amount") or 0)
            fund.gl_account = Account.objects.get(pk=request.POST["gl_account"])
            fund.replenish_trigger_pct = money(request.POST["replenish_trigger_pct"] or 0) / 100
            fund.is_active = request.POST.get("is_active") == "1"
            fund.save()
            messages.success(request, f"Petty cash fund {fund.fund_code} updated.")
            return redirect("ui:pcf_list")
        except (ValueError, ObjectDoesNotExist) as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "ui/cash/pcf_form.html",
        {
            "editing": fund,
            "editing_trigger_pct": int(round(fund.replenish_trigger_pct * 100)),
            "custodians": get_user_model().objects.order_by("username"),
        },
    )


# ---------------------------------------------------------------------------
# AP — CONSO batch (7.3: RFP -> batch -> post atomically)
# ---------------------------------------------------------------------------


@login_required
def conso_list(request):
    return render(request, "ui/ap/conso_list.html", {"page_obj": _page(request, list_conso(limit=None))})


@login_required
def conso_create(request):
    from apps.ap.models import CONSOBatch

    if request.method == "POST":
        try:
            company = Company.objects.first()
            conso_date = date.fromisoformat(request.POST["conso_date"])
            batch = CONSOBatch.objects.create(
                batch_no=DocumentSequence.next_number(
                    company=company, form_code="CONSO", year=conso_date.year,
                    pattern="CONSO-{YYYY}-{SEQ:02d}",
                ),
                conso_date=conso_date,
            )
            messages.success(request, f"CONSO batch {batch.batch_no} opened.")
            return redirect("ui:conso_detail", pk=batch.id)
        except (ValueError, KeyError) as exc:
            messages.error(request, str(exc))
    return render(request, "ui/ap/conso_form.html", {"today": date.today()})


@login_required
def conso_detail(request, pk):
    from apps.ap.models import CONSOBatch

    batch = get_object_or_404(CONSOBatch, pk=pk)
    ctx = conso_context(batch)
    ctx["available"] = unassigned_approved_rfps()
    return render(request, "ui/ap/conso_detail.html", ctx)


@login_required
@require_POST
def conso_add_rfp(request, pk):
    from apps.ap.models import CONSOBatch, RFPDocument

    batch = get_object_or_404(CONSOBatch, pk=pk)
    try:
        rfp = RFPDocument.objects.get(pk=request.POST["rfp"])
        if rfp.status not in ("fin_approved", "cnr_approved"):
            raise ValueError("Only finance-approved RFPs can be batched.")
        if rfp.conso_id:
            raise ValueError(f"RFP {rfp.ap_number} is already in batch {rfp.conso_id}.")
        rfp.conso = batch
        rfp.save(update_fields=["conso", "updated_at"])
        members = list(batch.rfps.all())
        batch.total_amount = sum(m.amount for m in members)
        batch.save(update_fields=["total_amount", "updated_at"])
        messages.success(request, f"RFP {rfp.ap_number} added to {batch.batch_no}.")
    except (ObjectDoesNotExist, ValueError, AccountingError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:conso_detail", pk=pk)


@login_required
@require_POST
def conso_post(request, pk):
    from apps.ap.models import CONSOBatch
    from apps.ap.services import CONSOService

    batch = get_object_or_404(CONSOBatch, pk=pk)
    try:
        CONSOService.post_batch(batch, user=request.user)
        messages.success(request, f"CONSO {batch.batch_no} posted — all RFPs in GL.")
    except (AccountingError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:conso_detail", pk=pk)


# ---------------------------------------------------------------------------
# Cash — bank reconciliation (ADR-026) + cash short (ADR-029/030)
# ---------------------------------------------------------------------------


@login_required
def recon_list(request):
    return render(request, "ui/cash/recon_list.html", {"page_obj": _page(request, list_recons(limit=None))})


@login_required
def recon_create(request):
    from apps.cash.models import BankAccount, WeeklyCashCycle
    from apps.cash.services import BankReconService

    if request.method == "POST":
        try:
            cycle = WeeklyCashCycle.objects.get(pk=request.POST["cycle"])
            bank = BankAccount.objects.get(pk=request.POST["bank_account"])
            recon = BankReconService.reconcile(
                cycle=cycle,
                bank_account=bank,
                bank_statement_balance=request.POST["bank_statement_balance"],
                user=request.user,
            )
            messages.success(
                request,
                f"Recon {cycle} / {bank.code}: diff ₱{recon.difference} ({recon.status}).",
            )
            return redirect("ui:recon_list")
        except (ObjectDoesNotExist, ValueError, AccountingError) as exc:
            messages.error(request, str(exc))
    selected_cycle = None
    if request.GET.get("cycle"):
        selected_cycle = WeeklyCashCycle.objects.filter(pk=request.GET["cycle"]).first()
    return render(
        request,
        "ui/cash/recon_form.html",
        {
            "cycles": WeeklyCashCycle.objects.select_related("segment").order_by("-cycle_start"),
            "banks": list_banks(),
            "selected_cycle": selected_cycle,
        },
    )


@login_required
def cash_short_list(request):
    return render(request, "ui/cash/cash_short_list.html", {"page_obj": _page(request, list_cash_shorts(limit=None))})


@login_required
def cash_short_record(request):
    from apps.cash.models import WeeklyCashCycle
    from apps.cash.services import CashShortService

    if request.method == "POST":
        try:
            cycle = WeeklyCashCycle.objects.get(pk=request.POST["cycle"])
            ws = CashShortService.record_variance(
                cycle=cycle,
                segment=cycle.segment,
                expected_cash=request.POST["expected_cash"],
                actual_cash=request.POST["actual_cash"],
                cause=request.POST.get("cause", ""),
                cause_category=request.POST.get("cause_category", ""),
                user=request.user,
            )
            messages.success(request, f"Variance ₱{ws.variance} recorded (open).")
            return redirect("ui:cash_short_list")
        except (ObjectDoesNotExist, ValueError, AccountingError) as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "ui/cash/cash_short_form.html",
        {"cycles": WeeklyCashCycle.objects.select_related("segment").order_by("-cycle_start")},
    )


@login_required
@require_POST
def cash_short_approve(request, pk):
    from apps.cash.models import CashShortExcessWorksheet
    from apps.cash.services import CashShortService

    ws = get_object_or_404(CashShortExcessWorksheet, pk=pk)
    is_htmx = request.headers.get("HX-Request")
    try:
        from apps.core.approvals import require_approval_role

        require_approval_role(request.user, "head")
        CashShortService.approve(ws, request.user)
        msg = "Variance approved."
        messages.success(request, msg)
    except AccountingError as exc:
        msg = str(exc)
        messages.error(request, msg)
    if is_htmx:
        response = render(request, "ui/cash/_cash_short_row.html", {"ws": ws})
        response["HX-Trigger"] = json.dumps({"showToast": msg})
        return response
    return redirect("ui:cash_short_list")


@login_required
def collections_summary(request):
    """Daily Collections Journal Entries Summary (cashier worksheet per cycle)."""
    from apps.cash.models import WeeklyCashCycle

    cycles = list(list_cycles())
    cycle = None
    if request.GET.get("cycle"):
        cycle = WeeklyCashCycle.objects.filter(pk=request.GET["cycle"]).first()
    if cycle is None and cycles:
        cycle = cycles[0]
    context = {"cycles": cycles}
    if cycle:
        context.update(daily_collections(cycle))
    return render(request, "ui/cash/collections_summary.html", context)


# ---------------------------------------------------------------------------
# General Journal register
# ---------------------------------------------------------------------------


@login_required
def general_journal(request):
    """Register of posted entries (workbook PAYMENT RECEIPTS / UPON DELIVERY
    layout): Date | Cycle | Ref | Party | PO | Description | CoA | Debit | Credit."""
    from .services import general_journal as gj

    ctx = gj(
        start=request.GET.get("start") or None,
        end=request.GET.get("end") or None,
        segment=request.GET.get("segment") or None,
    )
    ctx["page_obj"] = _page(request, ctx.pop("rows"))
    ctx["start"] = request.GET.get("start", "")
    ctx["end"] = request.GET.get("end", "")
    ctx["segment_sel"] = request.GET.get("segment", "")
    return render(request, "ui/reporting/general_journal.html", ctx)


# ---------------------------------------------------------------------------
# Foundation — Chart of Accounts (read-only)
# ---------------------------------------------------------------------------


@login_required
def account_options(request):
    """Type-ahead source for searchable account pickers (server-side).

    Returns the first ~30 postable accounts matching the query by code or
    name, plus the currently-selected account (when editing) so the picker
    can keep a stable selection.     ``?scope=`` narrows the pool so every
    GL picker shares one endpoint: ``all`` (default, every postable
    account), ``cash`` (postable assets — receipts, asset funding/cash),
    ``bank`` (postable accounts linked to an active bank — check vouchers),
    ``pcf`` (postable 100xx assets — petty-cash fund GL).
    ``selected=`` accepts an account code or id. Used by all async
    ``data-search-url`` pickers (JE/RFP/PCF/CV/AR/asset/bank forms).
    """
    q = request.GET.get("q", "").strip()
    selected = request.GET.get("selected", "").strip()
    scope = request.GET.get("scope", "all").strip()
    qs = Account.objects.filter(is_postable=True).order_by("code")
    if scope == "cash":
        qs = qs.filter(account_type="asset")
    elif scope == "bank":
        qs = qs.filter(bank_account__isnull=False, bank_account__is_active=True)
    elif scope == "pcf":
        qs = qs.filter(account_type="asset", code__startswith="100")
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
    rows = list(qs[:30])
    if selected and selected not in {a.code for a in rows}:
        lookup = Q(code=selected)
        if selected.isdigit():
            lookup |= Q(pk=selected)
        keep = Account.objects.filter(lookup, is_postable=True).first()
        if keep:
            rows.insert(0, keep)
    return JsonResponse(
        [
            {"id": a.id, "code": a.code, "text": f"{a.code} — {a.name}"}
            for a in rows
        ],
        safe=False,
    )


@login_required
def supplier_options(request):
    """Type-ahead source for searchable supplier/payee pickers (server-side).

    Returns the first ~30 active suppliers matching the query by code or name,
    plus the currently-selected supplier (when editing) so the picker keeps a
    stable selection. ``?selected=`` accepts a supplier code or id.
    """
    from apps.ap.models import Supplier

    q = request.GET.get("q", "").strip()
    selected = request.GET.get("selected", "").strip()
    qs = Supplier.objects.order_by("code")
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
    rows = list(qs[:30])
    if selected and selected not in {s.code for s in rows}:
        lookup = Q(code=selected)
        if selected.isdigit():
            lookup |= Q(pk=selected)
        keep = Supplier.objects.filter(lookup).first()
        if keep:
            rows.insert(0, keep)
    return JsonResponse(
        [
            {"id": a.id, "code": a.code, "text": f"{a.code} — {a.name}"}
            for a in rows
        ],
        safe=False,
    )


@login_required
def coa_list(request):
    """Chart of Accounts — read-only listing with search + filters."""
    from .services import coa_rows

    ctx = {
        "page_obj": _page(
            request,
            coa_rows(
                q=request.GET.get("q", "").strip(),
                segment=request.GET.get("segment", "").strip(),
                account_type=request.GET.get("account_type", "").strip(),
            ),
            per_page=50,
        ),
        "q": request.GET.get("q", "").strip(),
        "segment_sel": request.GET.get("segment", "").strip(),
        "account_type_sel": request.GET.get("account_type", "").strip(),
        "segments": Segment.objects.order_by("code"),
        "types": AccountType.choices,
    }
    template = (
        "ui/foundation/_coa_rows.html"
        if request.headers.get("HX-Request")
        else "ui/foundation/coa_list.html"
    )
    return render(request, template, ctx)


@login_required
def coa_print(request):
    """Print-optimized Chart of Accounts report (browser print dialog)."""
    from .services import coa_rows

    rows = coa_rows(
        q=request.GET.get("q", "").strip(),
        segment=request.GET.get("segment", "").strip(),
        account_type=request.GET.get("account_type", "").strip(),
    )
    groups = []
    for value, label in AccountType.choices:
        accounts = [a for a in rows if a.account_type == value]
        if accounts:
            groups.append((label, accounts))
    return render(
        request,
        "ui/foundation/coa_print.html",
        {
            "groups": groups,
            "total": len(rows),
            "segment_sel": request.GET.get("segment", "").strip(),
            "account_type_sel": request.GET.get("account_type", "").strip(),
            "q": request.GET.get("q", "").strip(),
        },
    )


@login_required
def coa_create(request):
    """Create a new COA account (staff add-only; head + admins)."""
    require_can_create_master(request.user)
    from apps.foundation.models import NORMAL_BALANCE, Account

    if request.method == "POST":
        try:
            code = request.POST["code"].strip()
            name = request.POST["name"].strip()
            account_type = AccountType(request.POST.get("account_type", "asset"))
            segment_code = request.POST.get("segment", "").strip()
            Account.objects.create(
                code=code,
                name=name,
                account_type=account_type,
                segment=segment_code,
                normal_balance=NORMAL_BALANCE.get(account_type, "debit"),
                classification=request.POST.get("classification", "").strip(),
                category=request.POST.get("category", "").strip(),
                sub_accounts=request.POST.get("sub_accounts", "").strip(),
                major_accounts=request.POST.get("major_accounts", "").strip(),
                behavior=request.POST.get("behavior", "").strip(),
                traceability=request.POST.get("traceability", "").strip(),
                controllability=request.POST.get("controllability", "").strip(),
            )
            messages.success(request, f"COA account {code} created.")
            return redirect("ui:coa_list")
        except (IntegrityError, ValueError, KeyError) as exc:
            messages.error(request, str(exc))
    return render(request, "ui/foundation/coa_form.html", {
        "types": AccountType.choices,
        "segments": Segment.objects.order_by("code"),
        "editing": False,
    })


@login_required
def coa_update(request, pk):
    """Update an existing COA account (Accounting & Finance Head + admins only)."""
    require_can_edit_master(request.user)
    from apps.foundation.models import NORMAL_BALANCE, Account

    account = get_object_or_404(Account, pk=pk)
    if request.method == "POST":
        try:
            account.name = request.POST.get("name", "").strip()
            account_type = AccountType(request.POST.get("account_type", account.account_type))
            account.account_type = account_type
            segment_code = request.POST.get("segment", "").strip()
            if segment_code:
                account.segment = segment_code
            account.normal_balance = NORMAL_BALANCE.get(account_type, "debit")
            account.classification = request.POST.get("classification", "").strip()
            account.category = request.POST.get("category", "").strip()
            account.sub_accounts = request.POST.get("sub_accounts", "").strip()
            account.major_accounts = request.POST.get("major_accounts", "").strip()
            account.behavior = request.POST.get("behavior", "").strip()
            account.traceability = request.POST.get("traceability", "").strip()
            account.controllability = request.POST.get("controllability", "").strip()
            account.save()
            messages.success(request, f"COA account {account.code} updated.")
            return redirect("ui:coa_list")
        except (IntegrityError, ValueError, Account.DoesNotExist) as exc:
            messages.error(request, str(exc))
    return render(request, "ui/foundation/coa_form.html", {
        "account": account,
        "types": AccountType.choices,
        "segments": Segment.objects.order_by("code"),
        "editing": True,
    })


# ---------------------------------------------------------------------------
# Cash flow statement
# ---------------------------------------------------------------------------


@login_required
def cash_flow(request):
    """Cash Flow Statement (ADR-031) — monthly cadence by default; a custom
    period_start/period_end still works (legacy GET form / API e2e uses it)."""
    from apps.cash.models import CashFlowStatement, WeeklyCashCycle
    from apps.cash.services import CashFlowService
    from apps.foundation.models import Company

    fmt = request.GET.get("format", "xlsx")
    company = Company.objects.first()
    latest = CashFlowStatement.objects.order_by("-period_end").first()
    year = int(request.GET.get("year") or date.today().year)
    month = int(request.GET.get("month") or date.today().month)

    if fmt == "csv" and latest:
        # CSV export of the cash flow snapshot
        import csv
        from io import StringIO
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Period Start", latest.period_start.isoformat()])
        writer.writerow(["Period End", latest.period_end.isoformat()])
        writer.writerow(["Collections", latest.collections])
        writer.writerow(["Payments to Depot", latest.payments_to_depot])
        writer.writerow(["Net Operating", nets["operating"] if (nets := {"operating": latest.collections - latest.payments_to_depot}) else "0.00"])
        writer.writerow(["Investing (CAPEX)", latest.asset_acquisitions])
        writer.writerow(["Financing (Net)", latest.loan_proceeds - latest.loan_repayments])
        writer.writerow(["Net Change in Cash", latest.net_change])
        writer.writerow(["Beginning Cash", latest.beginning_cash])
        writer.writerow(["Ending Cash (less ADB)", latest.ending_cash])
        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="CASH_FLOW.csv"'
        return response

    if fmt == "pdf" and latest:
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
        from reportlab.lib import colors

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=LETTER, leftMargin=0.6*inch, rightMargin=0.6*inch, topMargin=0.6*inch, bottomMargin=0.6*inch)
        elements = []
        data = [
            ["Period Start", latest.period_start.isoformat()],
            ["Period End", latest.period_end.isoformat()],
            ["Collections", latest.collections],
            ["Payments to Depot", latest.payments_to_depot],
            ["Net Operating", nets["operating"] if (nets := {"operating": latest.collections - latest.payments_to_depot}) else "0.00"],
            ["Investing (CAPEX)", latest.asset_acquisitions],
            ["Financing (Net)", latest.loan_proceeds - latest.loan_repayments],
            ["Net Change in Cash", latest.net_change],
            ["Beginning Cash", latest.beginning_cash],
            ["Ending Cash (less ADB)", latest.ending_cash],
        ]
        table = Table(data, colWidths=[2.5*inch, 2.5*inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f0f0")]),
        ]))
        elements.append(table)
        doc.build(elements)

        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="CASH_FLOW.pdf"'
        return response

    if company:
        try:
            if request.GET.get("period_start"):
                latest = CashFlowService.generate(
                    period_start=date.fromisoformat(request.GET["period_start"]),
                    period_end=date.fromisoformat(request.GET["period_end"]),
                    company=company,
                )
                messages.success(request, f"Cash flow generated for {company.code}.")
            elif request.GET.get("month"):
                latest = CashFlowService.generate_month(company, year, month)
                messages.success(request, f"Cash flow generated for {company.code} — {month:02d}/{year}.")
        except (ValueError, AccountingError) as exc:
            messages.error(request, str(exc))
    ctx = cash_flow_options()
    nets = None
    if latest:
        nets = {
            "operating": latest.collections - latest.payments_to_depot,
            "investing": -latest.asset_acquisitions,
            "financing": latest.loan_proceeds - latest.loan_repayments,
        }
    ctx.update({"latest": latest, "nets": nets, "year": year, "month": month})
    return render(request, "ui/cash/cash_flow.html", ctx)


@login_required
def cash_flow_print(request):
    """Print‑optimized page for the cash flow statement (browser print dialog)."""
    as_of = request.GET.get("as_of") or date.today().isoformat()
    segment = request.GET.get("segment") or ""
    from apps.ui.services import TrialBalanceService

    rows, (debit, credit) = TrialBalanceService.rows(as_of=as_of, segment=segment or None)
    ctx = {
        "rows": rows,
        "debit": debit,
        "credit": credit,
        "as_of": as_of,
        "segment": segment,
    }
    return render(request, "ui/cash/cash_flow_print.html", ctx)


# ---------------------------------------------------------------------------
# COLLECTIBLES worksheet
# ---------------------------------------------------------------------------


@login_required
def collectibles(request):
    """COLLECTIBLES worksheet (ADR-029): Distribution + F&A rows per cycle."""
    from apps.cash.models import CollectiblesWorksheet, WeeklyCashCycle
    from apps.cash.services import CollectiblesService

    cycles = list(collectibles_cycle_options())
    cycle = None
    if request.GET.get("cycle"):
        cycle = WeeklyCashCycle.objects.filter(pk=request.GET["cycle"]).first()
    if cycle:
        try:
            CollectiblesService.generate(cycle)
            rows = list(CollectiblesWorksheet.objects.filter(cycle=cycle).order_by("department"))
        except AccountingError as exc:
            messages.error(request, str(exc))
            rows = []
    else:
        rows = []
    return render(request, "ui/cash/collectibles.html", {"cycles": cycles, "cycle": cycle, "rows": rows})


# ---------------------------------------------------------------------------
# AR aging / register
# ---------------------------------------------------------------------------


@login_required
def aging(request):
    """AR aging buckets 30/60/90/120+ + per-invoice register as of a date."""
    from .services import aging_context

    as_of = date.fromisoformat(request.GET["as_of"]) if request.GET.get("as_of") else date.today()
    ctx = aging_context(as_of)
    ctx["page_obj"] = _page(request, ctx.pop("register"))
    return render(request, "ui/ar/aging.html", ctx)


@login_required
def ap_aging(request):
    """AP aging buckets + per-RFP open payable register as of a date."""
    from .services import ap_aging_context

    as_of = date.fromisoformat(request.GET["as_of"]) if request.GET.get("as_of") else date.today()
    ctx = ap_aging_context(as_of)
    ctx["page_obj"] = _page(request, ctx.pop("register"))
    return render(request, "ui/ap/aging.html", ctx)


@login_required
def fleet_fuel(request):
    """Fleet fuel management report: per-vehicle consumption + register."""
    from apps.fleet.models import Vehicle
    from apps.fleet.services import fleet_fuel_summary, record_fuel_log

    if request.method == "POST":
        try:
            vehicle = Vehicle.objects.get(pk=request.POST["vehicle"])
            record_fuel_log(
                vehicle=vehicle,
                logged_at=date.fromisoformat(request.POST["logged_at"]),
                liters=request.POST["liters"],
                cost_amount=request.POST["cost_amount"],
                segment=(
                    Segment.objects.filter(pk=request.POST["segment"]).first()
                    if request.POST.get("segment")
                    else None
                ),
                notes=request.POST.get("notes", ""),
                user=request.user,
            )
            messages.success(request, f"Fuel log recorded for {vehicle.plate_no}.")
        except (Vehicle.DoesNotExist, ValueError, AccountingError) as exc:
            messages.error(request, str(exc))

    start = request.GET.get("start") or None
    end = request.GET.get("end") or None
    segment = request.GET.get("segment") or None
    ctx = fleet_fuel_summary(start=start, end=end, segment=segment)
    ctx.update(
        {
            "vehicles": Vehicle.objects.select_related("segment").order_by("plate_no"),
            "segments": Segment.objects.order_by("code"),
            "start": start or "",
            "end": end or "",
            "segment_sel": segment or "",
        }
    )
    ctx["page_obj"] = _page(request, ctx.pop("rows"))
    return render(request, "ui/fleet/fuel.html", ctx)


# ---------------------------------------------------------------------------
# Tax & compliance (Phase 9)
# ---------------------------------------------------------------------------


@login_required
def tax_dashboard(request):
    """Tax & compliance hub: calendar, VAT, WHT certs, income tax provision."""
    from apps.tax.models import IncomeTaxProvision, TaxCalendar, VATComputation
    from apps.tax.services import TaxCalendarService

    from .services import tax_calendar_context

    ctx = {"provisions": IncomeTaxProvision.objects.select_related("segment", "journal_entry").order_by("-filing_period")}
    ctx.update(tax_calendar_context())
    return render(request, "ui/tax/dashboard.html", ctx)


@login_required
def tax_vat(request):
    """VAT at SI level (Phase 9): extract output VAT for a period."""
    from apps.tax.models import VATComputation
    from apps.tax.services import VATService

    computations = []
    summary = None
    period_start = request.GET.get("period_start")
    period_end = request.GET.get("period_end")
    if period_start and period_end:
        company = Company.objects.first()
        if company:
            computations = VATService.extract_for_period(
                company, date.fromisoformat(period_start), date.fromisoformat(period_end)
            )
            summary = VATService.period_summary(computations)
    return render(
        request, "ui/tax/vat.html",
        {"computations": computations, "summary": summary,
         "period_start": period_start or "", "period_end": period_end or ""},
    )


@login_required
def tax_wht(request):
    """BIR 2307/2306 prep from posted CV withholding (Phase 9)."""
    from apps.tax.services import WithholdingService

    cert_type = request.GET.get("cert_type", "2307")
    period_start = request.GET.get("period_start") or None
    period_end = request.GET.get("period_end") or None
    rows = WithholdingService.build_certificates(
        cert_type=cert_type,
        period_start=date.fromisoformat(period_start) if period_start else None,
        period_end=date.fromisoformat(period_end) if period_end else None,
    )
    return render(
        request, "ui/tax/wht.html",
        {"rows": rows, "cert_type": cert_type,
         "period_start": period_start or "", "period_end": period_end or ""},
    )


@login_required
def tax_provision(request):
    """Income tax provision: Dr 64600 | Cr income tax payable (Phase 9)."""
    from apps.tax.models import IncomeTaxProvision
    from apps.tax.services import IncomeTaxService

    if request.method == "POST":
        try:
            segment = Segment.objects.get(pk=request.POST["segment"])
            prov = IncomeTaxService.provision(
                company=segment.company,
                segment=segment,
                taxable_income=request.POST["taxable_income"],
                filing_period=request.POST["filing_period"],
                rate=request.POST.get("rate") or None,
                user=request.user,
            )
            messages.success(request, f"Income tax provision ₱{prov.tax_amount} posted.")
            return redirect("ui:tax_dashboard")
        except (Segment.DoesNotExist, ValueError, AccountingError) as exc:
            messages.error(request, str(exc))
    return render(
        request, "ui/tax/provision.html",
        {"segments": Segment.objects.order_by("code")},
    )


@login_required
def tax_calendar(request):
    """Tax calendar: file/paid tracking updates."""
    from apps.tax.models import TaxCalendar
    from apps.tax.services import TaxCalendarService

    from .services import tax_calendar_context

    if request.method == "POST":
        calendar_id = request.POST.get("calendar_id")
        status = request.POST.get("status")
        calendar = get_object_or_404(TaxCalendar, pk=calendar_id)
        try:
            TaxCalendarService.mark(
                calendar, status=status,
                filed_date=date.fromisoformat(request.POST["filed_date"]) if request.POST.get("filed_date") else None,
                paid_date=date.fromisoformat(request.POST["paid_date"]) if request.POST.get("paid_date") else None,
                user=request.user,
            )
            messages.success(request, f"{calendar.form} {calendar.filing_period} marked {status}.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("ui:tax_dashboard")
    ctx = tax_calendar_context()
    ctx["STATUSES"] = [
        ("not_due", "Not due"), ("due", "Due"), ("filed", "Filed"),
        ("paid", "Paid"), ("overdue", "Overdue"),
    ]
    return render(request, "ui/tax/calendar.html", ctx)


# ---------------------------------------------------------------------------
# Advances to Employees
# ---------------------------------------------------------------------------


@login_required
def advances(request):
    """Advances to Employees ledger (ADR-021) with liquidation form."""
    ctx = advances_context()
    ctx["page_obj"] = _page(request, ctx.pop("rows"))
    return render(request, "ui/ap/advances.html", ctx)


@login_required
@require_POST
def advance_liquidate(request, pk):
    from apps.ap.models import AdvanceToEmployee
    from apps.ap.services import AdvanceService

    adv = get_object_or_404(AdvanceToEmployee, pk=pk)
    try:
        AdvanceService.liquidate(
            adv,
            amount=request.POST["amount"],
            liquidate_date=date.fromisoformat(request.POST["liquidate_date"]),
            user=request.user,
        )
        messages.success(request, f"Advance for {adv.employee_name} updated.")
    except (ValueError, AccountingError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:advances")


# ---------------------------------------------------------------------------
# Inter-account transfers
# ---------------------------------------------------------------------------


@login_required
def transfers(request):
    """Inter-account transfer screen (ADR-030): Dr Cash-To | Cr Cash-From."""
    ctx = transfers_context()
    ctx["page_obj"] = _page(request, ctx.pop("transfers"))
    return render(request, "ui/cash/transfers.html", ctx)


@login_required
@require_POST
def transfer_create(request):
    from apps.cash.models import BankAccount
    from apps.cash.services import TransferService

    try:
        from_account = BankAccount.objects.get(pk=request.POST["from_account"])
        to_account = BankAccount.objects.get(pk=request.POST["to_account"])
        transfer = TransferService.transfer(
            from_account=from_account,
            to_account=to_account,
            amount=request.POST["amount"],
            purpose=request.POST["purpose"],
            transfer_date=date.fromisoformat(request.POST["transfer_date"]) if request.POST.get("transfer_date") else None,
            user=request.user,
        )
        messages.success(request, f"Transfer {transfer.transfer_date} posted ({from_account.code} → {to_account.code}).")
    except (BankAccount.DoesNotExist, ValueError, AccountingError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:transfers")


# ---------------------------------------------------------------------------
# User management (superadmin): who does what + approval hierarchy (ADR-020/036)
# ---------------------------------------------------------------------------


def _require_superuser(request):
    """Gate a view to the superadmin. Must follow a ``@login_required``."""
    if not request.user.is_superuser:
        raise PermissionDenied("Superadmin access required for user management.")


@login_required
def user_management(request):
    """Users & approval roles — the single "who does what" screen.

    Superadmin only. Lists every login with its approval role (staff -> head
    -> coo) and any petty-cash funds the user is custodian of, and posts role
    / active changes inline.
    """
    _require_superuser(request)
    from apps.core.approvals import APPROVAL_ROLES, ROLE_LABELS
    from apps.foundation.services import UserManagementService
    from apps.cash.models import PettyCashFund

    return render(
        request,
        "ui/foundation/user_management.html",
        {
            "rows": UserManagementService.list_users(),
            "role_choices": [(r, ROLE_LABELS[r]) for r in APPROVAL_ROLES],
            "pcf_count": PettyCashFund.objects.exclude(custodian=None).count(),
        },
    )


@login_required
@require_POST
def user_create(request):
    """Create a new login (optionally with an approval role)."""
    _require_superuser(request)
    from apps.foundation.services import UserManagementService

    try:
        u = UserManagementService.create_user(
            username=request.POST.get("username", ""),
            first_name=request.POST.get("first_name", ""),
            last_name=request.POST.get("last_name", ""),
            email=request.POST.get("email", ""),
            role=request.POST.get("role", ""),
            password=request.POST.get("password") or None,
        )
        messages.success(request, f"Created login '{u.username}'.")
    except (IntegrityError, ValueError, ValidationError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:user_management")


@login_required
@require_POST
def user_update(request, pk):
    """Update an existing user's approval role / active flag."""
    _require_superuser(request)
    from apps.foundation.services import UserManagementService
    from apps.foundation.models import UserProfile

    user = get_object_or_404(get_user_model(), pk=pk)
    try:
        UserManagementService.assign_role(user=user, role=request.POST.get("role", ""))
        active = request.POST.get("is_active") == "1"
        if user.is_active != active:
            UserManagementService.set_active(user=user, is_active=active)
        messages.success(
            request, f"Updated '{user.username}' (role: {request.POST.get('role', '') or 'unassigned'})."
        )
    except (UserProfile.DoesNotExist, ValueError, ValidationError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:user_management")
