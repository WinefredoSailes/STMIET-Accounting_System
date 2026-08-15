from django.shortcuts import get_object_or_404
from datetime import date
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.sequences.models import DocumentSequence

from .models import (
    AdvanceToEmployee,
    CheckVoucher,
    CONSOBatch,
    RFPDocument,
    Supplier,
)
from .serializers import (
    AdvanceToEmployeeSerializer,
    CheckVoucherSerializer,
    CONSOBatchSerializer,
    RFPDocumentSerializer,
    SupplierSerializer,
)
from .services import (
    AdvanceService,
    CONSOService,
    CVPaymentService,
    RFPService,
)


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects
    serializer_class = SupplierSerializer
    search_fields = ["code", "name"]
    filterset_fields = ["supplier_type"]


class RFPDocumentViewSet(viewsets.ModelViewSet):
    queryset = RFPDocument.objects.prefetch_related("lines")
    serializer_class = RFPDocumentSerializer
    search_fields = ["ap_number", "payee__name", "particulars"]
    filterset_fields = ["status", "segment"]

    def create(self, request, *args, **kwargs):
        """Create RFP: auto-number A####, validate lines sum, set LAST AP."""
        data = request.data
        from apps.foundation.models import Segment, Account
        from apps.foundation.models import Company

        segment = Segment.objects.get(pk=data.get("segment"))
        payee = Supplier.objects.get(pk=data.get("payee"))
        lines = data.get("lines", [])

        ap_number = data.get("ap_number") or DocumentSequence.next_number(
            company=payee.default_segment.company if payee.default_segment else segment.company,
            form_code="RFP", year=request.data.get("year", 2026),
        )

        rfp = RFPService.create_rfp(
            ap_number=ap_number,
            rfp_date=data.get("rfp_date"),
            payee=payee,
            particulars=data.get("particulars"),
            amount=data.get("amount"),
            segment=segment,
            purpose=data.get("purpose", ""),
            advance_amount=data.get("advance_amount", "20000.00"),
            lines=lines,
            user=request.user,
        )
        out = self.get_serializer(rfp)
        return Response(out.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        rfp = self.get_object()
        if rfp.status != "prepared":
            return Response({"detail": "Only prepared RFPs can be submitted."}, status=status.HTTP_400_BAD_REQUEST)
        rfp.status = "submitted"
        rfp.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(rfp).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """Advance approval step: checked -> acctg_approved -> fin_approved."""
        rfp = self.get_object()
        step = request.data.get("step")  # checked / acctg_approved / fin_approved
        if not step:
            return Response({"detail": "step required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            rfp = RFPService.advance_step(rfp, role=step, user=request.user)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(rfp).data)

    @action(detail=True, methods=["post"])
    def approve_cnr(self, request, pk=None):
        rfp = self.get_object()
        try:
            rfp = RFPService.approve_cnr(rfp, user=request.user)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(rfp).data)


class CONSOBatchViewSet(viewsets.ModelViewSet):
    queryset = CONSOBatch.objects
    serializer_class = CONSOBatchSerializer
    filterset_fields = ["status"]

    @action(detail=True, methods=["post"])
    def add_rfp(self, request, pk=None):
        batch = self.get_object()
        rfp_id = request.data.get("rfp_id")
        rfp = get_object_or_404(RFPDocument, pk=rfp_id)
        rfp.conso = batch
        rfp.save(update_fields=["conso", "updated_at"])
        return Response(self.get_serializer(batch).data)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        batch = self.get_object()
        try:
            batch = CONSOService.post_batch(batch, user=request.user)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(batch).data)


class CheckVoucherViewSet(viewsets.ModelViewSet):
    queryset = CheckVoucher.objects
    serializer_class = CheckVoucherSerializer
    filterset_fields = ["status", "payee"]

    def create(self, request, *args, **kwargs):
        data = request.data
        from apps.foundation.models import Account, Supplier

        payee = Supplier.objects.get(pk=data.get("payee"))
        bank_account = Account.objects.get(pk=data.get("bank_account"))
        rfp = None
        if data.get("rfp"):
            rfp = RFPDocument.objects.get(pk=data.get("rfp"))

        cv = CVPaymentService.create_cv(
            cv_number=data.get("cv_number") or f"CV-{date.today().year}-{CheckVoucher.objects.count()+1:04d}",
            cv_date=data.get("cv_date"),
            payee=payee,
            bank_account=bank_account,
            gross_amount=data.get("gross_amount"),
            withheld_tax=data.get("withheld_tax", "0.00"),
            rfp=rfp,
            check_no=data.get("check_no", ""),
            user=request.user,
        )
        out = self.get_serializer(cv)
        return Response(out.data, status=status.HTTP_201_CREATED)


class AdvanceToEmployeeViewSet(viewsets.ModelViewSet):
    queryset = AdvanceToEmployee.objects
    serializer_class = AdvanceToEmployeeSerializer
    filterset_fields = ["kind", "status", "segment"]

    @action(detail=True, methods=["post"])
    def liquidate(self, request, pk=None):
        advance = self.get_object()
        amount = request.data.get("amount")
        liquidate_date = request.data.get("liquidate_date")
        try:
            advance = AdvanceService.liquidate(advance, amount=amount, liquidate_date=liquidate_date, user=request.user)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(advance).data)