from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import (
    BankAccount,
    BankReconciliation,
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
    filterset_fields = ["account_type", "segment", "is_active"]
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
    queryset = PCFReplenishment.objects
    serializer_class = PCFReplenishmentSerializer
    filterset_fields = ["fund", "status"]

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        replen = self.get_object()
        replen = PCFService.post_replenishment(replen, user=request.user)
        out = self.get_serializer(replen)
        return Response(out.data, status=status.HTTP_200_OK)


class InterAccountTransferViewSet(viewsets.ModelViewSet):
    queryset = InterAccountTransfer.objects
    serializer_class = InterAccountTransferSerializer
    filterset_fields = ["from_account", "to_account"]

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
            reference=request.data.get("reference", ""), user=request.user,
        )
        out = self.get_serializer(tr)
        return Response(out.data, status=status.HTTP_201_CREATED)


class CashFlowStatementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CashFlowStatement.objects
    serializer_class = CashFlowStatementSerializer
    ordering = ["-period_end"]

    @action(detail=False, methods=["post"])
    def generate(self, request):
        period_start = request.data.get("period_start")
        period_end = request.data.get("period_end")
        segment_id = request.data.get("segment")
        from apps.foundation.models import Segment
        segment = Segment.objects.get(pk=segment_id)
        cf = CashFlowService.generate(period_start, period_end, segment)
        out = self.get_serializer(cf)
        return Response(out.data, status=status.HTTP_201_CREATED)


class BankReconciliationViewSet(viewsets.ModelViewSet):
    queryset = BankReconciliation.objects
    serializer_class = BankReconciliationSerializer
    filterset_fields = ["cycle", "bank_account", "status"]

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