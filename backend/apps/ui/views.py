"""Server-rendered UI views (Django templates + HTMX).

Every screen here is a thin HTML layer over the bounded-context services —
no business logic lives in this app (ADR-009). Forms post to the same
service functions the DRF API uses, so the UI and the API can never drift.
"""

from datetime import date, timedelta
from decimal import Decimal
import json
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, HttpResponseRedirect, Http404, JsonResponse
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
    customer_aging_context,
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
    list_pos,
    list_receipts,
    list_recons,
    list_rfps,
    list_suppliers,
    month_end_close_context,
    po_summary,
    po_timeline,
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
    "closed": "Closed",
}


def _parse_date(value, fallback=None):
    """date.fromisoformat with a fallback — malformed query params must
    never raise a 500."""
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return fallback


def _parse_int(value, fallback=None):
    """int() with a fallback — hostile query params never raise a 500."""
    if not value:
        return fallback
    try:
        return int(value)
    except (ValueError, TypeError):
        return fallback


def _export_url(view_name, **params):
    """Export endpoint for a screen, carrying its current filter state so a
    download always matches what the user sees."""
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    url = reverse(view_name)
    return f"{url}?{query}" if query else url


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
    """Journal Entries register — search + status/segment filters (HTMX)."""
    from apps.posting.models import JournalEntry

    from .filter_specs import je_filter_spec

    spec = je_filter_spec()
    qs = spec.apply(
        JournalEntry.objects.select_related("company", "segment").order_by(
            "-transaction_date", "-id"
        ),
        request.GET,
    )
    ctx = {
        "page_obj": _page(request, qs),
        "filters": spec.context(request.GET, request),
    }
    template = (
        "ui/posting/_je_table.html"
        if request.headers.get("HX-Request")
        else "ui/posting/je_list.html"
    )
    return render(request, template, ctx)


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
        "cost_centers": CostCenter.objects.filter(is_active=True).order_by("code"),
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
    supplier_name = request.POST.get("supplier_name", "").strip()[:255]
    po = request.POST.get("po", "").strip()[:128]
    ref_number = request.POST.get("ref_number", "").strip()[:128]

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
    centers = request.POST.getlist("line_cost_center")

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
                "cost_center": (centers[i] if i < len(centers) else "")[:64],
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
                    supplier_name=supplier_name,
                    po=po,
                    ref_number=ref_number,
                    created_by=request.user,
                )
                for i, p in enumerate(parsed, start=1):
                    JournalEntryLine.objects.create(
                        entry=entry,
                        line_no=i,
                        account=p["account"],
                        segment=p["segment"],
                        description=p["description"],
                        cost_center=p["cost_center"],
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
    centers = request.POST.getlist("line_cost_center")
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
                "cost_center": (centers[i] if i < len(centers) else "")[:64],
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
    """Post an approved JE. Only the Accounting & Finance Head may post."""
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
        from apps.core.approvals import require_approval_role

        require_approval_role(request.user, "head")
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
        "cost_centers": CostCenter.objects.filter(is_active=True).order_by("code"),
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


@login_required
def je_csv_export(request, pk):
    """Export a journal entry as a structured CSV download.

    Mirrors the printed voucher (je_print / je_pdf_export) as closely as a
    CSV allows: ENTRY INFORMATION block first, then the ACCOUNT DISTRIBUTION
    table (# | COA | Account Name | Segment | Cost Center | Description |
    Debit | Credit) with one row per distribution line, TOTALS, and the
    Prepared By / Approved By block. Amounts are exported as raw unformatted
    decimals (no thousand separators); the csv module handles quoting of
    commas and long descriptions.
    """
    entry = get_object_or_404(
        JournalEntry.objects.select_related("company", "segment")
            .prefetch_related("lines__account", "lines__segment"),
        pk=pk,
    )

    from apps.core.approvals import role_assignee, signatory_name
    from apps.foundation.calendar import cycle_range_for

    import csv
    import io

    requested_by = signatory_name(entry.created_by)
    approved_by = signatory_name(entry.approved_by) if entry.approved_by else ""
    if not approved_by and entry.status == PostingStatus.APPROVED:
        approved_by = role_assignee("head")

    cycle_start, cycle_end = cycle_range_for(
        entry.transaction_date, company=entry.company
    )
    if cycle_start.month == cycle_end.month:
        cycle_label = f"{cycle_start:%b} {cycle_start.day}-{cycle_end.day}, {cycle_start:%Y}"
    else:
        cycle_label = (
            f"{cycle_start:%b} {cycle_start.day} - {cycle_end:%b} {cycle_end.day}, {cycle_end:%Y}"
        )

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # ENTRY INFORMATION (mirrors the printed header block)
    writer.writerow(["ENTRY INFORMATION"])
    writer.writerow(["Voucher Ref #", entry.entry_no])
    writer.writerow(["Supplier / Customer", entry.supplier_name or ""])
    writer.writerow(["PO", entry.po or ""])
    writer.writerow(["REF #", entry.ref_number or ""])
    writer.writerow(["Date", entry.transaction_date.isoformat()])
    writer.writerow(["Cycle", cycle_label])
    writer.writerow(["Source Type", entry.source_doc_type or ""])
    writer.writerow(["Source No.", entry.source_doc_no or ""])
    writer.writerow(["Description", entry.description])
    writer.writerow([])

    # ACCOUNT DISTRIBUTION (mirrors the printed table)
    writer.writerow(["ACCOUNT DISTRIBUTION"])
    writer.writerow(["#", "COA", "Account Name", "Segment", "Cost Center", "Description", "Debit", "Credit"])
    entry_segment_code = entry.segment.code if entry.segment else ""
    for line in entry.lines.order_by("line_no"):
        writer.writerow(
            [
                line.line_no,
                line.account.code,
                line.account.name,
                line.segment.code if line.segment else entry_segment_code,
                line.cost_center or "",
                line.description or "",
                str(line.debit.quantize(Decimal("0.01"))) if line.debit else "",
                str(line.credit.quantize(Decimal("0.01"))) if line.credit else "",
            ]
        )
    writer.writerow([])
    writer.writerow(
        [
            "TOTALS",
            "",
            "",
            "",
            "",
            "",
            str(entry.total_debit.quantize(Decimal("0.01"))),
            str(entry.total_credit.quantize(Decimal("0.01"))),
        ]
    )
    writer.writerow([])

    # SIGNATURE BLOCK (mirrors the printed Prepared By / Approved By)
    writer.writerow(["Prepared By", requested_by])
    writer.writerow(["Approved By", approved_by])
    writer.writerow(["Signature over Printed Name", ""])
    writer.writerow(["Signature over Printed Name", ""])

    response = HttpResponse(output.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="JE_{entry.entry_no}.csv"'
    )
    return response


@login_required
def je_pdf_export(request, pk):
    """Download the journal entry as a real vector/text PDF voucher.

    Rendered server-side with ReportLab (apps/ui/pdf.py) following the same
    layout as the printed ACCTG-FOR-012 voucher: fixed column widths, cell
    text wrapping, repeated table headers across pages, selectable text.
    """
    entry = get_object_or_404(
        JournalEntry.objects.select_related("company", "segment")
            .prefetch_related("lines__account", "lines__segment"),
        pk=pk,
    )

    from apps.core.approvals import role_assignee, signatory_name

    requested_by = signatory_name(entry.created_by)
    approved_by = signatory_name(entry.approved_by) if entry.approved_by else ""
    if not approved_by and entry.status == PostingStatus.APPROVED:
        approved_by = role_assignee("head")

    from .pdf import build_journal_voucher_pdf

    data = build_journal_voucher_pdf(
        entry, requested_by=requested_by, approved_by=approved_by
    )
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="JE_{entry.entry_no}.pdf"'
    )
    return response


def _update_entry_from_form(request, entry):
    """Update an existing draft JE from form POST (mirrors _create_entry_from_form)."""
    transaction_date = date.fromisoformat(request.POST["transaction_date"])
    source_doc_type = request.POST.get("source_doc_type", "").strip()[:16]
    source_doc_no = request.POST.get("source_doc_no", "").strip()[:32]
    supplier_name = request.POST.get("supplier_name", "").strip()[:255]
    po = request.POST.get("po", "").strip()[:128]
    ref_number = request.POST.get("ref_number", "").strip()[:128]

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
    centers = request.POST.getlist("line_cost_center")

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
                "cost_center": (centers[i] if i < len(centers) else "")[:64],
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
        entry.supplier_name = supplier_name
        entry.po = po
        entry.ref_number = ref_number
        entry.fiscal_period = period
        entry.save(update_fields=["transaction_date", "segment", "description", "source_doc_type", "source_doc_no", "supplier_name", "po", "ref_number", "fiscal_period", "updated_at"])

        # Delete existing lines and recreate
        entry.lines.all().delete()
        for i, p in enumerate(parsed, start=1):
            JournalEntryLine.objects.create(
                entry=entry,
                line_no=i,
                account=p["account"],
                segment=p["segment"],
                description=p["description"],
                cost_center=p["cost_center"],
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
    as_of_date = _parse_date(request.GET.get("as_of"), date.today())
    as_of = as_of_date.isoformat()
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
    year = _parse_int(request.GET.get("year"), date.today().year) or date.today().year

    # as_of wins when provided (screens export with it); the legacy ?year=
    # form means the whole year through 12-31.
    today = date.today()
    as_of = request.GET.get("as_of")
    if as_of:
        as_of_date = _parse_date(as_of, today)
    else:
        as_of_date = date(year, 12, 31)
    as_of_iso = as_of_date.isoformat()

    from apps.ui.services import TrialBalanceService
    rows, (debit, credit) = TrialBalanceService.rows(as_of=as_of_iso)

    from apps.reporting.exports import csv_response, pdf_response

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
    as_of = _parse_date(request.GET.get("as_of"), date.today()).isoformat()
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
    """Download a financial statement (is/sfp/soce/cos/te) as XLSX / CSV / PDF."""
    from apps.reporting.excel_export import (
        build_income_statement,
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

    # Period defaults: fall back to the latest generated statement for this
    # company/type so the export URL never 500s without full params.
    if request.GET.get("period_start") and request.GET.get("period_end"):
        period_start = date.fromisoformat(request.GET["period_start"])
        period_end = date.fromisoformat(request.GET["period_end"])
    else:
        from apps.reporting.models import FinancialStatement
        latest = (
            FinancialStatement.objects.filter(
                statement_type=statement_type, company=company, segment=None
            )
            .order_by("-period_end")
            .first()
        )
        if latest:
            period_start, period_end = latest.period_start, latest.period_end
        else:
            period_start = date.fromisoformat(f"{date.today().year - 1}-01-01")
            period_end = date.fromisoformat(date.today().replace(month=12, day=31))

    builders = {
        "is": ("INCOME-STATEMENT", build_income_statement),
        "sfp": ("STATEMENT-OF-FINANCIAL-POSITION", build_statement_of_financial_position),
        "soce": ("STATEMENT-OF-CHANGES-IN-EQUITY", build_statement_of_changes_in_equity),
        "cos": ("STATEMENT-OF-COST-OF-SALES", build_statement_of_cost_of_sales),
        "te": ("STATEMENT-OF-TOTAL-EXPENSES", build_statement_of_total_expenses),
    }
    if statement_type not in builders:
        raise Http404

    if fmt == "csv":
        stem, builder = builders[statement_type]
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
def cash_flow_export(request):
    """Download the cash flow statement as XLSX / CSV / PDF.

    Mirrors the cash_flow screen — same month/year period, same line items —
    so the download can never disagree with what the user sees. The XLSX
    format reproduces the STATEMENT-OF-CASH-FLOW.xlsx workbook layout.
    """
    from apps.cash.models import CashFlowStatement
    from apps.cash.services import CashFlowService
    from apps.foundation.models import Company

    fmt = request.GET.get("format", "xlsx")
    company = Company.objects.first()
    if company is None:
        return HttpResponse("No company configured.", status=400)

    year = _parse_int(request.GET.get("year"), date.today().year)
    month = _parse_int(request.GET.get("month"), date.today().month)

    latest = None
    if company:
        try:
            if request.GET.get("period_start") and request.GET.get("period_end"):
                latest = CashFlowService.generate(
                    period_start=date.fromisoformat(request.GET["period_start"]),
                    period_end=date.fromisoformat(request.GET["period_end"]),
                    company=company,
                )
            else:
                latest = CashFlowService.generate_month(company, year, month)
        except (ValueError, AccountingError):
            latest = CashFlowStatement.objects.order_by("-period_end").first()
    if latest is None:
        return HttpResponse("No cash flow statement available yet.", status=404)

    stem = (
        f"STATEMENT-OF-CASH-FLOW-{latest.period_start:%Y%m%d}-{latest.period_end:%Y%m%d}"
    )

    if fmt == "xlsx":
        from apps.reporting.excel_export import build_cash_flow_statement, xlsx_response

        wb = build_cash_flow_statement(company, latest.period_start, latest.period_end)
        return xlsx_response(wb, f"{stem}.xlsx")

    rows = [
        ("OPERATING ACTIVITIES", ""),
        ("Collections (Distribution + Other)", latest.collections),
        ("Payments to Depot / Outflows", -latest.payments_to_depot),
        ("Net Cash from Operating Activities", latest.collections - latest.payments_to_depot),
        ("INVESTING ACTIVITIES", ""),
        ("Asset Acquisitions (CAPEX)", -latest.asset_acquisitions),
        ("FINANCING ACTIVITIES", ""),
        ("Loans Proceeds (Borrowed)", latest.loan_proceeds),
        ("Loan / Fuel Checks Cleared", -latest.loan_repayments),
        ("NET CHANGE IN CASH", latest.net_change),
        ("Cash - Beginning", latest.beginning_cash),
        ("Cash - End (less ADB maintained)", latest.ending_cash),
        ("ADB Adjustments (reporting, not a cash movement)", latest.adb_adjustments),
    ]

    if fmt == "csv":
        import csv as csv_module
        from io import StringIO

        buffer = StringIO()
        writer = csv_module.writer(buffer)
        writer.writerow(["Period Start", latest.period_start.isoformat()])
        writer.writerow(["Period End", latest.period_end.isoformat()])
        writer.writerow(["Line Item", "Amount"])
        for label, amount in rows:
            writer.writerow([label, "" if amount in (None, "") else str(amount)])
        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{stem}.csv"'
        return response

    from apps.core.exports import Column, TableSpec, pdf_spec_response

    spec = TableSpec(
        title="CASH FLOW STATEMENT",
        columns=[Column("Line Item"), Column("Amount", money=True)],
        rows=[[label, amount] for label, amount in rows],
        page="portrait",
        sheet_title="CASH FLOW",
    )
    return pdf_spec_response(spec, f"{stem}.pdf")


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
    """Customers master — search + segment/group/tier filters (HTMX)."""
    from apps.ar.models import Customer

    from .filter_specs import customer_list_filter_spec

    spec = customer_list_filter_spec()
    qs = spec.apply(Customer.objects.order_by("name"), request.GET)
    ctx = {
        "page_obj": _page(request, qs),
        "filters": spec.context(request.GET, request),
    }
    template = (
        "ui/ar/_customer_table.html"
        if request.headers.get("HX-Request")
        else "ui/ar/customer_list.html"
    )
    return render(request, template, ctx)


@login_required
def customer_detail(request, pk: int):
    """Customer ledger / history screen: customer info + receipts + invoices + aging."""
    from datetime import date as _d
    from decimal import Decimal as _D

    from apps.ar.models import AcknowledgmentReceipt, ARInvoice, Customer
    from apps.foundation.models import Segment

    customer = get_object_or_404(Customer, pk=pk)
    as_of = request.GET.get("as_of", _d.today())

    aging = customer_aging_context(customer, as_of=as_of)

    receipts = AcknowledgmentReceipt.objects.filter(
        customer=customer
    ).select_related("cash_account", "segment").order_by("-transaction_date", "-receipt_no")

    return render(
        request,
        "ui/ar/customer_detail.html",
        {
            "customer": customer,
            "as_of": as_of,
            "aging": aging,
            "receipts": receipts,
        },
    )


@login_required
def receipt_list(request):
    """Acknowledgment Receipts — search + status/segment/customer filters (HTMX)."""
    from apps.ar.models import AcknowledgmentReceipt

    from .filter_specs import receipt_list_filter_spec

    spec = receipt_list_filter_spec()
    qs = spec.apply(
        AcknowledgmentReceipt.objects.select_related("customer", "segment").order_by(
            "-transaction_date", "-receipt_no"
        ),
        request.GET,
    )
    ctx = {
        "page_obj": _page(request, qs),
        "filters": spec.context(request.GET, request),
    }
    template = (
        "ui/ar/_receipt_table.html"
        if request.headers.get("HX-Request")
        else "ui/ar/receipt_list.html"
    )
    return render(request, template, ctx)


@login_required
def ar_receipts_export(request, fmt):
    """AR receipts register export (the screen's columns)."""
    from apps.ar.models import AcknowledgmentReceipt
    from apps.core.exports import Column, TableSpec, table_export

    qs = AcknowledgmentReceipt.objects.select_related("customer", "segment", "applied_to").order_by(
        "-transaction_date", "-receipt_no"
    )
    rows = [
        [
            r.receipt_no,
            r.transaction_date.isoformat(),
            r.customer.name,
            r.segment.code,
            r.get_payment_method_display(),
            r.amount,
            r.check_no or "",
            r.transaction_no or "",
            r.ref_po_no or "",
            r.applied_to.invoice_no if r.applied_to else "",
        ]
        for r in qs
    ]
    total = sum((r.amount for r in qs), Decimal("0.00"))
    spec = TableSpec(
        title="Acknowledgment Receipts (ACCTG-FOR-005)",
        columns=[
            Column("Receipt No"), Column("Date"), Column("Customer", width_cm=6),
            Column("Segment"), Column("Method"), Column("Amount", money=True),
            Column("Check No"), Column("Transaction No"), Column("Ref. PO No."),
            Column("Applied To Invoice"),
        ],
        rows=rows,
        totals_row=["", "", "", "", "TOTAL", total, "", "", "",""],
        sheet_title="AR RECEIPTS",
        page="portrait",
    )
    return table_export(spec, fmt, f"AR_receipts.{fmt}")


@login_required
def ar_receipt_print(request, pk: int):
    """Print-optimized Acknowledgment Receipt (ACCTG-FOR-005)."""
    from apps.ar.models import AcknowledgmentReceipt

    receipt = get_object_or_404(AcknowledgmentReceipt, pk=pk)
    return render(
        request,
        "ui/ar/receipt_print.html",
        {"receipt": receipt},
    )


@login_required
def ar_receipt_export(request, pk: int, fmt: str):
    """AR receipt single-record export (pdf/xlsx/csv)."""
    from apps.ar.models import AcknowledgmentReceipt
    from apps.core.exports import Column, TableSpec, table_export

    receipt = get_object_or_404(AcknowledgmentReceipt, pk=pk)
    qs = AcknowledgmentReceipt.objects.filter(pk=receipt.pk).select_related(
        "customer", "segment", "applied_to"
    )
    rows = [
        [
            receipt.receipt_no,
            receipt.transaction_date.isoformat(),
            receipt.customer.name,
            receipt.segment.code,
            receipt.get_payment_method_display(),
            receipt.amount,
            receipt.check_no or "",
            receipt.transaction_no or "",
            receipt.ref_po_no or "",
            receipt.applied_to.invoice_no if receipt.applied_to else "",
        ]
    ]
    total = receipt.amount
    spec = TableSpec(
        title=f"Acknowledgment Receipt — {receipt.receipt_no}",
        columns=[
            Column("Receipt No"), Column("Date"), Column("Customer", width_cm=6),
            Column("Segment"), Column("Method"), Column("Amount", money=True),
            Column("Check No"), Column("Transaction No"), Column("Ref. PO No."),
            Column("Applied To Invoice"),
        ],
        rows=rows,
        totals_row=["", "", "", "", "TOTAL", total, "", "", "",""],
        sheet_title="AR RECEIPT",
        page="portrait",
    )
    return table_export(spec, fmt, f"AR_receipt_{receipt.receipt_no}.{fmt}")


@login_required
def supplier_list(request):
    """Suppliers master — search + type/segment filters (HTMX)."""
    from apps.ap.models import Supplier

    from .filter_specs import supplier_list_filter_spec

    spec = supplier_list_filter_spec()
    qs = spec.apply(Supplier.objects.prefetch_related("contacts").order_by("name"), request.GET)
    ctx = {
        "page_obj": _page(request, qs),
        "filters": spec.context(request.GET, request),
    }
    template = (
        "ui/ap/_supplier_table.html"
        if request.headers.get("HX-Request")
        else "ui/ap/supplier_list.html"
    )
    return render(request, template, ctx)


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
    from apps.ap.models import RFPDocument
    from apps.ap.services import rfp_payable
    from apps.core.approvals import approval_role_of

    from .filter_specs import rfp_filter_spec

    role = approval_role_of(request.user)
    spec = rfp_filter_spec()
    qs = spec.apply(
        RFPDocument.objects.select_related("payee", "segment")
        .prefetch_related("lines")
        .order_by("-created_at"),
        request.GET,
    )
    page = _page(request, qs)
    for rfp in page.object_list:
        rfp.approval_info = _rfp_approval_info(rfp, role)
        rfp.payable_amount = rfp_payable(rfp)
    ctx = {
        "page_obj": page,
        "summary": rfp_summary(),
        "filters": spec.context(request.GET, request),
    }
    template = (
        "ui/ap/_rfp_table.html"
        if request.headers.get("HX-Request")
        else "ui/ap/rfp_list.html"
    )
    return render(request, template, ctx)


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
    from apps.foundation.models import Account

    if request.method == "POST":
        try:
            customer = Customer.objects.get(pk=request.POST["customer"])
            cash_account = Account.objects.get(pk=request.POST["cash_account"])
            transaction_date = request.POST["transaction_date"]

            receipt = CollectionService.create_receipt(
                customer=customer,
                transaction_date=transaction_date,
                amount=request.POST.get("amount"),
                cash_account=cash_account,
                payment_method=request.POST.get("payment_method", "cash"),
                check_no=request.POST.get("check_no", ""),
                transaction_no=request.POST.get("transaction_no", ""),
                ref_po_no=request.POST.get("ref_po_no", ""),
                applied_to=None,
                lines=[{
                    "account": cash_account.id,
                    "segment": customer.segment.id,
                    "cost_center": "",
                    "description": request.POST.get("description", ""),
                    "debit": money(request.POST.get("amount") or "0"),
                    "credit": 0.00,
                }],
                created_by=request.user,
            )
            messages.success(request, f"Receipt {receipt.receipt_no} created as Draft. Submit for Head approval to post to GL.")
            return redirect("ui:receipt_detail", pk=receipt.pk)
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


@login_required
def receipt_detail(request, pk: int):
    from apps.ar.models import AcknowledgmentReceipt

    receipt = get_object_or_404(AcknowledgmentReceipt, pk=pk)
    return render(
        request,
        "ui/ar/receipt_detail.html",
        {"receipt": receipt, "audit_trail": _audit_trail("ar", pk)},
    )


@login_required
def receipt_submit(request, pk: int):
    from apps.ar.services import CollectionService

    receipt = get_object_or_404(AcknowledgmentReceipt, pk=pk)
    try:
        CollectionService.submit(receipt, user=request.user)
        messages.success(request, f"Receipt {receipt.receipt_no} submitted for approval.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("ui:receipt_detail", pk=pk)


@login_required
def receipt_approve(request, pk: int):
    from apps.ar.services import CollectionService

    receipt = get_object_or_404(AcknowledgmentReceipt, pk=pk)
    try:
        CollectionService.approve(receipt, user=request.user)
        messages.success(request, f"Receipt {receipt.receipt_no} approved and posted to GL.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("ui:receipt_detail", pk=pk)


@login_required
def receipt_reject(request, pk: int):
    from apps.ar.services import CollectionService

    receipt = get_object_or_404(AcknowledgmentReceipt, pk=pk)
    note = request.POST.get("note", "")
    try:
        CollectionService.reject(receipt, user=request.user, note=note)
        messages.success(request, f"Receipt {receipt.receipt_no} rejected. Returned to Draft.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("ui:receipt_detail", pk=pk)


@login_required
def receipt_deposit(request, pk: int):
    from apps.ar.models import AcknowledgmentReceipt
    from apps.ar.services import DepositService
    from apps.foundation.models import Account

    receipt = get_object_or_404(AcknowledgmentReceipt, pk=pk)
    bank_account = Account.objects.get(pk=request.POST.get("bank_account")) if request.method == "POST" else None

    if request.method == "POST":
        try:
            # For now, create deposit with just this receipt; can be extended to multi-select
            deposit = DepositService.record_deposit(
                receipts=[receipt],
                bank_account=bank_account,
                transaction_date=request.POST.get("transaction_date"),
                reference=request.POST.get("reference", ""),
                user=request.user,
            )
            messages.success(request, f"Deposit {deposit.deposit_no} recorded and posted to GL.")
        except Exception as exc:
            messages.error(request, str(exc))
        return redirect("ui:receipt_detail", pk=pk)

    # GET: show deposit form with the receipt's segment and available bank accounts
    from apps.ar.services import segment_choices as _seg_choices  # just to have segment list
    from apps.foundation.models import Segment
    segments = Segment.objects.order_by("code")
    banks = Account.objects.filter(is_postable=True).order_by("code")
    return render(
        request,
        "ui/ar/receipt_deposit.html",
        {
            "receipt": receipt,
            "segments": segments,
            "banks": banks,
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
    from apps.ap.models import PurchaseOrder, Supplier
    from apps.ap.services import RFPService
    from apps.sequences.models import DocumentSequence

    if request.method == "POST":
        try:
            payee = Supplier.objects.get(pk=request.POST["payee"])
            segment = Segment.objects.get(pk=request.POST["segment"])
            rfp_date = request.POST.get("rfp_date", "")
            if not rfp_date:
                raise ValidationError("Enter the date of request.")
            po = None
            po_pk = (request.POST.get("po") or "").strip()
            if po_pk:
                po = get_object_or_404(PurchaseOrder, pk=po_pk)
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
                po=po,
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
            "cost_centers": CostCenter.objects.filter(is_active=True).order_by("code"),
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
    from apps.ap.services import rfp_payable

    payable = rfp_payable(rfp)

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
            "payable": money(payable),
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
    from apps.ap.services import rfp_payable

    payable = money(rfp_payable(rfp))
    return render(
        request,
        "ui/ap/rfp_print.html",
        {
            "rfp": rfp,
            "lines": lines,
            "dr_lines": dr_lines,
            "cr_lines": cr_lines,
            "total": total,
            "payable": payable,
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
def rfp_export(request, pk, fmt):
    """RFP export: PDF renders the ACCTG-FOR-012 form; XLSX/CSV the lines."""
    from apps.ap.models import RFPDocument
    from apps.core.exports import Column, TableSpec, table_export
    from .pdf import build_rfp_pdf

    rfp = get_object_or_404(
        RFPDocument.objects.select_related("payee", "segment"), pk=pk,
    )
    if (fmt or "").lower() == "pdf":
        data = build_rfp_pdf(rfp, paper="a5")
        response = HttpResponse(data, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="RFP_{rfp.ap_number}.pdf"'
        return response

    lines = list(rfp.lines.select_related("account", "segment").order_by("line_no"))
    total = sum((line.amount for line in lines if line.side == "dr"), Decimal("0.00")) or rfp.amount
    spec = TableSpec(
        title=f"RFP {rfp.ap_number} — Request for Payment (ACCTG-FOR-012)",
        columns=[
            Column("#"), Column("Side"), Column("COA"),
            Column("Account Name", width_cm=6), Column("Segment"),
            Column("Cost Center", width_cm=3.5), Column("Description", width_cm=6),
            Column("Amount", money=True),
        ],
        preamble=[
            ["Payee", rfp.payee.name],
            ["Date", rfp.rfp_date.isoformat()],
            ["Vendor No", rfp.payee.code],
            ["Department/Address", rfp.payee.address
             or f"{rfp.segment.name} ({rfp.segment.code})"],
            ["Status", rfp.status],
        ],
        rows=[
            [
                line.line_no, line.side.upper(), line.account.code,
                line.account.name, line.segment.code, line.cost_center or "",
                line.description or rfp.particulars, line.amount,
            ]
            for line in lines
        ],
        totals_row=["", "", "", "TOTAL", "", "", "", total],
        sheet_title=f"RFP_{rfp.ap_number}",
        page="portrait",
    )
    return table_export(spec, fmt, f"RFP_{rfp.ap_number}.{fmt}")


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
        from apps.ap.services import rfp_payable

        rfp.approval_info = _rfp_approval_info(rfp, approval_role_of(request.user))
        rfp.payable_amount = rfp_payable(rfp)
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
            po_pk = (request.POST.get("po") or "").strip()
            if po_pk and rfp.po_id != int(po_pk):
                from apps.ap.models import PurchaseOrder

                rfp.po = get_object_or_404(PurchaseOrder, pk=po_pk)
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
            "edit_mode": "revise",
            "segments": Segment.objects.order_by("code"),
            "accounts": Account.objects.filter(is_postable=True).order_by("code"),
            "cost_centers": CostCenter.objects.filter(is_active=True).order_by("code"),
        },
    )


@login_required
def rfp_edit(request, pk):
    """The preparer corrects a prepared RFP before submitting it. GET shows a
    prefilled edit form; POST runs RFPService.edit_prepared (prepared +
    preparer only)."""
    from apps.ap.models import PurchaseOrder, RFPDocument, Supplier
    from apps.ap.services import RFPService

    rfp = get_object_or_404(
        RFPDocument.objects.select_related("payee", "segment").prefetch_related("lines"), pk=pk
    )
    if rfp.status != "prepared":
        messages.error(request, "Only prepared RFPs can be edited.")
        return redirect("ui:rfp_detail", pk=pk)
    if request.user.id != rfp.created_by_id:
        messages.error(request, "Only the preparer may edit this RFP.")
        return redirect("ui:rfp_detail", pk=pk)

    if request.method == "POST":
        try:
            payee = get_object_or_404(Supplier, pk=request.POST["payee"])
            segment = get_object_or_404(Segment, pk=request.POST["segment"])
            rfp_date = request.POST.get("rfp_date", "")
            if not rfp_date:
                raise ValidationError("Enter the date of request.")
            po = None
            po_pk = (request.POST.get("po") or "").strip()
            if po_pk:
                po = get_object_or_404(PurchaseOrder, pk=po_pk)
            lines = _rfp_lines_from_form(request)
            if not lines:
                raise ValidationError("Add at least one charge line.")
            rfp = RFPService.edit_prepared(
                rfp,
                user=request.user,
                rfp_date=date.fromisoformat(rfp_date),
                payee=payee,
                segment=segment,
                po=po,
                purpose=request.POST.get("purpose", ""),
                lines=lines,
            )
            messages.success(request, f"RFP {rfp.ap_number} updated.")
            return redirect("ui:rfp_detail", pk=pk)
        except (AccountingError, ValidationError) as exc:
            messages.error(request, str(exc))

    return render(
        request,
        "ui/ap/rfp_form.html",
        {
            "editing": rfp,
            "edit_mode": "edit",
            "segments": Segment.objects.order_by("code"),
            "accounts": Account.objects.filter(is_postable=True).order_by("code"),
            "cost_centers": CostCenter.objects.filter(is_active=True).order_by("code"),
        },
    )


# ---------------------------------------------------------------------------
# AP — Purchase Orders (ADR-0XX)
# ---------------------------------------------------------------------------


def _po_lines_from_form(request):
    """Parse the PO line grid (parallel arrays) into line dicts.

    Every completed row contributes one POLine — PR no. / qty / unit /
    description / unit price. Rows without a description are skipped; the
    service recomputes each line's amount (qty x unit price).
    """
    pr_nos = request.POST.getlist("line_pr_no")
    qtys = request.POST.getlist("line_qty")
    units = request.POST.getlist("line_unit")
    descs = request.POST.getlist("line_description")
    prices = request.POST.getlist("line_unit_price")
    accounts = request.POST.getlist("line_account")
    lines = []
    for i, desc in enumerate(descs):
        desc = (desc or "").strip()
        if not desc:
            continue
        if i >= len(qtys) or i >= len(prices):
            raise ValidationError(f"Line {i + 1}: quantity and unit price are required.")
        try:
            qty = money(qtys[i] or 0)
            price = money(prices[i] or 0)
        except ValidationError:
            raise ValidationError(f"Line {i + 1}: quantity and unit price must be amounts.")
        lines.append(
            {
                "pr_number": (pr_nos[i] if i < len(pr_nos) else "").strip(),
                "qty": qty,
                "unit": (units[i] if i < len(units) else "").strip(),
                "description": desc,
                "unit_price": price,
                "account": (accounts[i] if i < len(accounts) else "").strip(),
            }
        )
    return lines


def _po_approval_info(po, role):
    """Inline-approval facts for one PO row (HTMX row swap). Mirror of
    apps.core.approvals.PO_NEXT_ROLE / po_queue."""
    from apps.core.approvals import PO_NEXT_ROLE
    from apps.ap.services import po_coo_required

    next_role = PO_NEXT_ROLE.get(po.status)
    if po.status == "fin_approved" and po_coo_required(po):
        next_role = "coo"
    can_act = bool(next_role) and role == next_role
    label = "Check" if po.status in ("prepared", "submitted") else "Approve"
    return {
        "has_action": can_act,
        "next_role": next_role,
        "label": label,
    }


@login_required
def po_list(request):
    from apps.ap.models import PurchaseOrder
    from apps.core.approvals import approval_role_of

    from .filter_specs import po_filter_spec

    role = approval_role_of(request.user)
    spec = po_filter_spec()
    qs = spec.apply(
        PurchaseOrder.objects.select_related("supplier", "segment").order_by(
            "-po_date", "-po_number"
        ),
        request.GET,
    )
    page = _page(request, qs)
    for po in page.object_list:
        po.approval_info = _po_approval_info(po, role)
    ctx = {
        "page_obj": page,
        "summary": po_summary(),
        "filters": spec.context(request.GET, request),
    }
    template = (
        "ui/ap/_po_table.html"
        if request.headers.get("HX-Request")
        else "ui/ap/po_list.html"
    )
    return render(request, template, ctx)


@login_required
def po_create(request):
    from apps.ap.models import Supplier
    from apps.ap.services import PurchaseOrderService

    if request.method == "POST":
        try:
            supplier = Supplier.objects.get(pk=request.POST["supplier"])
            segment = Segment.objects.get(pk=request.POST["segment"])
            po_date = request.POST.get("po_date", "")
            if not po_date:
                raise ValidationError("Enter the date of the purchase order.")
            lines = _po_lines_from_form(request)
            if not lines:
                raise ValueError("Add at least one line item.")
            po = PurchaseOrderService.create_po(
                po_number=DocumentSequence.next_number(
                    company=supplier.default_segment.company if supplier.default_segment else segment.company,
                    form_code="PO",
                    year=int(po_date[:4]),
                    pattern="{YYYY}-{SEQ:05d}",
                ),
                po_date=date.fromisoformat(po_date),
                supplier=supplier,
                segment=segment,
                particulars=request.POST.get("particulars", ""),
                lines=lines,
                discount=request.POST.get("discount") or "0.00",
                vat_amount=request.POST.get("vat_amount") or "0.00",
                other_charges=request.POST.get("other_charges") or "0.00",
                payment_terms=request.POST.get("payment_terms", ""),
                contract_duration=request.POST.get("contract_duration", ""),
                ship_to_company=request.POST.get("ship_to_company", ""),
                ship_to_address=request.POST.get("ship_to_address", ""),
                contact_person=request.POST.get("contact_person", ""),
                notes=request.POST.get("notes", ""),
                user=request.user,
            )
            messages.success(request, f"PO {po.po_number} created (prepared).")
            return redirect("ui:po_detail", pk=po.id)
        except (AccountingError, ValueError) as exc:
            messages.error(request, str(exc))
        except ObjectDoesNotExist as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "ui/ap/po_form.html",
        {"segments": Segment.objects.order_by("code")},
    )


@login_required
def po_detail(request, pk):
    from apps.ap.models import PurchaseOrder
    from apps.core.approvals import (
        approval_role_of,
        role_assignee,
        ROLE_LABELS,
        PO_NEXT_ROLE,
    )

    po = get_object_or_404(
        PurchaseOrder.objects.prefetch_related("lines", "rfps"), pk=pk
    )
    awaiting = None
    from apps.ap.services import po_pending_final_check

    role = PO_NEXT_ROLE.get(po.status)
    if po_pending_final_check(po):
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
        "ui/ap/po_detail.html",
        {
            "po": po,
            "timeline": po_timeline(po),
            "awaiting": awaiting,
            "is_head": approval_role_of(request.user) == "head",
            "audit_trail": _audit_trail("po", po.id),
        },
    )


@login_required
def po_print(request, pk):
    """Print-optimized Purchase Order matching the LIMDON template layout:
    PO# / date / vendor (name, address, TIN) / item grid with the
    discount→subtotal→VAT→others→total block / delivery block / AADB + CNR
    signature lines."""
    from apps.ap.models import PurchaseOrder

    po = get_object_or_404(
        PurchaseOrder.objects.select_related("supplier", "segment", "created_by"),
        pk=pk,
    )
    lines = list(po.lines.order_by("line_no"))
    return render(
        request,
        "ui/ap/po_print.html",
        {
            "po": po,
            "lines": lines,
            "contact_no": po.supplier.contact_no or "",
        },
    )


@login_required
@require_POST
def po_submit(request, pk):
    from apps.ap.models import PurchaseOrder

    po = get_object_or_404(PurchaseOrder, pk=pk)
    try:
        if po.status != "prepared":
            raise ValueError("Only prepared POs can be submitted.")
        po.status = "submitted"
        po.save(update_fields=["status", "updated_at"])
        from apps.ap.services import log_action

        log_action(po, "submitted", actor=request.user)
        messages.success(request, f"PO {po.po_number} submitted.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("ui:po_detail", pk=pk)


@login_required
@require_POST
def po_approve(request, pk):
    from apps.ap.models import PurchaseOrder
    from apps.ap.services import PurchaseOrderService
    from apps.core.approvals import approval_role_of, require_approval_role

    po = get_object_or_404(PurchaseOrder, pk=pk)
    is_hx = bool(request.headers.get("HX-Request"))
    try:
        require_approval_role(request.user, "head")
        po = PurchaseOrderService.approve_head(po, user=request.user)
        msg = f"PO {po.po_number} approved."
        messages.success(request, msg)
    except (AccountingError, ValueError) as exc:
        msg = str(exc)
        messages.error(request, msg)
    if is_hx:
        po.approval_info = _po_approval_info(po, approval_role_of(request.user))
        response = render(request, "ui/ap/_po_row.html", {"po": po})
        response["HX-Trigger"] = json.dumps({"showToast": msg})
        return response
    return redirect("ui:po_detail", pk=pk)


@login_required
@require_POST
def po_approve_cnr(request, pk):
    from apps.ap.models import PurchaseOrder
    from apps.ap.services import PurchaseOrderService
    from apps.core.approvals import require_approval_role

    po = get_object_or_404(PurchaseOrder, pk=pk)
    try:
        require_approval_role(request.user, "coo")
        po = PurchaseOrderService.approve_cnr(po, user=request.user)
        messages.success(request, f"PO {po.po_number} approved by CNR.")
    except AccountingError as exc:
        messages.error(request, str(exc))
    return redirect("ui:po_detail", pk=pk)


@login_required
@require_POST
def po_reject(request, pk):
    """An approver returns the PO to the preparer with a note (ADR-0XX
    reject/revise cycle)."""
    from apps.ap.models import PurchaseOrder
    from apps.ap.services import PurchaseOrderService
    from apps.core.approvals import PO_NEXT_ROLE, require_approval_role

    po = get_object_or_404(PurchaseOrder, pk=pk)
    from apps.ap.services import po_pending_final_check

    role = PO_NEXT_ROLE.get(po.status)
    if po_pending_final_check(po):
        role = "coo"
    note = request.POST.get("note", "")
    try:
        if role:
            require_approval_role(request.user, role)
        po = PurchaseOrderService.reject(po, user=request.user, note=note)
        messages.success(request, f"PO {po.po_number} rejected and returned to {po.created_by}.")
    except (AccountingError, ValidationError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:po_detail", pk=pk)


@login_required
def po_revise(request, pk):
    """The preparer revises a rejected PO and resubmits it. GET shows a
    prefilled edit form; POST runs PurchaseOrderService.revise (preparer-only)."""
    from apps.ap.models import PurchaseOrder
    from apps.ap.services import PurchaseOrderService

    po = get_object_or_404(
        PurchaseOrder.objects.select_related("supplier").prefetch_related("lines"), pk=pk
    )
    if request.user.id != po.created_by_id:
        messages.error(request, "Only the preparer may revise this PO.")
        return redirect("ui:po_detail", pk=pk)

    if request.method == "POST":
        try:
            lines = _po_lines_from_form(request)
            if not lines:
                raise ValidationError("Add at least one line item.")
            po = PurchaseOrderService.revise(
                po,
                user=request.user,
                lines=lines,
                particulars=request.POST.get("particulars", ""),
                discount=request.POST.get("discount") or None,
                vat_amount=request.POST.get("vat_amount") or None,
                other_charges=request.POST.get("other_charges") or None,
                payment_terms=request.POST.get("payment_terms", ""),
                contract_duration=request.POST.get("contract_duration", ""),
                ship_to_company=request.POST.get("ship_to_company", ""),
                ship_to_address=request.POST.get("ship_to_address", ""),
                contact_person=request.POST.get("contact_person", ""),
                notes=request.POST.get("notes", ""),
            )
            messages.success(request, f"PO {po.po_number} revised and resubmitted.")
            return redirect("ui:po_detail", pk=pk)
        except (AccountingError, ValidationError) as exc:
            messages.error(request, str(exc))

    return render(
        request,
        "ui/ap/po_form.html",
        {"editing": po, "segments": Segment.objects.order_by("code")},
    )


@login_required
@require_POST
def po_close(request, pk):
    from apps.ap.models import PurchaseOrder
    from apps.ap.services import PurchaseOrderService
    from apps.core.approvals import require_approval_role

    po = get_object_or_404(PurchaseOrder, pk=pk)
    try:
        require_approval_role(request.user, "head")
        po = PurchaseOrderService.close_po(po, user=request.user)
        messages.success(request, f"PO {po.po_number} closed.")
    except AccountingError as exc:
        messages.error(request, str(exc))
    return redirect("ui:po_detail", pk=pk)


@login_required
def po_options(request):
    """Type-ahead source for the RFP form's Purchase Order picker.

    Lists approved POs that still hold available balance (total less reserved
    and already-billed RFPs), optionally narrowed to the RFP's supplier via
    ``?supplier=<pk|code>``. ``?selected=<po id>`` keeps a stable selection
    when editing an RFP, even if the PO is no longer billable.
    """
    from apps.ap.models import PurchaseOrder

    q = request.GET.get("q", "").strip()
    supplier = request.GET.get("supplier", "").strip()
    selected = request.GET.get("selected", "").strip()
    qs = (
        PurchaseOrder.objects.filter(status="approved")
        .select_related("supplier")
        .order_by("-po_number")
    )
    if supplier:
        if supplier.isdigit():
            qs = qs.filter(supplier_id=int(supplier))
        else:
            qs = qs.filter(supplier__code=supplier)
    if q:
        qs = qs.filter(Q(po_number__icontains=q) | Q(supplier__name__icontains=q))
    rows = [po for po in qs[:40] if po.available_amount > 0]
    if selected and selected not in {str(po.id) for po in rows}:
        keep = PurchaseOrder.objects.filter(pk=selected).first()
        if keep:
            rows.insert(0, keep)
    return JsonResponse(
        [
            {
                "id": po.id,
                "code": po.po_number,
                "text": f"{po.po_number} — {po.supplier.name}",
                "tin": po.supplier.tin,
                "available": str(po.available_amount),
            }
            for po in rows
        ],
        safe=False,
    )


@login_required
def po_prefill(request, pk):
    """JSON used by the RFP form when a Purchase Order is picked: the PO's
    vendor, segment and line items (each with its optional GL account) so the
    payee picker and distribution grid can be pre-filled. Only approved POs
    prefill; editing an RFP whose PO is no longer billable degrades to a
    manual entry (the picker keeps the stale selection via ?selected)."""
    from apps.ap.models import PurchaseOrder

    po = get_object_or_404(
        PurchaseOrder.objects.select_related("supplier", "segment").prefetch_related("lines"),
        pk=pk,
    )
    if po.status != "approved":
        return JsonResponse({"error": "Only approved POs can pre-fill an RFP."}, status=400)
    return JsonResponse(
        {
            "id": po.id,
            "po_number": po.po_number,
            "supplier_id": po.supplier_id,
            "supplier_code": po.supplier.code,
            "supplier_name": po.supplier.name,
            "segment_id": po.segment_id,
            "segment_code": po.segment.code,
            "available": str(po.available_amount),
            "lines": [
                {
                    "description": line.description,
                    "amount": str(line.amount),
                    "account_code": line.account.code if line.account else "",
                    "account_name": line.account.name if line.account else "",
                }
                for line in po.lines.all()
            ],
        }
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
def asset_export(request, pk, fmt):
    """Fixed Asset card export: header facts + depreciation schedule."""
    from apps.assets.models import Asset
    from apps.core.exports import Column, TableSpec, table_export

    asset = get_object_or_404(
        Asset.objects.select_related("category", "segment", "asset_account"), pk=pk,
    )
    schedule = list(asset.depreciation_schedule.select_related("journal_entry").order_by("period_start"))
    rows = [
        [
            row.period_start.isoformat(),
            row.amount,
            row.status,
            row.journal_entry.entry_no if row.journal_entry else "",
        ]
        for row in schedule
    ]
    spec = TableSpec(
        title=f"Fixed Asset Card — {asset.asset_no} {asset.name}",
        columns=[
            Column("Period Start"), Column("Amount", money=True),
            Column("Status"), Column("Journal Entry"),
        ],
        preamble=[
            ["Category", asset.category.name],
            ["Segment", asset.segment.code],
            ["Acquisition Date", asset.acquisition_date.isoformat()],
            ["Cost", asset.cost],
            ["Residual Value", asset.residual_value],
            ["Depreciable Base", asset.depreciable_base],
            ["Monthly Depreciation", asset.monthly_depreciation],
            ["Accumulated Depreciation", asset.accumulated_depreciation],
            ["Net Book Value", asset.net_book_value],
            ["Funding Source", asset.funding_source],
            ["Status", asset.status],
        ],
        rows=rows,
        totals_row=["TOTAL", sum((row.amount for row in schedule), Decimal("0.00")), "", ""],
        sheet_title=f"ASSET {asset.asset_no}",
        page="landscape",
    )
    return table_export(spec, fmt, f"Asset_{asset.asset_no}.{fmt}")


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
    """Check Vouchers — search + status/payee/bank filters (HTMX)."""
    from apps.ap.models import CheckVoucher

    from .filter_specs import cv_filter_spec

    spec = cv_filter_spec()
    qs = spec.apply(
        CheckVoucher.objects.select_related("payee", "bank_account", "rfp").order_by("-cv_date"),
        request.GET,
    )
    ctx = {
        "page_obj": _page(request, qs),
        "filters": spec.context(request.GET, request),
    }
    template = (
        "ui/ap/_cv_table.html"
        if request.headers.get("HX-Request")
        else "ui/ap/cv_list.html"
    )
    return render(request, template, ctx)


@login_required
def cv_create(request):
    from apps.ap.models import RFPDocument
    from apps.ap.services import CVPaymentService, rfp_payable

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
    payable = None
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
            payable = money(rfp_payable(selected_rfp))
        except (ValueError, RFPDocument.DoesNotExist):
            messages.error(request, "Selected RFP not found.")
    return render(
        request,
        "ui/ap/cv_form.html",
        {
            "rfps": approved_rfps(),
            "today": date.today(),
            "selected_rfp": selected_rfp,
            "payable": payable,
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
    from apps.ap.services import rfp_payable

    payable = money(rfp_payable(rfp)) if rfp else None
    from apps.cash.models import CheckDisbursement

    disb = CheckDisbursement.objects.filter(cv_id=cv.pk).values("cleared_at").first()
    cleared_at = disb["cleared_at"] if disb else None
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
        "payable": payable,
        "cleared_at": cleared_at,
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
    date_of_request = rfp.rfp_date if rfp and rfp.rfp_date else None
    from apps.ap.services import rfp_payable

    payable = money(rfp_payable(rfp)) if rfp else money(total)
    from apps.cash.models import CheckDisbursement

    disb = CheckDisbursement.objects.filter(cv_id=cv.pk).values("cleared_at").first()
    cleared_at = disb["cleared_at"] if disb else None
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
            "payable": payable,
            "cleared_at": cleared_at,
            "position": position,
            "signatories": signatories,
            "date_of_request": date_of_request,
        },
    )


@login_required
def cv_export(request, pk, fmt):
    """Check Voucher export: PDF renders the ACCTG-FOR-010 form; XLSX/CSV lines."""
    from apps.ap.models import CheckVoucher
    from apps.core.exports import Column, TableSpec, table_export
    from .pdf import build_cv_pdf

    cv = get_object_or_404(
        CheckVoucher.objects.select_related("payee", "bank_account", "rfp"), pk=pk,
    )
    if (fmt or "").lower() == "pdf":
        data = build_cv_pdf(cv, paper="a5")
        response = HttpResponse(data, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="CV_{cv.cv_number}.pdf"'
        return response

    rfp = cv.rfp
    lines = list(rfp.lines.select_related("account", "segment")) if rfp else []
    total = sum((line.amount for line in lines if line.side == "dr"), Decimal("0.00"))
    spec = TableSpec(
        title=f"CV {cv.cv_number} — Check Voucher (ACCTG-FOR-010)",
        columns=[
            Column("#"), Column("Side"), Column("COA"),
            Column("Account Name", width_cm=6), Column("Segment"),
            Column("Cost Center", width_cm=3.5), Column("Description", width_cm=6),
            Column("Amount", money=True),
        ],
        preamble=[
            ["Payee", cv.payee.name],
            ["Date", cv.cv_date.isoformat()],
            ["Check No", cv.check_no or ""],
            ["Gross Amount", cv.gross_amount],
            ["Withheld Tax", cv.withheld_tax],
            ["Net Amount", cv.net_amount],
            ["Status", cv.status],
        ],
        rows=[
            [
                line.line_no, line.side.upper(), line.account.code,
                line.account.name, line.segment.code, line.cost_center or "",
                line.description or (rfp.particulars if rfp else ""), line.amount,
            ]
            for line in lines
        ],
        totals_row=["", "", "", "TOTAL", "", "", "", total],
        sheet_title=f"CV_{cv.cv_number}",
        page="portrait",
    )
    return table_export(spec, fmt, f"CV_{cv.cv_number}.{fmt}")


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
    from apps.ap.services import CVPaymentService, rfp_payable

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
            "payable": money(rfp_payable(cv.rfp)) if cv.rfp_id else None,
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
    from apps.ap.models import Supplier
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
            suppliers = request.POST.getlist("exp_supplier")
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
                supplier = None
                supplier_id = suppliers[i] if i < len(suppliers) else ""
                if supplier_id:
                    supplier = Supplier.objects.filter(pk=supplier_id).first()
                if supplier is None:
                    raise ValidationError(f"Line {i + 1}: select a supplier (Business name).")
                expenses.append(
                    {
                        "account_code": Account.objects.get(code=acc_id).code,
                        "side": "dr" if debit else "cr",
                        "amount": str(debit or credit),
                        "description": (descs[i] if i < len(descs) else "")[:500],
                        "segment": segments[i] if i < len(segments) else "",
                        "cost_center": (cost_centers[i] if i < len(cost_centers) else "")[:64],
                        "supplier_id": supplier.pk,
                        "business_name": supplier.name,
                        "tin": supplier.tin,
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
            if request.POST.get("request_date"):
                replen.request_date = date.fromisoformat(request.POST["request_date"])
            replen.save(update_fields=["payee_name", "reference", "request_date", "updated_at"])
            messages.success(request, f"PCF replenishment {replen.voucher_no} requested (₱{replen.amount}).")
            return redirect("ui:pcf_replenishment_list")
        except (AccountingError, ValueError, KeyError) as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "ui/cash/pcf_replenish_form.html",
        {
            "funds": PettyCashFund.objects.filter(
                custodian=request.user, is_active=True
            ).select_related("gl_account", "company", "custodian").order_by("fund_code"),
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
    PETTY CASH REPLENISHMENT.xlsx columns. Columns the app does not capture yet
    (Type, DATE, REF., Address, VAT, AP NO) print blank."""
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
                "business_name": exp.get("business_name", ""),
                "tin": exp.get("tin", ""),
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
def pcf_replenishment_export(request, pk, fmt):
    """PCF replenishment export: PDF is the 23-col workpaper; XLSX/CSV the
    detail-screen columns (business name, TIN, description, segment, cost
    center, GL account, debit, credit)."""
    from apps.cash.models import PCFReplenishment
    from apps.core.exports import Column, TableSpec, table_export
    from .pdf import build_pcf_replenishment_pdf

    replen = get_object_or_404(
        PCFReplenishment.objects.select_related("fund__custodian", "fund__company"),
        pk=pk,
    )
    voucher_label = replen.voucher_no or str(replen.id)
    if (fmt or "").lower() == "pdf":
        data = build_pcf_replenishment_pdf(replen)
        response = HttpResponse(data, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="PCF_{voucher_label}.pdf"'
        return response

    rows = []
    dr_sum = Decimal("0.00")
    cr_sum = Decimal("0.00")
    for exp in replen.expenses or []:
        amount = Decimal(str(exp.get("amount", 0)))
        side = str(exp.get("side", "dr")).lower()
        if side == "cr":
            cr_sum += amount
        else:
            dr_sum += amount
        rows.append(
            [
                exp.get("business_name", ""),
                exp.get("tin", ""),
                exp.get("description", ""),
                exp.get("segment", ""),
                exp.get("cost_center", ""),
                exp.get("account_code", ""),
                amount if side != "cr" else "",
                amount if side == "cr" else "",
            ]
        )
    spec = TableSpec(
        title=f"PCF Replenishment {voucher_label}",
        columns=[
            Column("Business Name", width_cm=5), Column("TIN", width_cm=3),
            Column("Description", width_cm=6), Column("Segment", width_cm=2.5),
            Column("Cost Center", width_cm=2.5), Column("GL Account", width_cm=3),
            Column("Debit", money=True), Column("Credit", money=True),
        ],
        preamble=[
            ["Fund", replen.fund.name or replen.fund.fund_code],
            ["Request Date", replen.request_date.isoformat()],
            ["Payee", replen.payee_name or ""],
            ["Reference", replen.reference or ""],
            ["Status", replen.status],
        ],
        rows=rows,
        totals_row=["", "", "", "", "", "TOTAL", dr_sum, cr_sum],
        sheet_title=f"PCF_{voucher_label}",
        page="landscape",
    )
    return table_export(spec, fmt, f"PCF_{voucher_label}.{fmt}")


@login_required
@require_POST
def pcf_replenishment_post(request, pk):
    """Post the head-approved voucher to the GL. Same gate as RFP/CV steps:
    only the Accounting & Finance Head may post (ADR-032)."""
    from apps.cash.models import PCFReplenishment
    from apps.cash.services import PCFService
    from apps.core.approvals import require_approval_role

    replen = get_object_or_404(PCFReplenishment, pk=pk)
    try:
        require_approval_role(request.user, "head")
        PCFService.post_replenishment(replen, user=request.user)
        messages.success(request, f"Replenishment {replen.id} posted to GL.")
    except (AccountingError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:pcf_replenishment_detail", pk=pk)


@login_required
@require_POST
def pcf_replenishment_approve(request, pk):
    """Approve a PCF replenishment; this auto-creates its CONSO batch entry
    (ADR-038 §7c). The JE posts when the CONSO batch is posted. Head-only,
    mirroring the RFP approval step."""
    from apps.cash.models import PCFReplenishment
    from apps.cash.services import PCFService
    from apps.core.approvals import require_approval_role

    replen = get_object_or_404(PCFReplenishment, pk=pk)
    try:
        require_approval_role(request.user, "head")
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
def conso_export(request, pk, fmt):
    """CONSO batch export: every member (RFP / PCF replenishment) + total."""
    from apps.ap.models import CONSOBatch
    from apps.core.exports import Column, TableSpec, table_export

    batch = get_object_or_404(CONSOBatch, pk=pk)
    ctx = conso_context(batch)
    rows = [
        ["RFP", m.ap_number, m.rfp_date.isoformat(), m.payee.name, m.amount, m.status]
        for m in ctx["members"]
    ] + [
        ["PCF", r.payee_name or r.id, r.request_date.isoformat(),
         r.fund.name or r.fund.fund_code, r.amount, r.status]
        for r in ctx["pcf_members"]
    ]
    spec = TableSpec(
        title=f"CONSO {batch.batch_no}",
        columns=[
            Column("Type"), Column("Doc No"), Column("Date"),
            Column("Payee / Fund", width_cm=6), Column("Amount", money=True),
            Column("Status"),
        ],
        preamble=[
            ["CONSO Date", batch.conso_date.isoformat()],
            ["Members", len(rows)],
            ["Status", batch.status],
        ],
        rows=rows,
        totals_row=["", "", "", "TOTAL", ctx["total"], ""],
        sheet_title=f"CONSO {batch.batch_no}",
        page="portrait",
    )
    return table_export(spec, fmt, f"CONSO_{batch.batch_no}.{fmt}")


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
    context["export_url"] = _export_url("ui:collections_export", cycle=cycle.pk if cycle else "")
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
        start=_parse_date(request.GET.get("start")),
        end=_parse_date(request.GET.get("end")),
        segment=_parse_int(request.GET.get("segment")),
    )
    ctx["page_obj"] = _page(request, ctx.pop("rows"))
    ctx["start"] = request.GET.get("start", "")
    ctx["end"] = request.GET.get("end", "")
    ctx["segment_sel"] = request.GET.get("segment", "")
    return render(request, "ui/reporting/general_journal.html", ctx)


def _table_response(
    title,
    header,
    rows,
    fmt,
    stem,
    sheet_title="SHEET",
    money_cols=(),
    page="landscape",
    totals_row=None,
    preamble=None,
):
    """Render a plain table to xlsx/csv/pdf via the shared table engine."""
    from apps.core.exports import Column, TableSpec, table_export

    columns = [Column(h, money=(i in money_cols)) for i, h in enumerate(header)]
    spec = TableSpec(
        title=title,
        columns=columns,
        rows=rows,
        totals_row=totals_row,
        sheet_title=sheet_title,
        page=page,
    )
    if preamble is not None:
        spec.preamble = preamble
    return table_export(spec, fmt, f"{stem}.{fmt}")


@login_required
def je_xlsx_export(request, pk):
    """Export a single journal entry as an Excel (.xlsx) download.

    Same block layout as the old workbook: ENTRY INFORMATION meta rows, then
    the ACCOUNT DISTRIBUTION table with Debit/Credit as real numeric cells.
    """
    from apps.core.exports import Column, TableSpec, table_export

    entry = get_object_or_404(
        JournalEntry.objects.prefetch_related("lines__account", "lines__segment"),
        pk=pk,
    )
    preamble = [
        ["Voucher Ref #", entry.entry_no],
        ["Date", entry.transaction_date.isoformat()],
        ["Source Type", entry.source_doc_type or ""],
        ["Source No.", entry.source_doc_no or ""],
        ["Supplier / Customer Name", entry.supplier_name or ""],
        ["PO", entry.po or ""],
        ["REF #", entry.ref_number or ""],
        ["Segment", entry.segment.code if entry.segment else ""],
    ]
    rows = [
        [
            line.account.code or "",
            line.account.name or "",
            line.segment.code if line.segment else "",
            line.cost_center or "",
            line.description or "",
            line.debit,
            line.credit,
        ]
        for line in entry.lines.order_by("line_no")
    ]
    spec = TableSpec(
        title=f"JOURNAL ENTRY {entry.entry_no}",
        preamble=preamble,
        columns=[
            Column("COA"),
            Column("Account Name"),
            Column("Segment"),
            Column("Cost Center"),
            Column("Description"),
            Column("Debit", money=True),
            Column("Credit", money=True),
        ],
        rows=rows,
        totals_row=["TOTALS", "", "", "", "", entry.total_debit, entry.total_credit],
        sheet_title="JE",
    )
    return table_export(spec, "xlsx", f"JE_{entry.entry_no}.xlsx")


@login_required
def je_list_export(request):
    """Download the whole journal entries list as XLSX / CSV / PDF."""
    from .services import list_entries

    fmt = request.GET.get("format", "xlsx")
    entries = list_entries(limit=None)

    from apps.core.approvals import display_name

    header = ["Entry No.", "Date", "Description", "Segment", "Debit", "Credit", "Status", "Prepared By"]
    rows = [
        [
            e.entry_no,
            e.transaction_date.isoformat(),
            e.description,
            e.segment.code if e.segment else "",
            e.total_debit,
            e.total_credit,
            e.get_status_display(),
            display_name(e.created_by),
        ]
        for e in entries
    ]
    return _table_response(
        "JOURNAL ENTRIES", header, rows, fmt, "JOURNAL-ENTRIES",
        sheet_title="JE LIST", money_cols=(4, 5), totals_row=None,
        page="landscape",
    )


@login_required
def general_journal_export(request):
    """Download the General Journal register as XLSX / CSV / PDF.

    Honors the same date/segment filters as the screen, so the download can
    never disagree with what the user sees."""
    from .services import general_journal as gj

    fmt = request.GET.get("format", "xlsx")
    start = _parse_date(request.GET.get("start"))
    end = _parse_date(request.GET.get("end"))
    segment = _parse_int(request.GET.get("segment"))

    data = gj(start=start, end=end, segment=segment, limit=None)
    header = [
        "Date", "Cycle", "Ref #", "Supplier / Customer", "PO #", "Description",
        "CoA", "Account Name", "Cost Center", "Debit", "Credit",
    ]
    rows = [
        [
            r["date"].isoformat(),
            r["cycle"],
            r["ref"],
            r["party"],
            r["po"],
            r["description"],
            r["coa"],
            r["account_name"],
            r["cost_center"],
            r["debit"],
            r["credit"],
        ]
        for r in data["rows"]
    ]
    return _table_response(
        "GENERAL JOURNAL",
        header,
        rows,
        fmt,
        "GENERAL-JOURNAL",
        sheet_title="GJ",
        money_cols=(9, 10),
        totals_row=[
            "TOTALS", "", "", "", "", "", "", "", "",
            data["total_debit"], data["total_credit"],
        ],
        page="landscape",
    )


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
            {
                "id": a.id,
                "code": a.code,
                "text": f"{a.code} — {a.name}",
                "tin": a.tin,
            }
            for a in rows
        ],
        safe=False,
    )


@login_required
def customer_options(request):
    """Type-ahead source for searchable customer pickers (server-side).

    Returns the first ~30 active customers matching the query by code or name,
    plus the currently-selected customer (when editing) so the picker keeps a
    stable selection. ``?selected=`` accepts a customer code or id.
    """
    from apps.ar.models import Customer

    q = request.GET.get("q", "").strip()
    selected = request.GET.get("selected", "").strip()
    qs = Customer.objects.order_by("code")
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
    rows = list(qs[:30])
    if selected and selected not in {c.code for c in rows}:
        lookup = Q(code=selected)
        if selected.isdigit():
            lookup |= Q(pk=selected)
        keep = Customer.objects.filter(lookup).first()
        if keep:
            rows.insert(0, keep)
    return JsonResponse(
        [
            {
                "id": c.id,
                "code": c.code,
                "text": f"{c.code} — {c.name}",
                "tin": c.tin,
            }
            for c in rows
        ],
        safe=False,
    )


@login_required
def approved_rfp_options(request):
    """Type-ahead source for the CV form's "RFP to pay" (payee) picker.

    Mirrors the GL account picker contract: returns the first ~30 payable
    RFPs (posted + not yet paid — the same set the form dropdown lists)
    matching the query by RFP number, payee name or payee code, plus the
    currently-selected RFP so the picker keeps a stable selection while the
    user types. ``?q=`` filters; ``?selected=`` accepts an RFP id or number.
    """
    from django.db.models import Q

    q = request.GET.get("q", "").strip()
    selected = request.GET.get("selected", "").strip()
    qs = approved_rfps()
    if q:
        qs = qs.filter(
            Q(ap_number__icontains=q)
            | Q(payee__name__icontains=q)
            | Q(payee__code__icontains=q)
        )
    rows = list(qs[:30])
    if selected and not any(str(r.id) == selected or r.ap_number == selected for r in rows):
        lookup = Q(ap_number=selected)
        if selected.isdigit():
            lookup |= Q(pk=selected)
        keep = approved_rfps().filter(lookup).first()
        if keep:
            rows.insert(0, keep)
    return JsonResponse(
        [
            {
                "id": r.id,
                "code": r.ap_number,
                "text": f"{r.ap_number} — {r.payee.name} — ₱{r.amount:,.2f}",
            }
            for r in rows
        ],
        safe=False,
    )


@login_required
def party_options(request):
    """Type-ahead source for the Journal Voucher Supplier/Customer picker.

    Combines the supplier and customer masters into one result set so a
    single picker can assign the voucher party. ``?q=`` filters by code or
    name; results cap at 30, newest first. ``?selected=`` accepts a code, an
    id, or an exact recorded name (the journal stores the plain name, so
    editing re-attaches the stored party by name).
    """
    from apps.ap.models import Supplier
    from apps.ar.models import Customer

    q = request.GET.get("q", "").strip()
    selected = request.GET.get("selected", "").strip()
    rows_by_name = {}

    def pool(base_qs):
        if q:
            base_qs = base_qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
        return base_qs

    def match_selected(done, base_qs):
        keep = None
        if selected:
            lookup = Q(code=selected) | Q(name__icontains=selected)
            if selected.isdigit():
                lookup |= Q(pk=selected)
            keep = base_qs.filter(lookup).first()
        return keep

    suppliers = pool(Supplier.objects.select_related("default_segment"))
    customers = pool(Customer.objects.all())

    for s in suppliers[:20]:
        rows_by_name[f"{s.code} — {s.name}"] = {
            "id": s.id, "code": s.code, "text": f"{s.code} — {s.name}",
            "tin": s.tin, "kind": "supplier",
        }
    for c in customers[:20]:
        rows_by_name[f"{c.code} — {c.name}"] = {
            "id": c.id, "code": c.code, "text": f"{c.code} — {c.name}",
            "tin": c.tin, "kind": "customer",
        }

    keep_s = match_selected(set(), Supplier.objects.all())
    keep_c = match_selected(set(), Customer.objects.all())
    chosen = None
    if keep_s:
        chosen = {
            "id": keep_s.id, "code": keep_s.code,
            "text": f"{keep_s.code} — {keep_s.name}",
            "tin": keep_s.tin, "kind": "supplier",
        }
    elif keep_c:
        chosen = {
            "id": keep_c.id, "code": keep_c.code,
            "text": f"{keep_c.code} — {keep_c.name}",
            "tin": keep_c.tin, "kind": "customer",
        }
    results = list(rows_by_name.values())
    if chosen and chosen["text"] not in rows_by_name:
        results.insert(0, chosen)
    return JsonResponse(results[:30], safe=False)


from .filter_specs import coa_filter_spec


@login_required
def coa_list(request):
    """Chart of Accounts — read-only listing with search + filters."""
    from .services import coa_rows

    spec = coa_filter_spec()
    qs = coa_rows(
        q=request.GET.get("q", "").strip(),
        segment=request.GET.get("segment", "").strip(),
        account_type=request.GET.get("account_type", "").strip(),
    )
    # Note: spec.apply is omitted because coa_rows already applies q/segment/account_type.
    # The filter bar still renders the spec's UI and preserves values via context.
    ctx = {
        "page_obj": _page(
            request,
            qs,
            per_page=50,
        ),
        "filters": spec.context(request.GET, request),
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

    spec = coa_filter_spec()
    qs = coa_rows(
        q=request.GET.get("q", "").strip(),
        segment=request.GET.get("segment", "").strip(),
        account_type=request.GET.get("account_type", "").strip(),
    )
    qs = spec.apply(qs, request.GET)
    groups = []
    for value, label in AccountType.choices:
        accounts = [a for a in qs if a.account_type == value]
        if accounts:
            groups.append((label, accounts))
    return render(
        request,
        "ui/foundation/coa_print.html",
        {
            "groups": groups,
            "total": len(qs),
            "filter_context": spec.context(request.GET, request),
            "q": request.GET.get("q", "").strip(),
            "segment_sel": request.GET.get("segment", "").strip(),
            "account_type_sel": request.GET.get("account_type", "").strip(),
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
    period_start/period_end still works (legacy GET form / API e2e uses it).

    Export downloads live on the /reports/cash-flow/export/ endpoint; this
    screen generates + renders. The format select redirects there via the
    export toolbar URL."""
    from apps.cash.models import CashFlowStatement, WeeklyCashCycle
    from apps.cash.services import CashFlowService
    from apps.foundation.models import Company

    company = Company.objects.first()
    latest = CashFlowStatement.objects.order_by("-period_end").first()
    year = int(request.GET.get("year") or date.today().year)
    month = int(request.GET.get("month") or date.today().month)

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
    ctx.update(
        {
            "latest": latest,
            "nets": nets,
            "year": year,
            "month": month,
            "format": request.GET.get("format", "xlsx"),
        }
    )
    return render(request, "ui/cash/cash_flow.html", ctx)


@login_required
def cash_flow_print(request):
    """Print‑optimized page for the cash flow statement (browser print dialog)."""
    from apps.cash.models import CashFlowStatement, WeeklyCashCycle
    from apps.cash.services import CashFlowService
    from apps.foundation.models import Company

    company = Company.objects.first()
    year = int(request.GET.get("year") or date.today().year)
    month = int(request.GET.get("month") or date.today().month)
    latest = CashFlowStatement.objects.order_by("-period_end").first()
    if company:
        try:
            if request.GET.get("month"):
                latest = CashFlowService.generate_month(company, year, month)
        except (ValueError, AccountingError):
            pass
    nets = None
    if latest:
        nets = {
            "operating": latest.collections - latest.payments_to_depot,
            "investing": -latest.asset_acquisitions,
            "financing": latest.loan_proceeds - latest.loan_repayments,
        }
    ctx = {
        "latest": latest,
        "nets": nets,
        "year": year,
        "month": month,
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
    return render(
        request, "ui/cash/collectibles.html",
        {
            "cycles": cycles, "cycle": cycle, "rows": rows,
            "export_url": _export_url("ui:collectibles_export", cycle=cycle.pk if cycle else ""),
        },
    )


# ---------------------------------------------------------------------------
# AR aging / register
# ---------------------------------------------------------------------------


@login_required
def aging(request):
    """AR aging buckets 30/60/90/120+ + per-invoice register as of a date."""
    from .services import aging_context

    as_of = date.fromisoformat(request.GET["as_of"]) if request.GET.get("as_of") else date.today()
    ctx = aging_context(as_of)
    ctx["export_url"] = _export_url("ui:aging_export", as_of=as_of)
    ctx["page_obj"] = _page(request, ctx.pop("register"))
    return render(request, "ui/ar/aging.html", ctx)


@login_required
def ap_aging(request):
    """AP aging buckets + per-RFP open payable register as of a date."""
    from .services import ap_aging_context

    as_of = date.fromisoformat(request.GET["as_of"]) if request.GET.get("as_of") else date.today()
    ctx = ap_aging_context(as_of)
    ctx["export_url"] = _export_url("ui:ap_aging_export", as_of=as_of)
    ctx["page_obj"] = _page(request, ctx.pop("register"))
    return render(request, "ui/ap/aging.html", ctx)


@login_required
def ap_ledger(request):
    """Supplier / Payee Ledger Summary.

    Filter bar: text search (code / name), [All / With Outstanding Balance Only] dropdown,
    Export dropdown. Table: Code | Supplier/Payee Name | Total Billed | Total Paid | Outstanding.
    """
    from .services import ap_supplier_summary

    q = request.GET.get("q", "").strip()
    outstanding_only = request.GET.get("filter", "") == "outstanding"
    ctx = ap_supplier_summary(q=q, outstanding_only=outstanding_only)
    ctx["export_url"] = _export_url("ui:ap_ledger_export", q=q, filter="outstanding" if outstanding_only else "")
    ctx["page_obj"] = _page(request, ctx.pop("rows"))
    ctx["filter_url"] = request.GET.urlencode()
    return render(request, "ui/ap/ledger_summary.html", ctx)


@login_required
def ap_ledger_export(request):
    """Export the supplier/payee ledger summary as XLSX / CSV / PDF."""
    from .services import ap_supplier_summary

    q = request.GET.get("q", "").strip()
    outstanding_only = request.GET.get("filter", "") == "outstanding"
    ctx = ap_supplier_summary(q=q, outstanding_only=outstanding_only)
    rows = [
        [r["code"], r["name"], r["billed"], r["paid"], r["outstanding"]]
        for r in ctx["rows"]
    ]
    return _table_response(
        "SUPPLIER / PAYEE LEDGER SUMMARY",
        ["Code", "Supplier/Payee Name", "Total Billed", "Total Paid", "Outstanding Balance"],
        rows,
        request.GET.get("format", "xlsx"),
        "SUPPLIER-LEDGER-SUMMARY",
        sheet_title="SUPPLIER LEDGER SUMMARY",
        money_cols=(2, 3, 4),
        totals_row=["", "TOTALS", ctx["total_billed"], ctx["total_paid"], ctx["total_outstanding"]],
        page="landscape",
    )


@login_required
def ap_supplier_ledger(request, pk):
    """Supplier Statement of Account / AP Subsidiary Ledger."""
    from .services import ap_supplier_ledger
    from django.shortcuts import get_object_or_404
    from apps.ap.models import Supplier

    supplier = get_object_or_404(Supplier, pk=pk)
    start = request.GET.get("start")
    end = request.GET.get("end")
    # preserve existing querystring for filter persistence
    filter_qs = "&".join([f"{k}={v}" for k, v in request.GET.items() if k not in ("page", "start", "end")])
    ctx = ap_supplier_ledger(supplier=supplier, start=start, end=end)
    ctx["supplier"] = supplier
    ctx["filter_qs"] = filter_qs
    return render(request, "ui/ap/supplier_ledger.html", ctx)


@login_required
def ap_supplier_ledger_export(request, pk):
    """Export the supplier subsidiary ledger as XLSX / CSV / PDF."""
    from .services import ap_supplier_ledger
    from django.shortcuts import get_object_or_404
    from apps.ap.models import Supplier

    supplier = get_object_or_404(Supplier, pk=pk)
    start = request.GET.get("start")
    end = request.GET.get("end")
    ctx = ap_supplier_ledger(supplier=supplier, start=start, end=end)

    header = ["Date", "Ref #", "Type", "Description / Particulars", "Debit", "Credit", "Balance Dr", "Balance Cr"]
    rows = []
    for r in ctx["rows"]:
        rows.append([
            r["date"],
            r["ref"],
            r["type"],
            r["description"],
            r["debit"],
            r["credit"],
            r["balance_dr"] if r["balance_dr"] is not None else "",
            r["balance_cr"] if r["balance_cr"] is not None else "",
        ])
    # totals row
    totals = [
        ctx["start"] or "",
        "",
        "",
        "Period Totals",
        ctx["period_debit"],
        ctx["period_credit"],
        ctx["closing_dr"] if ctx["closing_dr"] is not None else "",
        ctx["closing_cr"] if ctx["closing_cr"] is not None else "",
    ]
    # preamble with supplier / period info
    preamble = [
        [f"Supplier: {ctx['supplier'].code} — {ctx['supplier'].name}", ""],
        [f"Period: {ctx['start'] or 'All Dates'}", ""],
    ]
    return _table_response(
        f"STATEMENT OF ACCOUNT — {supplier.code} {supplier.name}",
        header,
        rows,
        request.GET.get("format", "xlsx"),
        f"LEDGER-{supplier.code}",
        sheet_title="LEDGER",
        money_cols=(4, 5, 6, 7),
        totals_row=totals,
        page="landscape",
        preamble=preamble,
    )


@login_required
def ap_supplier_ledger_print(request, pk):
    """Print-optimized copy of the supplier ledger."""
    from .services import ap_supplier_ledger
    from django.shortcuts import get_object_or_404
    from apps.ap.models import Supplier

    supplier = get_object_or_404(Supplier, pk=pk)
    start = request.GET.get("start")
    end = request.GET.get("end")
    ctx = ap_supplier_ledger(supplier=supplier, start=start, end=end)
    ctx["supplier"] = supplier
    return render(request, "ui/ap/supplier_ledger_print.html", ctx)


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
            "export_url": _export_url(
                "ui:fleet_fuel_export", start=start, end=end, segment=segment
            ),
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
         "period_start": period_start or "", "period_end": period_end or "",
         "export_url": _export_url(
             "ui:tax_vat_export", period_start=period_start, period_end=period_end
         )},
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
         "period_start": period_start or "", "period_end": period_end or "",
         "export_url": _export_url(
             "ui:tax_wht_export",
             cert_type=cert_type, period_start=period_start, period_end=period_end,
         )},
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
    """Request one or more inter-account transfers from the batch grid (ADR-030).

    Every non-blank row becomes its own transfer + DRAFT JE (Dr Cash-To | Cr
    Cash-From). Nothing posts here: each transfer stays ``requested`` until
    the finance head approves it (transfer_approve), same flow as RFP/JE/CV.
    The batch is atomic: one invalid line rejects every leg.
    """
    from django.db import transaction

    from apps.cash.models import BankAccount
    from apps.cash.services import TransferService

    from_ids = request.POST.getlist("line_from")
    to_ids = request.POST.getlist("line_to")
    amounts = request.POST.getlist("line_amount")
    purposes = request.POST.getlist("line_purpose")

    # Backward-compatible single-leg POST (old inline form).
    if not from_ids and {"from_account", "to_account", "amount"} <= set(request.POST):
        from_ids, to_ids, amounts, purposes = (
            [request.POST["from_account"]],
            [request.POST["to_account"]],
            [request.POST["amount"]],
            [request.POST.get("purpose", "")],
        )

    transfer_date = date.fromisoformat(request.POST["transfer_date"]) if request.POST.get("transfer_date") else None
    bank_ids = {x for pair in (from_ids, to_ids) for x in pair if x}
    banks = {b.id: b for b in BankAccount.objects.filter(id__in=bank_ids)}

    def bank(pk):
        if not pk:
            raise AccountingError("Every transfer line needs both a From and a To account.")
        try:
            b = banks.get(int(pk))
        except (TypeError, ValueError):
            b = None
        if not b:
            raise AccountingError("Unknown bank account on a transfer line.")
        return b

    posted = []
    try:
        with transaction.atomic():
            for f_id, t_id, amt, purp in zip(from_ids, to_ids, amounts, purposes):
                if not (f_id or t_id or amt.strip()):
                    continue  # blank template row
                f = bank(f_id)
                t = bank(t_id)
                purpose = (purp or "").strip() or f"Fund transfer to {t.code} ({t.bank_name})"
                posted.append(
                    TransferService.transfer(
                        from_account=f,
                        to_account=t,
                        amount=amt,
                        purpose=purpose,
                        transfer_date=transfer_date,
                        user=request.user,
                    )
                )
            if not posted:
                raise AccountingError("Add at least one transfer line before posting.")
    except AccountingError as exc:
        messages.error(request, str(exc))
        return redirect("ui:transfers")
    messages.success(
        request,
        f"Requested {len(posted)} transfer(s) on "
        f"{transfer_date.strftime('%Y-%m-%d') if transfer_date else 'today'} — "
        f"awaiting head approval before posting.",
    )
    return redirect("ui:transfers")


@login_required
@require_POST
def transfer_approve(request, pk):
    """requested -> approved (finance head posts the transfer JE to the GL).

    Same gate as RFP/JE/CV approval: only the head may approve, and every
    transfer — whatever the amount (no threshold) — posts here.
    """
    from apps.cash.models import InterAccountTransfer
    from apps.cash.services import TransferService
    from apps.core.approvals import require_approval_role
    import logging

    logger = logging.getLogger(__name__)

    transfer = get_object_or_404(InterAccountTransfer, pk=pk)
    try:
        require_approval_role(request.user, "head")
        transfer = TransferService.approve(transfer, user=request.user)
        messages.success(request, f"Transfer {transfer.voucher_no} approved — entry in GL.")
    except Exception as exc:
        logger.error(f"Transfer approval error: {exc}")
        messages.error(request, "An error occurred during approval. Please try again.")
    return redirect("ui:transfers")


def _transfer_type(transfer):
    """Derived TRANSFER TYPE (no schema field): same bank -> intra-bank."""
    from_bank = (transfer.from_account.bank_name or "").strip().casefold()
    to_bank = (transfer.to_account.bank_name or "").strip().casefold()
    return "Intra-Bank Transfer" if from_bank and from_bank == to_bank else "Inter-Bank Transfer"


def _ftv_context(transfer):
    """Shared context for the FTV print view and ReportLab PDF export."""
    from apps.cash.services import TransferService
    from apps.core.approvals import role_assignee, signatory_name

    entry = transfer.journal_entry
    prepared_by = signatory_name(
        transfer.initiated_by or (entry.created_by if entry else None)
    )
    checked_by = role_assignee("head")
    approved_by = (
        signatory_name(transfer.approved_by)
        if transfer.approved_by
        else (role_assignee("coo") or checked_by)
    )
    return {
        "transfer": transfer,
        "voucher_no": TransferService.ensure_voucher_no(transfer),
        "transfer_type": _transfer_type(transfer),
        "entry": entry,
        "lines": list(entry.lines.order_by("line_no")) if entry else [],
        "total": entry.total_debit if entry else transfer.amount,
        "total_credit": entry.total_credit if entry else transfer.amount,
        "prepared_by": prepared_by,
        "checked_by": checked_by,
        "approved_by": approved_by,
        "date_label": (
            transfer.transfer_date.strftime("%B %d, %Y") if transfer.transfer_date else ""
        ),
    }


def _ftv_get(request, pk):
    from apps.cash.models import InterAccountTransfer

    return get_object_or_404(
        InterAccountTransfer.objects.select_related(
            "from_account", "to_account", "journal_entry", "initiated_by"
        ).prefetch_related("journal_entry__lines__account", "journal_entry__lines__segment"),
        pk=pk,
    )


@login_required
def ftv_print(request, pk):
    """Print-optimized Fund Transfer Voucher (FTV) — browser print dialog."""
    transfer = _ftv_get(request, pk)
    return render(request, "ui/cash/ftv_print.html", _ftv_context(transfer))


@login_required
def ftv_pdf_export(request, pk):
    """Download the Fund Transfer Voucher as a real vector/text PDF."""
    transfer = _ftv_get(request, pk)
    ctx = _ftv_context(transfer)

    from .pdf import build_fund_transfer_voucher_pdf

    data = build_fund_transfer_voucher_pdf(
        transfer,
        voucher_no=ctx["voucher_no"],
        transfer_type=ctx["transfer_type"],
        date_label=ctx["date_label"],
        prepared_by=ctx["prepared_by"],
        checked_by=ctx["checked_by"],
        approved_by=ctx["approved_by"],
    )
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="FTV_{ctx["voucher_no"]}.pdf"'
    )
    return response


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


# ---------------------------------------------------------------------------
# General Ledger — COA-grouped index + classic per-account running balance
# ---------------------------------------------------------------------------


def _ledger_month_options(company):
    """(month, label) options for the fiscal-month dropdown, from posted GL."""
    from apps.posting.models import GeneralLedger

    months = sorted(
        {
            (d.year, d.month)
            for d in GeneralLedger.objects.filter(
                entry__status="posted", entry__company=company
            ).values_list("transaction_date", flat=True)
        },
        reverse=True,
    )
    return [
        {"key": f"{year}-{month:02d}", "label": f"{date(year, month, 1):%b %Y}"}
        for year, month in months
    ]


def _ledger_ctx(request, extra=None):
    """Shared filter context for the ledger screens (window + period choices)."""
    from django.utils.http import urlencode

    from .services import ledger_window

    win = ledger_window(request.GET)
    q = {}
    if win["month"]:
        q["month"] = win["month"]
    elif win["start"] or win["end"]:
        if win["start"]:
            q["start"] = win["start"].isoformat()
        if win["end"]:
            q["end"] = win["end"].isoformat()
    if win["segment"]:
        q["segment"] = win["segment"]
    ctx = {
        "win": win,
        "period_options": _ledger_month_options(win["company"]),
        "start": win["start"].isoformat() if win["start"] else "",
        "end": win["end"].isoformat() if win["end"] else "",
        "segment_sel": win["segment"],
        "filter_qs": urlencode(q),
        "format": request.GET.get("format", "xlsx"),
    }
    if extra:
        ctx.update(extra)
    return ctx


@login_required
def ledger_index(request):
    """The COA-grouped ledger index: opening | period Dr | period Cr | closing.

    Filters are the shared window (fiscal month or date range) + optional
    segment; every account row drills into its running-balance register."""
    from .services import ledger_index as ledger_index_data

    win = _ledger_ctx(request)["win"]
    data = ledger_index_data(
        company=win["company"],
        start=win["start"],
        end=win["end"],
        segment=win["segment"] or None,
    )
    return render(
        request,
        "ui/reporting/ledger_index.html",
        _ledger_ctx(request, data),
    )


@login_required
def ledger_account_detail(request, pk):
    """The classic per-account register with a running balance."""
    from .services import ledger_account as account_reg

    win = _ledger_ctx(request)["win"]
    account = get_object_or_404(Account, pk=pk)
    reg = account_reg(
        account=account,
        company=win["company"],
        start=win["start"],
        end=win["end"],
        segment=win["segment"] or None,
    )
    return render(
        request,
        "ui/reporting/ledger_account.html",
        _ledger_ctx(request, reg),
    )


@login_required
def ledger_print(request):
    """Print-optimized copy of the ledger index (browser print dialog)."""
    win = _ledger_ctx(request)["win"]
    from .services import ledger_index as ledger_index_data

    data = ledger_index_data(
        company=win["company"],
        start=win["start"],
        end=win["end"],
        segment=win["segment"] or None,
    )
    return render(
        request,
        "ui/reporting/ledger_index_print.html",
        _ledger_ctx(request, data),
    )


@login_required
def ledger_account_print(request, pk):
    """Print-optimized copy of a per-account register."""
    win = _ledger_ctx(request)["win"]
    from .services import ledger_account as account_reg

    account = get_object_or_404(Account, pk=pk)
    reg = account_reg(
        account=account,
        company=win["company"],
        start=win["start"],
        end=win["end"],
        segment=win["segment"] or None,
    )
    return render(
        request,
        "ui/reporting/ledger_account_print.html",
        _ledger_ctx(request, reg),
    )


@login_required
def ledger_export(request):
    """Download the ledger index as XLSX / CSV / PDF (filters honored)."""
    from .services import ledger_index as ledger_index_data

    fmt = request.GET.get("format", "xlsx")
    win = _ledger_ctx(request)["win"]
    data = ledger_index_data(
        company=win["company"],
        start=win["start"],
        end=win["end"],
        segment=win["segment"] or None,
    )
    header = ["Code", "Account", "Classification", "Opening", "Debit", "Credit", "Closing"]
    rows = []
    for g in data["groups"]:
        for s in g["sections"]:
            for r in s["rows"]:
                rows.append(
                    [
                        r["code"],
                        r["name"],
                        r["classification"],
                        r["opening"],
                        r["debit"],
                        r["credit"],
                        r["closing"],
                    ]
                )
    stem = "LEDGER-INDEX"
    win_label = win["month"] or f"{win['start'] or ''}_{win['end'] or ''}".strip("_")
    return _table_response(
        "LEDGER INDEX", header, rows, fmt, f"{stem}-{win_label}", sheet_title="LEDGER",
        money_cols=(3, 4, 5, 6),
        totals_row=["", "TOTALS", "", "", data["total_debit"], data["total_credit"], ""],
        page="landscape",
    )


@login_required
def ledger_account_export(request, pk):
    """Download a per-account register as XLSX / CSV / PDF."""
    from .services import ledger_account as account_reg

    fmt = request.GET.get("format", "xlsx")
    win = _ledger_ctx(request)["win"]
    account = get_object_or_404(Account, pk=pk)
    reg = account_reg(
        account=account,
        company=win["company"],
        start=win["start"],
        end=win["end"],
        segment=win["segment"] or None,
    )
    header = ["Date", "Ref #", "Source", "Particulars", "Cost Center", "Debit", "Credit", "Balance"]
    rows = [
        [win["start"] or "", "Balance B/f", "", "Opening balance", "", "", "", reg["opening"]]
    ]
    for r in reg["rows"]:
        rows.append(
            [
                r["date"].isoformat(),
                r["entry_no"],
                f"{r['source_type']} {r['source_doc_no']}".strip(),
                r["particulars"],
                r["cost_center"],
                r["debit"],
                r["credit"],
                r["balance"],
            ]
        )
    stem = f"LEDGER-{account.code}"
    win_label = win["month"] or f"{win['start'] or ''}_{win['end'] or ''}".strip("_")
    return _table_response(
        f"LEDGER — {account.code} {account.name}", header, rows, fmt,
        f"{stem}-{win_label}", sheet_title="LEDGER",
        money_cols=(5, 6, 7),
        totals_row=[
            win["end"] or "", "TOTALS", "", "Period movement", "",
            reg["period_debit"], reg["period_credit"], reg["closing"],
        ],
        page="landscape",
    )


# ---------------------------------------------------------------------------
# Phase 3 — register/list exports (Engine A + screen-parity rows)
# ---------------------------------------------------------------------------


def _cycle_label(cycle):
    return f"{cycle.cycle_start.isoformat()} to {cycle.cycle_end.isoformat()}"


@login_required
def aging_export(request):
    """AR aging register (open invoice balances as-of the screen's date)."""
    fmt = request.GET.get("format", "xlsx")
    as_of = date.fromisoformat(request.GET["as_of"]) if request.GET.get("as_of") else date.today()
    ctx = aging_context(as_of)
    rows = [
        [
            r["invoice_no"],
            r["customer"],
            r["date"].isoformat(),
            r["segment"],
            r["status"],
            r["age_days"] if r["age_days"] is not None else "",
            r["balance"],
        ]
        for r in ctx["register"] + ctx["not_yet_due"]
    ]
    return _table_response(
        f"AR AGING & REGISTER AS OF {as_of.isoformat()}",
        ["Invoice #", "Customer", "Date", "Segment", "Status", "Age (days)", "Balance"],
        rows,
        fmt,
        "AR_AGING",
        sheet_title="AR AGING",
        money_cols=(6,),
        page="landscape",
        totals_row=["", "TOTAL OUTSTANDING", "", "", "", "",
                    ctx["register_total"] + ctx["not_yet_due_total"]],
    )


@login_required
def ap_aging_export(request):
    """AP aging register (open posted-RFP balances as-of the screen's date)."""
    from .services import ap_aging_context

    fmt = request.GET.get("format", "xlsx")
    as_of = date.fromisoformat(request.GET["as_of"]) if request.GET.get("as_of") else date.today()
    ctx = ap_aging_context(as_of)
    rows = [
        [
            r["ap_number"],
            r["payee"],
            r["date"].isoformat(),
            r["segment"],
            r["status"],
            r["age_days"] if r["age_days"] is not None else "",
            r["balance"],
        ]
        for r in ctx["register"] + ctx["not_yet_due"]
    ]
    return _table_response(
        f"AP AGING & REGISTER AS OF {as_of.isoformat()}",
        ["AP #", "Payee", "Date", "Segment", "Status", "Age (days)", "Open Balance"],
        rows,
        fmt,
        "AP_AGING",
        sheet_title="AP AGING",
        money_cols=(6,),
        page="landscape",
        totals_row=["", "TOTAL OPEN PAYABLES", "", "", "", "",
                    ctx["register_total"] + ctx["not_yet_due_total"]],
    )


@login_required
def customer_export(request):
    """Customer master export (superset of the customers screen columns)."""
    fmt = request.GET.get("format", "xlsx")
    rows = [
        [
            c.code,
            c.name,
            c.owner_name or "",
            c.contact_no or "",
            c.tin or "",
            c.segment.code if c.segment else "",
            c.group,
            c.pricing_tier,
            c.address or "",
            c.notes or "",
        ]
        for c in list_customers()
    ]
    return _table_response(
        "CUSTOMERS MASTER",
        ["Code", "Business Name", "Owner", "Contact", "TIN", "Segment",
         "Group", "Pricing Tier", "Address", "Notes"],
        rows,
        fmt,
        "CUSTOMERS",
        sheet_title="CUSTOMERS",
        page="landscape",
    )


@login_required
def supplier_export(request):
    """Supplier master export (superset of the suppliers screen columns)."""
    fmt = request.GET.get("format", "xlsx")
    rows = []
    for s in list_suppliers():
        contacts = ", ".join(
            f"{c.name}{' — ' + c.phone if c.phone else ''}" for c in s.contacts.all()
        ) or s.contact_no or ""
        rows.append(
            [
                s.code,
                s.name,
                s.owner_name or "",
                s.tin or "",
                s.email or "",
                contacts,
                "Yes" if s.attachments_required else "—",
            ]
        )
    return _table_response(
        "SUPPLIERS MASTER",
        ["Code", "Business Name", "Owner/Rep", "TIN", "Email", "Contact", "Attachments"],
        rows,
        fmt,
        "SUPPLIERS",
        sheet_title="SUPPLIERS",
        page="landscape",
    )


@login_required
def coa_export(request):
    """Chart of Accounts export honoring the screen's filters."""
    from .filter_specs import coa_filter_spec
    from .services import coa_rows

    spec = coa_filter_spec()
    fmt = request.GET.get("format", "xlsx")
    rows = [
        [
            a.code,
            a.name,
            a.segment or "",
            a.classification or "",
            a.category or "",
            a.sub_accounts or "",
            a.major_accounts or "",
            a.behavior or "",
            a.traceability or "",
            a.controllability or "",
        ]
        for a in spec.apply(
            coa_rows(
                q=request.GET.get("q", "").strip(),
                segment=request.GET.get("segment", "").strip(),
                account_type=request.GET.get("account_type", "").strip(),
            ),
request.GET,
        )
    ]
    return _table_response(
        "CHART OF ACCOUNTS",
        ["Code", "Account Name", "Segment", "Classification", "Category",
         "Sub-Accounts", "Major Accounts", "Behavior", "Traceability", "Controllability"],
        rows,
        fmt,
        "CHART_OF_ACCOUNTS",
        sheet_title="COA",
        page="landscape",
    )


@login_required
def assets_list_export(request):
    """Fixed assets register export honoring the screen's filters."""
    fmt = request.GET.get("format", "xlsx")
    rows = [
        [
            a.asset_no,
            a.name,
            a.category.name if a.category else "",
            a.segment.code if a.segment else "",
            a.acquisition_date.isoformat(),
            a.cost,
            a.status,
        ]
        for a in list_assets(
            limit=None,
            q=request.GET.get("q", "").strip(),
            category=request.GET.get("category", "").strip(),
            segment=request.GET.get("segment", "").strip(),
            status=request.GET.get("status", "").strip(),
        )
    ]
    return _table_response(
        "FIXED ASSETS REGISTER",
        ["Asset No", "Name", "Category", "Segment", "Acquired", "Cost", "Status"],
        rows,
        fmt,
        "ASSET-REGISTER",
        sheet_title="ASSETS",
        money_cols=(5,),
        page="landscape",
    )


@login_required
def transfers_export(request):
    """Inter-account transfer register (ADR-030)."""
    fmt = request.GET.get("format", "xlsx")
    rows = []
    for t in transfers_context()["transfers"]:
        rows.append(
            [
                t.transfer_date.isoformat(),
                t.voucher_no or "",
                t.from_account.code,
                t.to_account.code,
                t.amount,
                t.purpose,
                t.status,
                t.journal_entry.entry_no if t.journal_entry else "",
            ]
        )
    return _table_response(
        "INTER-ACCOUNT TRANSFERS",
        ["Date", "Voucher", "From (Credit)", "To (Debit)", "Amount", "Purpose", "Status", "JE"],
        rows,
        fmt,
        "TRANSFERS",
        sheet_title="TRANSFERS",
        money_cols=(4,),
        page="landscape",
    )


@login_required
def recon_export(request):
    """Bank reconciliation register (ADR-026)."""
    fmt = request.GET.get("format", "xlsx")
    rows = []
    for r in list_recons(limit=None):
        rows.append(
            [
                _cycle_label(r.cycle),
                r.bank_account.code,
                r.book_balance,
                r.bank_statement_balance,
                r.difference,
                r.status,
                r.reconciled_by.username if r.reconciled_by else "",
            ]
        )
    return _table_response(
        "BANK RECONCILIATIONS",
        ["Cycle", "Bank", "Book", "Bank statement", "Difference", "Status", "Reconciled by"],
        rows,
        fmt,
        "RECONCILIATIONS",
        sheet_title="RECON",
        money_cols=(2, 3, 4),
        page="landscape",
    )


@login_required
def cash_short_export(request):
    """Cash short / excess worksheet register (ADR-029/030)."""
    fmt = request.GET.get("format", "xlsx")
    rows = [
        [
            _cycle_label(ws.cycle),
            ws.segment.code if ws.segment else "",
            ws.expected_cash,
            ws.actual_cash,
            ws.variance,
            ws.cause,
            ws.status,
        ]
        for ws in list_cash_shorts(limit=None)
    ]
    return _table_response(
        "CASH SHORT / EXCESS WORKSHEET",
        ["Cycle", "Segment", "Expected", "Actual", "Variance", "Cause", "Status"],
        rows,
        fmt,
        "CASH-SHORT",
        sheet_title="CASH SHORT",
        money_cols=(2, 3, 4),
        page="landscape",
    )


@login_required
def cycles_export(request):
    """Weekly cash cycle register (ADR-013/028)."""
    fmt = request.GET.get("format", "xlsx")
    rows = []
    for c in list_cycles(limit=None):
        rows.append(
            [
                c.cycle_start.isoformat(),
                c.cycle_end.isoformat(),
                c.segment.code,
                c.closing_balance,
                c.status,
                c.reconciled_by.username if c.reconciled_by else "",
                c.notes or "",
            ]
        )
    return _table_response(
        "WEEKLY CASH CYCLES",
        ["Cycle start", "Cycle end", "Segment", "Closing balance", "Status", "Reconciled by", "Notes"],
        rows,
        fmt,
        "CYCLES",
        sheet_title="CYCLES",
        money_cols=(3,),
        page="landscape",
    )


@login_required
def banks_export(request):
    """Bank account / cash-fund master list."""
    fmt = request.GET.get("format", "xlsx")
    rows = [
        [
            b.code,
            b.bank_name,
            b.get_account_type_display(),
            b.account_number or "",
            b.branch or "",
            b.gl_account.code if b.gl_account else "",
            b.company.code,
            "Active" if b.is_active else "Inactive",
        ]
        for b in list_banks()
    ]
    return _table_response(
        "BANKS / CASH FUNDS",
        ["Code", "Bank", "Account type", "Account no.", "Branch", "GL account", "Company", "Status"],
        rows,
        fmt,
        "BANKS",
        sheet_title="BANKS",
        page="landscape",
    )


@login_required
def collections_export(request):
    """Daily Collections JE Summary for a cycle (cashier worksheet columns)."""
    fmt = request.GET.get("format", "xlsx")
    from apps.cash.models import WeeklyCashCycle

    cycles = list(list_cycles())
    cycle = None
    if request.GET.get("cycle"):
        cycle = WeeklyCashCycle.objects.filter(pk=request.GET["cycle"]).first()
    if cycle is None and cycles:
        cycle = cycles[0]
    if cycle is None:
        header = ["DATE", "AR/SI #", "OUTLET'S NAME", "REMARKS"]
        return _table_response(
            "DAILY COLLECTIONS JE SUMMARY",
            header, [], fmt, "DAILY-COLLECTIONS", sheet_title="COLLECTIONS",
            page="landscape",
        )
    ctx = daily_collections(cycle)
    nb = len(ctx["bank_cols"])
    header = [
        "DATE", "AR/SI #", "TR NO", "OUTLET'S NAME", "PARTICULARS", "PO NUMBER",
        "CASH ON HAND (DR)", "CASH ON HAND (CR)",
        *ctx["bank_cols"],
        "AR (DR)", "AR (CR)", "AP (DR)", "AP (CR)",
        "TOTAL COLLECTIONS", "REMARKS",
    ]
    rows = [
        [
            r["date"].isoformat(),
            r["ar_no"],
            r["transaction_no"],
            r["outlet"],
            r["particulars"],
            r["po_number"],
            r["cash_debit"],
            r["cash_credit"],
            *r["bank_amounts"],
            r["ar_debit"],
            r["ar_credit"],
            r["ap_debit"],
            r["ap_credit"],
            r["total"],
            r["remarks"],
        ]
        for r in ctx["rows"]
    ]
    totals = ctx["totals"]
    totals_row = [
        "", "", "", "", "", "",
        totals["cash_debit"], totals["cash_credit"],
        *ctx["bank_totals"],
        totals["ar_debit"], totals["ar_credit"],
        totals["ap_debit"], totals["ap_credit"],
        totals["total"], "",
    ]
    money_cols = list(range(6, 8 + nb)) + list(range(8 + nb, 13 + nb))
    return _table_response(
        f"DAILY COLLECTIONS JE SUMMARY — CYCLE {_cycle_label(cycle)}",
        header, rows, fmt, "DAILY-COLLECTIONS",
        sheet_title="COLLECTIONS", money_cols=tuple(money_cols),
        page="landscape", totals_row=totals_row,
    )


@login_required
def collectibles_export(request):
    """COLLECTIBLES worksheet for a cycle (ADR-029)."""
    fmt = request.GET.get("format", "xlsx")
    from apps.cash.models import CollectiblesWorksheet, WeeklyCashCycle
    from apps.cash.services import CollectiblesService

    cycle = None
    if request.GET.get("cycle"):
        cycle = WeeklyCashCycle.objects.filter(pk=request.GET["cycle"]).first()
    if cycle is None:
        return _table_response(
            "COLLECTIBLES WORKSHEET",
            ["Department", "Client Paid", "Depot Paid", "Gross Mark-Up"],
            [], fmt, "COLLECTIBLES", sheet_title="COLLECTIBLES",
            money_cols=(1, 2, 3),
        )
    try:
        CollectiblesService.generate(cycle)
        rows = [
            [
                w.department,
                w.client_paid,
                w.depot_paid,
                w.gross_markup,
            ]
            for w in CollectiblesWorksheet.objects.filter(cycle=cycle).order_by("department")
        ]
    except AccountingError:
        rows = []
    return _table_response(
        f"COLLECTIBLES WORKSHEET — CYCLE {_cycle_label(cycle)}",
        ["Department", "Client Paid (Collections)", "Depot Paid (Outflows)", "Gross Mark-Up / Net Position"],
        rows, fmt, "COLLECTIBLES", sheet_title="COLLECTIBLES",
        money_cols=(1, 2, 3),
    )


@login_required
def advances_export(request):
    """Advances to employees ledger (ADR-021)."""
    fmt = request.GET.get("format", "xlsx")
    ctx = advances_context()
    rows = [
        [
            r["advance"].employee_name,
            r["kind"],
            r["segment_code"],
            r["advance"].granted_date.isoformat(),
            r["advance"].amount,
            r["advance"].liquidated_amount,
            r["outstanding"],
            r["status_label"],
        ]
        for r in ctx["rows"]
    ]
    return _table_response(
        "ADVANCES TO EMPLOYEES",
        ["Employee", "Kind", "Segment", "Granted", "Amount", "Liquidated", "Outstanding", "Status"],
        rows,
        fmt,
        "ADVANCES",
        sheet_title="ADVANCES",
        money_cols=(4, 5, 6),
        page="landscape",
        totals_row=["", "", "", "", "", "", ctx["total_outstanding"], ""],
    )


@login_required
def conso_list_export(request):
    """CONSO batch register."""
    fmt = request.GET.get("format", "xlsx")
    rows = [
        [
            b.batch_no,
            b.conso_date.isoformat(),
            b.rfps.count(),
            b.total_amount,
            b.status,
        ]
        for b in list_conso(limit=None)
    ]
    return _table_response(
        "CONSO BATCHES",
        ["Batch No", "Date", "Members", "Total", "Status"],
        rows,
        fmt,
        "CONSO-REGISTER",
        sheet_title="CONSO",
        money_cols=(3,),
        page="landscape",
    )


@login_required
def fleet_fuel_export(request):
    """Fleet fuel register (per-log rows honoring the screen's filters)."""
    fmt = request.GET.get("format", "xlsx")
    from apps.fleet.services import fleet_fuel_summary

    rows = [
        [
            log.logged_at.isoformat(),
            log.vehicle.plate_no,
            log.segment.code if log.segment else "",
            log.liters,
            log.cost_amount,
            log.notes or "",
        ]
        for log in fleet_fuel_summary(
            start=request.GET.get("start") or None,
            end=request.GET.get("end") or None,
            segment=request.GET.get("segment") or None,
        )["rows"]
    ]
    return _table_response(
        "FLEET FUEL REGISTER",
        ["Date", "Vehicle", "Segment", "Liters", "Cost", "Notes"],
        rows,
        fmt,
        "FLEET-FUEL",
        sheet_title="FLEET FUEL",
        money_cols=(4,),
        page="landscape",
    )


@login_required
def tax_vat_export(request):
    """VAT extraction at SI level for a period (2550Q prep)."""
    fmt = request.GET.get("format", "xlsx")
    from apps.tax.models import VATComputation
    from apps.tax.services import VATService

    computations = []
    period_start = request.GET.get("period_start")
    period_end = request.GET.get("period_end")
    if period_start and period_end:
        company = Company.objects.first()
        if company:
            computations = VATService.extract_for_period(
                company, date.fromisoformat(period_start), date.fromisoformat(period_end)
            )
    rows = [
        [
            c.invoice.invoice_no,
            c.invoice.transaction_date.isoformat(),
            c.segment.code,
            c.gross_amount,
            c.net_amount,
            c.output_vat,
            "OK" if c.is_balanced else "NOT",
        ]
        for c in computations
    ]
    return _table_response(
        "VAT EXTRACTION (SI LEVEL)",
        ["Invoice", "Date", "Segment", "Gross", "Net", "Output VAT", "Balanced"],
        rows,
        fmt,
        "VAT",
        sheet_title="VAT",
        money_cols=(3, 4, 5),
        page="landscape",
    )


@login_required
def tax_wht_export(request):
    """Withholding certificates (2307 / 2306) from posted CVs."""
    fmt = request.GET.get("format", "xlsx")
    from apps.tax.services import WithholdingService

    cert_type = request.GET.get("cert_type", "2307")
    period_start = request.GET.get("period_start") or None
    period_end = request.GET.get("period_end") or None
    rows = [
        [
            r["cv_number"],
            r["payee"].name,
            r["tin"] or "",
            r["segment"].code,
            r["gross_amount"],
            r["tax_amount"],
        ]
        for r in WithholdingService.build_certificates(
            cert_type=cert_type,
            period_start=date.fromisoformat(period_start) if period_start else None,
            period_end=date.fromisoformat(period_end) if period_end else None,
        )
    ]
    return _table_response(
        f"WITHHOLDING CERTIFICATES ({cert_type})",
        ["CV No", "Payee", "TIN", "Segment", "Gross", "Tax Withheld"],
        rows,
        fmt,
        f"WHT-{cert_type}",
        sheet_title="WHT",
        money_cols=(4, 5),
        page="landscape",
    )


@login_required
def tax_provision_export(request):
    """Income tax provisions booked (dashboard table)."""
    fmt = request.GET.get("format", "xlsx")
    from apps.tax.models import IncomeTaxProvision

    rows = [
        [
            p.segment.code,
            p.filing_period,
            p.taxable_income,
            f"{p.tax_rate:.4f}",
            p.tax_amount,
            p.journal_entry.entry_no if p.journal_entry else "",
        ]
        for p in IncomeTaxProvision.objects.select_related("segment", "journal_entry").order_by("-filing_period")
    ]
    return _table_response(
        "INCOME TAX PROVISIONS",
        ["Segment", "Period", "Taxable income", "Rate", "Tax", "Reference"],
        rows,
        fmt,
        "TAX-PROVISION",
        sheet_title="TAX PROVISION",
        money_cols=(2, 4),
        page="landscape",
    )


@login_required
def tax_calendar_export(request):
    """Tax filing calendar register."""
    fmt = request.GET.get("format", "xlsx")
    from apps.tax.models import TaxCalendar

    company = Company.objects.first()
    qs = TaxCalendar.objects.filter(company=company).order_by("due_date", "form") if company else TaxCalendar.objects.none()
    rows = [
        [
            c.form,
            c.filing_period,
            c.due_date.isoformat(),
            c.amount_due,
            c.status,
            c.filed_date.isoformat() if c.filed_date else "",
            c.paid_date.isoformat() if c.paid_date else "",
        ]
        for c in qs
    ]
    return _table_response(
        "TAX FILING CALENDAR",
        ["Form", "Period", "Due date", "Amount", "Status", "Filed", "Paid"],
        rows,
        fmt,
        "TAX-CALENDAR",
        sheet_title="TAX CALENDAR",
        money_cols=(3,),
        page="landscape",
    )


@login_required
def month_end_close_export(request):
    """Month-end close status: step checklist + posted closing entries."""
    fmt = request.GET.get("format", "xlsx")
    close = month_end_close_context()
    rows = []
    if close is None:
        rows = [["No open fiscal period found", ""]]
    else:
        fp = close.fiscal_period
        rows.append(["Period", f"{fp.period_no} — {fp.start_date} to {fp.end_date}"])
        rows.append(["Status", close.status])
        for step, state in close.steps.items():
            rows.append([f"Step: {step}", state])
        if close.revenue_close_entry:
            rows.append(["Revenue close", f"{close.revenue_close_entry.entry_no} ({close.revenue_close_entry.status})"])
        if close.expense_close_entry:
            rows.append(["Expense close", f"{close.expense_close_entry.entry_no} ({close.expense_close_entry.status})"])
        if close.appropriation_entry:
            rows.append(["Appropriation", f"{close.appropriation_entry.entry_no} ({close.appropriation_entry.status})"])
    return _table_response(
        "MONTH-END CLOSE STATUS",
        ["Item", "Value"],
        rows,
        fmt,
        "MONTH-END-CLOSE",
        sheet_title="MONTH-END CLOSE",
    )
