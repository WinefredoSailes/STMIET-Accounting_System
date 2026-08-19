"""Server-rendered UI views (Django templates + HTMX).

Every screen here is a thin HTML layer over the bounded-context services —
no business logic lives in this app (ADR-009). Forms post to the same
service functions the DRF API uses, so the UI and the API can never drift.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponseRedirect, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.exceptions import AccountingError, ValidationError
from apps.core.money import approve_threshold, money
from apps.foundation.models import Account, AccountType, Company, FiscalPeriod, Segment
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
    bank_accounts,
    book_balance,
    cash_accounts,
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
    pcf_gl_candidates,
    rfp_summary,
    rfp_timeline,
    transfers_context,
    unassigned_approved_rfps,
)

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
    entry = get_object_or_404(JournalEntry.objects.prefetch_related("lines__account"), pk=pk)
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
        "accounts": Account.objects.filter(is_postable=True).order_by("code"),
        "today": date.today(),
    }
    return render(request, "ui/posting/je_form.html", ctx)


def _create_entry_from_form(request):
    """Build a draft JE from the form POST (lines as parallel arrays)."""
    company = Company.objects.get(pk=request.POST["company"])
    segment = Segment.objects.get(pk=request.POST["segment"])
    transaction_date = date.fromisoformat(request.POST["transaction_date"])
    description = request.POST["description"].strip()
    source_doc_type = request.POST.get("source_doc_type", "")
    source_doc_no = request.POST.get("source_doc_no", "")

    period = (
        FiscalPeriod.objects.filter(
            start_date__lte=transaction_date, end_date__gte=transaction_date
        ).first()
    )

    with transaction.atomic():
        entry = JournalEntry.objects.create(
            entry_no=DocumentSequence.next_number(
                company=company, form_code="JE", year=transaction_date.year
            ),
            company=company,
            segment=segment,
            fiscal_period=period,
            transaction_date=transaction_date,
            status=PostingStatus.DRAFT,
            description=description,
            source_doc_type=source_doc_type,
            source_doc_no=source_doc_no,
            created_by=request.user,
        )
        accounts = request.POST.getlist("account")
        debits = request.POST.getlist("debit")
        credits = request.POST.getlist("credit")
        descs = request.POST.getlist("line_description")
        for i, account_id in enumerate(accounts):
            if not account_id:
                continue
            debit = money(debits[i] or 0)
            credit = money(credits[i] or 0)
            if not debit and not credit:
                continue
            account = Account.objects.filter(pk=account_id).first()
            if account is None:
                raise ValueError("Unknown account in line.")
            JournalEntryLine.objects.create(
                entry=entry,
                line_no=i + 1,
                account=account,
                description=descs[i] if i < len(descs) else "",
                debit=debit,
                credit=credit,
            )
        if not entry.lines.exists():
            raise ValueError("Add at least one line with an amount.")
        entry.recalc_totals()
    return entry


@login_required
@require_POST
def je_post(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk)
    approve = "approve" in request.POST
    try:
        if approve:
            entry.status = PostingStatus.APPROVED
            entry.save(update_fields=["status", "updated_at"])
        posted = PostingService.post(entry, approver=request.user)
        messages.success(request, f"Entry {posted.entry_no} posted.")
    except AccountingError as exc:
        messages.error(request, str(exc))
    return redirect("ui:je_detail", pk=pk)


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
    """Download TRIAL-BALANCE.xlsx mirror (year-wise monthly Dr/Cr pairs)."""
    from apps.reporting.excel_export import build_trial_balance, xlsx_response

    company = Company.objects.first()
    year = int(request.GET.get("year") or date.today().year)
    return xlsx_response(build_trial_balance(company, year), f"TRIAL-BALANCE-{year}.xlsx")


@login_required
def statement_export(request, statement_type):
    """Download the statement workbook (sfp/soce/cos/te) for a period."""
    from apps.reporting.excel_export import (
        build_statement_of_changes_in_equity,
        build_statement_of_cost_of_sales,
        build_statement_of_financial_position,
        build_statement_of_total_expenses,
        xlsx_response,
    )

    builders = {
        "sfp": ("STATEMENT-OF-FINANCIAL-POSITION", build_statement_of_financial_position),
        "soce": ("STATEMENT-OF-CHANGES-IN-EQUITY", build_statement_of_changes_in_equity),
        "cos": ("STATEMENT-OF-COST-OF-SALES", build_statement_of_cost_of_sales),
        "te": ("STATEMENT-OF-TOTAL-EXPENSES", build_statement_of_total_expenses),
    }
    if statement_type not in builders:
        raise Http404
    company = Company.objects.first()
    period_start = date.fromisoformat(request.GET.get("period_start"))
    period_end = date.fromisoformat(request.GET.get("period_end"))
    from apps.reporting.services import StatementTemplateService

    StatementTemplateService.seed_defaults()
    if statement_type in ("cos", "te"):
        wb = builders[statement_type][1](company, period_start, period_end)
    else:
        wb = builders[statement_type][1](
            company, period_start, period_end, request.GET.get("net_profit")
        )
    stem = builders[statement_type][0]
    return xlsx_response(wb, f"{stem}-{period_start:%Y%m%d}-{period_end:%Y%m%d}.xlsx")


@login_required
def cash_flow_export(request):
    """Download STATEMENT-OF-CASH-FLOW.xlsx CF mirror for a cycle period."""
    from apps.reporting.excel_export import build_cash_flow_statement, xlsx_response

    seg = Segment.objects.get(pk=request.GET.get("segment"))
    period_start = date.fromisoformat(request.GET.get("period_start"))
    period_end = date.fromisoformat(request.GET.get("period_end"))
    wb = build_cash_flow_statement(seg, period_start, period_end)
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


@login_required
def rfp_list(request):
    return render(
        request,
        "ui/ap/rfp_list.html",
        {"page_obj": _page(request, list_rfps(limit=None)), "summary": rfp_summary()},
    )


@login_required
def bank_list(request):
    return render(request, "ui/cash/bank_list.html", {"page_obj": _page(request, list_banks())})


@login_required
def cycle_list(request):
    return render(request, "ui/cash/cycle_list.html", {"page_obj": _page(request, list_cycles(limit=None))})


@login_required
def asset_list(request):
    return render(request, "ui/assets/asset_list.html", {"page_obj": _page(request, list_assets(limit=None))})


# ---------------------------------------------------------------------------
# AR — customer master + acknowledgment receipts (ACCTG-FOR-005)
# ---------------------------------------------------------------------------


@login_required
def customer_create(request):
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
                notes=request.POST.get("notes", ""),
            )
            messages.success(request, "Customer created.")
            return redirect("ui:customer_list")
        except (IntegrityError, ValueError, ObjectDoesNotExist) as exc:
            messages.error(request, str(exc))
    return render(request, "ui/ar/customer_form.html", {"segments": Segment.objects.order_by("code")})


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
            "cash_accounts": cash_accounts(),
            "today": date.today(),
        },
    )


# ---------------------------------------------------------------------------
# AP — supplier master + RFP document (ACCTG-FOR-012)
# ---------------------------------------------------------------------------


@login_required
def supplier_create(request):
    if request.method == "POST":
        try:
            from apps.ap.models import Supplier

            segment = request.POST.get("default_segment")
            Supplier.objects.create(
                code=request.POST["code"].strip(),
                name=request.POST["name"].strip(),
                supplier_type=request.POST["supplier_type"],
                tin=request.POST.get("tin", ""),
                address=request.POST.get("address", ""),
                contact_no=request.POST.get("contact_no", ""),
                default_segment=Segment.objects.get(pk=segment) if segment else None,
            )
            messages.success(request, "Supplier created.")
            return redirect("ui:supplier_list")
        except (IntegrityError, ValueError, ObjectDoesNotExist) as exc:
            messages.error(request, str(exc))
    return render(request, "ui/ap/supplier_form.html", {"segments": Segment.objects.order_by("code")})


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
            lines = []
            seg_ids = request.POST.getlist("line_segment")
            codes = request.POST.getlist("line_account")
            amounts = request.POST.getlist("line_amount")
            descs = request.POST.getlist("line_description")
            for i, seg_id in enumerate(seg_ids):
                if not seg_id or not codes[i]:
                    continue
                lines.append(
                    {
                        "segment": Segment.objects.get(pk=seg_id),
                        "account_code": codes[i],
                        "amount": amounts[i] or 0,
                        "description": descs[i] if i < len(descs) else "",
                    }
                )
            if not lines:
                raise ValueError("Add at least one charge line.")
            rfp = RFPService.create_rfp(
                ap_number=ap_number,
                rfp_date=date.fromisoformat(rfp_date),
                payee=payee,
                particulars=request.POST["particulars"].strip(),
                amount=request.POST["amount"],
                segment=segment,
                purpose=request.POST.get("purpose", ""),
                advance_amount=request.POST.get("advance_amount") or "20000.00",
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
            "suppliers": list_suppliers(),
            "segments": Segment.objects.order_by("code"),
            "accounts": Account.objects.filter(is_postable=True).order_by("code"),
        },
    )


@login_required
def rfp_detail(request, pk):
    from apps.ap.models import RFPDocument

    rfp = get_object_or_404(
        RFPDocument.objects.prefetch_related("lines__account", "lines__segment"), pk=pk
    )
    return render(request, "ui/ap/rfp_detail.html", {"rfp": rfp, "timeline": rfp_timeline(rfp)})


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
        messages.success(request, f"RFP {rfp.ap_number} submitted.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("ui:rfp_detail", pk=pk)


@login_required
@require_POST
def rfp_approve(request, pk):
    from apps.ap.models import RFPDocument
    from apps.ap.services import RFPService

    rfp = get_object_or_404(RFPDocument, pk=pk)
    next_roles = {"prepared": "checked", "submitted": "checked", "checked": "acctg_approved", "acctg_approved": "fin_approved"}
    role = next_roles.get(rfp.status)
    try:
        if not role:
            raise ValueError(f"No approval step available from status '{rfp.status}'.")
        rfp = RFPService.advance_step(rfp, role=role, user=request.user)
        messages.success(request, f"RFP {rfp.ap_number} approved at '{role}'.")
    except (AccountingError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("ui:rfp_detail", pk=pk)


@login_required
@require_POST
def rfp_approve_cnr(request, pk):
    from apps.ap.models import RFPDocument
    from apps.ap.services import RFPService

    rfp = get_object_or_404(RFPDocument, pk=pk)
    try:
        rfp = RFPService.approve_cnr(rfp, user=request.user)
        messages.success(request, f"RFP {rfp.ap_number} approved by CNR.")
    except AccountingError as exc:
        messages.error(request, str(exc))
    return redirect("ui:rfp_detail", pk=pk)


# ---------------------------------------------------------------------------
# Cash — bank master + weekly cycle generation
# ---------------------------------------------------------------------------


@login_required
def bank_create(request):
    if request.method == "POST":
        try:
            from apps.cash.models import BankAccount

            BankAccount.objects.create(
                code=request.POST["code"].strip(),
                name=request.POST["name"].strip(),
                account_type=request.POST["account_type"],
                bank_name=request.POST.get("bank_name", ""),
                bank_code=request.POST.get("bank_code", ""),
                gl_account=Account.objects.get(pk=request.POST["gl_account"]),
                segment=Segment.objects.get(pk=request.POST["segment"]),
                adb_required=money(request.POST.get("adb_required") or 0),
            )
            messages.success(request, "Bank account created.")
            return redirect("ui:bank_list")
        except (IntegrityError, ValueError, ObjectDoesNotExist) as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "ui/cash/bank_form.html",
        {
            "segments": Segment.objects.order_by("code"),
            "accounts": Account.objects.filter(is_postable=True).order_by("code"),
        },
    )


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
        {
            "asset": asset,
            "cash_accounts": cash_accounts(),
        },
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
    return render(
        request,
        "ui/ap/cv_form.html",
        {
            "rfps": approved_rfps(),
            "bank_accounts": bank_accounts(),
            "today": date.today(),
        },
    )


@login_required
def cv_detail(request, pk):
    from apps.ap.models import CheckVoucher

    cv = get_object_or_404(
        CheckVoucher.objects.select_related("payee", "bank_account", "rfp"),
        pk=pk,
    )
    if cv.rfp_id:
        list(cv.rfp.lines.select_related("account", "segment"))
    return render(request, "ui/ap/cv_detail.html", {"cv": cv})


@login_required
@require_POST
def cv_sign(request, pk):
    """created -> signed (CNR signs the check)."""
    from apps.ap.models import CheckVoucher

    cv = get_object_or_404(CheckVoucher, pk=pk)
    if cv.status == "created":
        cv.status = "signed"
        cv.signed_by = request.user
        cv.save(update_fields=["status", "signed_by", "updated_at"])
        messages.success(request, f"CV {cv.cv_number} signed.")
    else:
        messages.error(request, f"CV cannot be signed from status '{cv.status}'.")
    return redirect("ui:cv_detail", pk=pk)


@login_required
@require_POST
def cv_release(request, pk):
    """signed -> released (treasury releases the check)."""
    from apps.ap.models import CheckVoucher

    cv = get_object_or_404(CheckVoucher, pk=pk)
    if cv.status == "signed":
        cv.status = "released"
        cv.released_by = request.user
        cv.save(update_fields=["status", "released_by", "updated_at"])
        messages.success(request, f"CV {cv.cv_number} released.")
    else:
        messages.error(request, f"CV cannot be released from status '{cv.status}'.")
    return redirect("ui:cv_detail", pk=pk)


@login_required
@require_POST
def cv_clear(request, pk):
    """released -> cleared (check encashed)."""
    from apps.ap.models import CheckVoucher

    cv = get_object_or_404(CheckVoucher, pk=pk)
    if cv.status == "released":
        cv.status = "cleared"
        cv.save(update_fields=["status", "updated_at"])
        messages.success(request, f"CV {cv.cv_number} cleared.")
    else:
        messages.error(request, f"CV cannot be cleared from status '{cv.status}'.")
    return redirect("ui:cv_detail", pk=pk)


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
            amounts = request.POST.getlist("exp_amount")
            descs = request.POST.getlist("exp_description")
            cost_centers = request.POST.getlist("exp_cost_center")
            for i, acc_id in enumerate(accounts):
                if not acc_id:
                    continue
                expenses.append(
                    {
                        "account_code": Account.objects.get(pk=acc_id).code,
                        "amount": amounts[i] or 0,
                        "description": descs[i] if i < len(descs) else "",
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
            if request.POST.get("request_date"):
                replen.request_date = date.fromisoformat(request.POST["request_date"])
            replen.save(update_fields=["payee_name", "reference", "request_date", "updated_at"])
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
        PCFReplenishment.objects.select_related("fund__custodian", "fund__segment"),
        pk=pk,
    )
    return render(request, "ui/cash/pcf_replenishment_detail.html", {"replen": replen})


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
def pcf_create(request):
    from apps.cash.models import PettyCashFund

    if request.method == "POST":
        try:
            PettyCashFund.objects.create(
                fund_code=request.POST["fund_code"],
                name=request.POST["name"].strip(),
                custodian=get_user_model().objects.get(pk=request.POST["custodian"]),
                imprest_amount=money(request.POST.get("imprest_amount") or 0),
                gl_account=Account.objects.get(pk=request.POST["gl_account"]),
                segment=Segment.objects.get(pk=request.POST["segment"]),
            )
            messages.success(request, "Petty cash fund created.")
            return redirect("ui:pcf_list")
        except (IntegrityError, ValueError, ObjectDoesNotExist) as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "ui/cash/pcf_form.html",
        {
            "segments": Segment.objects.order_by("code"),
            "accounts": pcf_gl_candidates(),
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
    try:
        CashShortService.approve(ws, request.user)
        messages.success(request, "Variance approved.")
    except AccountingError as exc:
        messages.error(request, str(exc))
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
    return render(request, "ui/foundation/coa_list.html", ctx)


# ---------------------------------------------------------------------------
# Cash flow statement
# ---------------------------------------------------------------------------


@login_required
def cash_flow(request):
    """Cash Flow Statement (ADR-031) — generates on GET with period + segment."""
    from apps.cash.models import CashFlowStatement
    from apps.cash.services import CashFlowService

    seg = Segment.objects.filter(pk=request.GET.get("segment")).first()
    latest = CashFlowStatement.objects.order_by("-period_end").first()
    if seg and request.GET.get("period_start"):
        try:
            latest = CashFlowService.generate(
                period_start=date.fromisoformat(request.GET["period_start"]),
                period_end=date.fromisoformat(request.GET["period_end"]),
                segment=seg,
            )
            messages.success(request, f"Cash flow generated for {seg.code}.")
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
    ctx.update({"seg": seg, "latest": latest, "nets": nets})
    return render(request, "ui/cash/cash_flow.html", ctx)


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
