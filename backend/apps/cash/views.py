from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.reporting.excel_export import build_cash_flow_statement, xlsx_response

from .models import (
    BankAccount,
    BankReconciliation,
    BankReconLine,
    CashFlowStatement,
    CashShortExcessWorksheet,
    CheckDisbursement,
    CollectiblesWorksheet,
    InterAccountTransfer,
    PCFReplenishment,
    PettyCashFund,
    WeeklyCashCycle,
)
from .serializers import (
    BankAccountSerializer,
    BankReconciliationSerializer,
    BankReconLineSerializer,
    CashFlowStatementSerializer,
    CashShortExcessWorksheetSerializer,
    CheckDisbursementSerializer,
    CollectiblesWorksheetSerializer,
    InterAccountTransferSerializer,
    PCFReplenishmentSerializer,
    PettyCashFundSerializer,
    WeeklyCashCycleSerializer,
)
from .services import (
    BankReconService,
    CashCycleService,
    CashFlowService,
    CashShortService,
    CheckDisbursementService,
    CollectiblesService,
    PCFService,
    TransferService,
)


class BankAccountViewSet(viewsets.ModelViewSet):
    queryset = BankAccount.objects
    serializer_class = BankAccountSerializer
    filterset_fields = ["account_type", "company", "is_active"]
    search_fields = ["code", "name", "bank_name"]


class WeeklyCashCycleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WeeklyCashCycle.objects
    serializer_class = WeeklyCashCycleSerializer
    filterset_fields = ["segment", "status"]
    ordering = ["-cycle_start"]

    @action(detail=False, methods=["post"])
    def generate(self, request):
        """POST /cash/cycles/generate/ with {segment_id, start_date, end_date}"""
        segment_id = request.data.get("segment_id")
        start = request.data.get("start_date")
        end = request.data.get("end_date")
        from apps.foundation.models import Segment
        segment = Segment.objects.get(pk=segment_id)
        cycles = CashCycleService.generate_range(segment, start, end)
        out = self.get_serializer(cycles, many=True)
        return Response(out.data, status=status.HTTP_201_CREATED)


class PettyCashFundViewSet(viewsets.ModelViewSet):
    queryset = PettyCashFund.objects
    serializer_class = PettyCashFundSerializer
    filterset_fields = ["fund_code", "is_active"]

    @action(detail=True, methods=["post"])
    def replenish(self, request, pk=None):
        fund = self.get_object()
        expenses = request.data.get("expenses", [])
        replen = PCFService.request_replenishment(fund, expenses, user=request.user)
        out = PCFReplenishmentSerializer(replen)
        return Response(out.data, status=status.HTTP_201_CREATED)


class PCFReplenishmentViewSet(viewsets.ModelViewSet):
    """PCV lifecycle (mirrors the RFP API): ``replenish`` creates a DRAFT, the
    custodian submits it (``draft -> requested``, the Head-queue gateway), and
    edits/deletes are allowed only by the preparer while the voucher is still
    a draft. Approval/rejection stay head-only service calls."""

    queryset = PCFReplenishment.objects.select_related("fund", "cv")
    serializer_class = PCFReplenishmentSerializer
    filterset_fields = ["fund", "status"]

    @staticmethod
    def _is_preparer(request, replen):
        return (
            request.user.is_superuser
            or replen.fund.custodian_id == request.user.id
            or (replen.requested_by_id and replen.requested_by_id == request.user.id)
        )

    def _assert_can_edit(self, replen):
        """Draft + preparer only (the fund's custodian counts as preparer-side
        even when a colleague drafted it) — after it leaves the desk changes
        go through the reject/revise cycle (same contract as the RFP viewset)."""
        from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied

        if replen.status != "draft":
            raise DRFPermissionDenied("Only draft vouchers can be edited.")
        if not self._is_preparer(self.request, replen):
            raise DRFPermissionDenied(
                "Only the preparer or the fund's custodian may edit this voucher."
            )

    def update(self, request, *args, **kwargs):
        self._assert_can_edit(self.get_object())
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        self._assert_can_edit(self.get_object())
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self._assert_can_edit(self.get_object())
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        """draft -> requested (the custodian sends it to the Head)."""
        replen = self.get_object()
        replen = PCFService.submit_replenishment(replen, user=request.user)
        return Response(self.get_serializer(replen).data)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        replen = self.get_object()
        replen = PCFService.post_replenishment(replen, user=request.user)
        out = self.get_serializer(replen)
        return Response(out.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """requested -> approved (head only; auto-batches to CONSO)."""
        from apps.core.approvals import require_approval_role

        require_approval_role(request.user, "head")
        replen = self.get_object()
        replen = PCFService.approve_replenishment(replen, user=request.user)
        return Response(self.get_serializer(replen).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """requested -> rejected (head only, note required)."""
        from apps.core.approvals import require_approval_role

        require_approval_role(request.user, "head")
        replen = self.get_object()
        replen = PCFService.reject_replenishment(
            replen, user=request.user, note=request.data.get("note", "")
        )
        return Response(self.get_serializer(replen).data)

    @action(detail=True, methods=["post"])
    def revise(self, request, pk=None):
        """rejected -> requested: reopen for the custodian to edit/resubmit.

        Accepts the same header fields as the UI revise form (payee_name,
        reference, request_date, fund, expenses) so a changed NAME persists
        through the API path too; omitted fields keep their stored values.
        """
        from datetime import date as _date

        replen = self.get_object()
        kwargs = {}
        if "payee_name" in request.data:
            kwargs["payee_name"] = request.data.get("payee_name") or ""
        if "reference" in request.data:
            kwargs["reference"] = request.data.get("reference") or ""
        if request.data.get("request_date"):
            kwargs["request_date"] = _date.fromisoformat(request.data.get("request_date"))
        if request.data.get("fund"):
            kwargs["fund"] = PettyCashFund.objects.get(pk=request.data.get("fund"))
        if "expenses" in request.data and request.data.get("expenses") is not None:
            kwargs["expenses"] = request.data.get("expenses")
        replen = PCFService.revise_replenishment(replen, user=request.user, **kwargs)
        return Response(self.get_serializer(replen).data)


class InterAccountTransferViewSet(viewsets.ModelViewSet):
    queryset = InterAccountTransfer.objects
    serializer_class = InterAccountTransferSerializer
    filterset_fields = ["from_account", "to_account", "status"]
    permission_classes = []

    def create(self, request, *args, **kwargs):
        from_account = request.data.get("from_account")
        to_account = request.data.get("to_account")
        amount = request.data.get("amount")
        purpose = request.data.get("purpose")
        from apps.cash.models import BankAccount
        from_acc = BankAccount.objects.get(pk=from_account)
        to_acc = BankAccount.objects.get(pk=to_account)
        tr = TransferService.transfer(
            from_account=from_acc, to_account=to_acc,
            amount=amount, purpose=purpose,
            reference=request.data.get("reference", ""),
            check_no=request.data.get("check_no", ""),
            cost_center=request.data.get("cost_center", ""), user=request.user,
        )
        # The transfer is created with status ``requested``, then submitted by
        # the preparer; the JE is posted when the head approves it.
        out = self.get_serializer(tr)
        return Response(out.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        """requested/rejected -> submitted (preparer sends it to the head)."""
        from apps.cash.services import TransferService

        transfer = self.get_object()
        TransferService.submit(transfer, user=request.user)
        return Response(self.get_serializer(transfer).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """submitted -> approved (finance head only; posts the JE to the GL).

        Same gate as RFP/JE/CV approval: only the head may approve, and every
        transfer — whatever the amount — posts to the GL here.
        """
        from apps.core.approvals import require_approval_role

        require_approval_role(request.user, "head")
        transfer = self.get_object()
        from apps.cash.services import TransferService
        TransferService.approve(transfer, user=request.user)
        # Re-serialize so the client sees the approved status.
        out = self.get_serializer(transfer)
        return Response(out.data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """submitted -> rejected (finance head, note required)."""
        from apps.core.approvals import require_approval_role

        require_approval_role(request.user, "head")
        transfer = self.get_object()
        from apps.cash.services import TransferService
        TransferService.reject(
            transfer, user=request.user, note=request.data.get("note", "")
        )
        return Response(self.get_serializer(transfer).data)


class CashFlowStatementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CashFlowStatement.objects
    serializer_class = CashFlowStatementSerializer
    ordering = ["-period_end"]

    @action(detail=False, methods=["post"])
    def generate(self, request):
        period_start = request.data.get("period_start")
        period_end = request.data.get("period_end")
        company_id = request.data.get("company")
        from apps.foundation.models import Company
        company = Company.objects.get(pk=company_id)
        cf = CashFlowService.generate(period_start, period_end, company)
        out = self.get_serializer(cf)
        return Response(out.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        """GET /api/cash/cash-flow/export/?company=&period_start=&period_end=
        — workbook mirroring the CF sheet of STATEMENT-OF-CASH-FLOW.xlsx."""
        from datetime import date

        from apps.foundation.models import Company

        company = Company.objects.get(pk=request.query_params.get("company"))
        period_start = date.fromisoformat(request.query_params.get("period_start"))
        period_end = date.fromisoformat(request.query_params.get("period_end"))
        wb = build_cash_flow_statement(company, period_start, period_end)
        return xlsx_response(
            wb, f"STATEMENT-OF-CASH-FLOW-{period_start:%Y%m%d}-{period_end:%Y%m%d}.xlsx"
        )


class BankReconciliationViewSet(viewsets.ModelViewSet):
    queryset = BankReconciliation.objects.prefetch_related("lines")
    serializer_class = BankReconciliationSerializer
    filterset_fields = ["cycle", "bank_account", "status", "frequency", "period_start", "period_end"]

    def create(self, request, *args, **kwargs):
        from apps.cash.models import WeeklyCashCycle, BankAccount
        cycle = WeeklyCashCycle.objects.get(pk=request.data.get("cycle"))
        bank = BankAccount.objects.get(pk=request.data.get("bank_account"))
        recon = BankReconService.reconcile(
            cycle=cycle, bank_account=bank,
            bank_statement_balance=request.data.get("bank_statement_balance"),
            user=request.user,
        )
        out = self.get_serializer(recon)
        return Response(out.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="create-monthly")
    def create_monthly(self, request):
        """POST /cash/reconciliations/create-monthly/ with
        {segment_id, bank_account_id, year, month} — idempotent."""
        from apps.cash.models import BankAccount
        from apps.foundation.models import Segment

        segment = Segment.objects.get(pk=request.data.get("segment_id"))
        bank = BankAccount.objects.get(pk=request.data.get("bank_account_id"))
        recon = BankReconService.create_monthly_reconciliation(
            segment=segment, bank_account=bank,
            year=int(request.data.get("year")), month=int(request.data.get("month")),
            user=request.user,
        )
        return Response(self.get_serializer(recon).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="capture-balances")
    def capture_balances(self, request, pk=None):
        """Capture unadjusted balances ONCE (locks the snapshot)."""
        recon = BankReconService.capture_balances(
            self.get_object(),
            bank_statement_balance=request.data.get("bank_statement_balance"),
            user=request.user,
        )
        return Response(self.get_serializer(recon).data)

    @action(detail=True, methods=["post"])
    def compute(self, request, pk=None):
        recon = BankReconService.compute_adjusted_balances(self.get_object())
        return Response(self.get_serializer(recon).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        """draft/open -> submitted (preparer sends it for review)."""
        recon = BankReconService.submit(self.get_object(), user=request.user)
        return Response(self.get_serializer(recon).data)

    @action(detail=True, methods=["post"], url_path="pre-approve")
    def pre_approve(self, request, pk=None):
        """submitted -> pre_approved (head only; temporary pre-approval)."""
        from apps.core.approvals import require_approval_role

        require_approval_role(request.user, "head")
        recon = BankReconService.pre_approve(self.get_object(), user=request.user)
        return Response(self.get_serializer(recon).data)

    @action(detail=True, methods=["post"], url_path="final-approve")
    def final_approve(self, request, pk=None):
        """pre_approved -> approved (head only; locks the statement)."""
        from apps.core.approvals import require_approval_role

        require_approval_role(request.user, "head")
        recon = BankReconService.final_approve(self.get_object(), user=request.user)
        return Response(self.get_serializer(recon).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """submitted/pre_approved -> draft (head only, note required)."""
        from apps.core.approvals import require_approval_role

        require_approval_role(request.user, "head")
        recon = BankReconService.reject(
            self.get_object(), user=request.user, note=request.data.get("note", "")
        )
        return Response(self.get_serializer(recon).data)

    @action(detail=True, methods=["get"], url_path="export-excel")
    def export_excel(self, request, pk=None):
        """GET single-bank statement workbook (unified template)."""
        from apps.reporting.excel_export import build_bank_reconciliation_statement, xlsx_response

        recon = self.get_object()
        wb = build_bank_reconciliation_statement(recon)
        code = recon.bank_account.code
        return xlsx_response(
            wb, f"BANK-RECON-{code}-{recon.period_start:%Y%m%d}-{recon.period_end:%Y%m%d}.xlsx"
        )

    @action(detail=True, methods=["get"], url_path="export-pdf")
    def export_pdf(self, request, pk=None):
        """GET single-bank statement PDF (same template as Excel)."""
        from apps.reporting.recon_export import bank_recon_pdf_response

        return bank_recon_pdf_response(self.get_object())

    @action(detail=False, methods=["get"], url_path="consolidated/export-excel")
    def consolidated_excel(self, request):
        """GET ?company=&period_start=&period_end= — all banks workbook."""
        from datetime import date

        from apps.foundation.models import Company
        from apps.reporting.excel_export import build_consolidated_bank_reconciliation, xlsx_response

        company = Company.objects.get(pk=request.query_params.get("company"))
        period_start = date.fromisoformat(request.query_params.get("period_start"))
        period_end = date.fromisoformat(request.query_params.get("period_end"))
        wb = build_consolidated_bank_reconciliation(company, period_start, period_end)
        return xlsx_response(
            wb, f"BANK-RECON-CONSO-{period_start:%Y%m%d}-{period_end:%Y%m%d}.xlsx"
        )

    @action(detail=False, methods=["get"], url_path="consolidated/export-pdf")
    def consolidated_pdf(self, request):
        """GET ?company=&period_start=&period_end= — all banks PDF."""
        from datetime import date

        from apps.foundation.models import Company
        from apps.reporting.recon_export import consolidated_recon_pdf_response

        company = Company.objects.get(pk=request.query_params.get("company"))
        period_start = date.fromisoformat(request.query_params.get("period_start"))
        period_end = date.fromisoformat(request.query_params.get("period_end"))
        return consolidated_recon_pdf_response(company, period_start, period_end)


class BankReconLineViewSet(viewsets.ModelViewSet):
    """Statement lines: create/update/delete recompute adjusted balances."""

    queryset = BankReconLine.objects.select_related("recon")
    serializer_class = BankReconLineSerializer
    filterset_fields = ["recon", "side", "category", "match_status"]

    def create(self, request, *args, **kwargs):
        recon = BankReconciliation.objects.get(pk=request.data.get("recon"))
        line = BankReconService.add_line(
            recon,
            side=request.data.get("side"),
            category=request.data.get("category"),
            amount=request.data.get("amount"),
            reference=request.data.get("reference", ""),
            description=request.data.get("description", ""),
            user=request.user,
        )
        return Response(self.get_serializer(line).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        line = BankReconService.update_line(self.get_object(), **request.data)
        return Response(self.get_serializer(line).data)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        BankReconService.delete_line(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


class CheckDisbursementViewSet(viewsets.ModelViewSet):
    queryset = CheckDisbursement.objects
    serializer_class = CheckDisbursementSerializer
    filterset_fields = ["status", "cv"]

    @action(detail=True, methods=["post"])
    def sign(self, request, pk=None):
        disb = self.get_object()
        CheckDisbursementService.sign_cnr(disb.cv, request.user)
        out = self.get_serializer(disb)
        return Response(out.data)

    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        disb = self.get_object()
        CheckDisbursementService.release_quibs(disb.cv, request.user)
        out = self.get_serializer(disb)
        return Response(out.data)

    @action(detail=True, methods=["post"])
    def clear(self, request, pk=None):
        disb = self.get_object()
        from apps.cash.models import BankAccount
        bank = BankAccount.objects.get(pk=request.data.get("bank_account"))
        CheckDisbursementService.clear(disb.cv, bank, request.user)
        out = self.get_serializer(disb)
        return Response(out.data)


class CollectiblesViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CollectiblesWorksheet.objects
    serializer_class = CollectiblesWorksheetSerializer
    filterset_fields = ["cycle", "department"]

    @action(detail=False, methods=["post"])
    def generate(self, request):
        """POST /cash/collectibles/generate/ with {cycle_id} — regenerates both
        department rows from the cycle's posted activities (ADR-029)."""
        from apps.cash.models import WeeklyCashCycle

        cycle = WeeklyCashCycle.objects.get(pk=request.data.get("cycle_id"))
        rows = CollectiblesService.generate(cycle)
        out = self.get_serializer(rows, many=True)
        return Response(out.data, status=status.HTTP_201_CREATED)


class CashShortExcessViewSet(viewsets.ModelViewSet):
    queryset = CashShortExcessWorksheet.objects
    serializer_class = CashShortExcessWorksheetSerializer
    filterset_fields = ["cycle", "segment", "status"]

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        ws = self.get_object()
        CashShortService.approve(ws, request.user)
        out = self.get_serializer(ws)
        return Response(out.data)