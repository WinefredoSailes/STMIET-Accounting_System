from django.core.exceptions import PermissionDenied
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
    PurchaseOrder,
    RFPDocument,
    Supplier,
)
from .serializers import (
    AdvanceToEmployeeSerializer,
    CheckVoucherSerializer,
    CONSOBatchSerializer,
    PurchaseOrderSerializer,
    RFPDocumentSerializer,
    SupplierSerializer,
)
from .services import (
    AdvanceService,
    CONSOService,
    CVPaymentService,
    PurchaseOrderService,
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

    def _assert_can_edit(self, rfp):
        """The preparer may edit an RFP only while it is still `prepared` —
        after it leaves her desk (submitted or later) changes go through the
        reject/revise cycle and no one may delete a document."""
        if rfp.status != "prepared":
            raise PermissionDenied("Only prepared RFPs can be edited.")
        if self.request.user.id != rfp.created_by_id:
            raise PermissionDenied("Only the preparer may edit this RFP.")

    def update(self, request, *args, **kwargs):
        rfp = self.get_object()
        self._assert_can_edit(rfp)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        rfp = self.get_object()
        self._assert_can_edit(rfp)
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        rfp = self.get_object()
        self._assert_can_edit(rfp)
        return super().destroy(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """Create RFP: auto-number A####, validate lines sum, set LAST AP."""
        data = request.data
        from apps.foundation.models import Segment, Account
        from apps.foundation.models import Company

        segment = Segment.objects.get(pk=data.get("segment"))
        payee = Supplier.objects.get(pk=data.get("payee"))
        lines = data.get("lines", [])
        po = None
        if data.get("po"):
            po = PurchaseOrder.objects.get(pk=data.get("po"))

        ap_number = data.get("ap_number") or DocumentSequence.next_number(
            company=payee.default_segment.company if payee.default_segment else segment.company,
            form_code="RFP", year=request.data.get("year", 2026),
        )

        rfp = RFPService.create_rfp(
            ap_number=ap_number,
            rfp_date=data.get("rfp_date"),
            payee=payee,
            segment=segment,
            purpose=data.get("purpose", ""),
            lines=lines,
            user=request.user,
            po=po,
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
        from apps.core.approvals import require_approval_role

        try:
            require_approval_role(request.user, step)
            rfp = RFPService.advance_step(rfp, role=step, user=request.user)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(rfp).data)

    @action(detail=True, methods=["post"])
    def approve_cnr(self, request, pk=None):
        rfp = self.get_object()
        from apps.core.approvals import require_approval_role

        try:
            require_approval_role(request.user, "coo")
            rfp = RFPService.approve_cnr(rfp, user=request.user)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(rfp).data)


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    """Purchase Orders (ADR-0XX): auto-numbered {YYYY}-{SEQ}, approval chain
    mirrors the RFP (head trio + optional CNR/COO), manually closed by head."""

    queryset = PurchaseOrder.objects.prefetch_related("lines")
    serializer_class = PurchaseOrderSerializer
    search_fields = ["po_number", "supplier__name", "particulars"]
    filterset_fields = ["status", "segment"]

    def create(self, request, *args, **kwargs):
        data = request.data
        from apps.foundation.models import Segment
        from apps.sequences.models import DocumentSequence

        segment = Segment.objects.get(pk=data.get("segment"))
        supplier = Supplier.objects.get(pk=data.get("supplier"))
        company = segment.company or (supplier.default_segment.company if supplier.default_segment else None)
        try:
            year = int(str(data.get("po_date"))[:4])
        except (TypeError, ValueError):
            year = date.today().year

        po_number = data.get("po_number") or DocumentSequence.next_number(
            company=company, form_code="PO", year=year, pattern="{YYYY}-{SEQ:05d}",
        )

        po = PurchaseOrderService.create_po(
            po_number=po_number,
            po_date=data.get("po_date"),
            supplier=supplier,
            segment=segment,
            particulars=data.get("particulars", ""),
            lines=data.get("lines", []),
            discount=data.get("discount", "0.00"),
            vat_amount=data.get("vat_amount", "0.00"),
            other_charges=data.get("other_charges", "0.00"),
            payment_terms=data.get("payment_terms", ""),
            contract_duration=data.get("contract_duration", ""),
            ship_to_company=data.get("ship_to_company", ""),
            ship_to_address=data.get("ship_to_address", ""),
            contact_person=data.get("contact_person", ""),
            notes=data.get("notes", ""),
            user=request.user,
        )
        out = self.get_serializer(po)
        return Response(out.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        po = self.get_object()
        if po.status != "prepared":
            return Response({"detail": "Only prepared POs can be submitted."}, status=status.HTTP_400_BAD_REQUEST)
        po.status = "submitted"
        po.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(po).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """Advance approval step: checked -> acctg_approved -> fin_approved."""
        po = self.get_object()
        step = request.data.get("step")  # checked / acctg_approved / fin_approved
        if not step:
            return Response({"detail": "step required"}, status=status.HTTP_400_BAD_REQUEST)
        from apps.core.approvals import require_approval_role

        try:
            require_approval_role(request.user, step)
            po = PurchaseOrderService.advance_step(po, role=step, user=request.user)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(po).data)

    @action(detail=True, methods=["post"])
    def approve_cnr(self, request, pk=None):
        po = self.get_object()
        from apps.core.approvals import require_approval_role

        try:
            require_approval_role(request.user, "coo")
            po = PurchaseOrderService.approve_cnr(po, user=request.user)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(po).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        po = self.get_object()
        from apps.core.approvals import require_approval_role

        try:
            require_approval_role(request.user, "head")
            po = PurchaseOrderService.close_po(po, user=request.user)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(po).data)


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

        try:
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
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
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