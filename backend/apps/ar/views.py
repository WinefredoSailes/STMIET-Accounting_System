from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.exceptions import AccountingError

from .models import AcknowledgmentReceipt, ARInvoice, Customer, Deposit, PriceSnapshot
from .serializers import (
    AcknowledgmentReceiptSerializer,
    ARInvoiceSerializer,
    CustomerSerializer,
    DepositSerializer,
    PriceSnapshotSerializer,
)
from .services import CollectionService, CycleLedgerService, DepositService


class CustomerViewSet(viewsets.ModelViewSet):
    """Customer master. Staff-created customers land ``pending`` and must be
    approved by the Accounting & Finance Head (same rule as the UI); the
    Head's own creations are approved immediately."""

    queryset = Customer.objects
    serializer_class = CustomerSerializer
    search_fields = ["code", "name"]
    filterset_fields = ["group", "pricing_tier", "approval_status"]

    def create(self, request, *args, **kwargs):
        from apps.ar.services import CustomerService

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = CustomerService.create_customer(
            created_by=request.user, **serializer.validated_data
        )
        return Response(self.get_serializer(customer).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        from apps.core.approvals import can_edit_master

        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        creator_revise = (
            instance.approval_status == "rejected"
            and instance.created_by_id == getattr(request.user, "id", None)
        )
        if not can_edit_master(request.user) and not creator_revise:
            return Response(
                {"detail": "Only the Accounting & Finance Head may edit customers."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        from apps.ar.services import CustomerService

        customer = CustomerService.update_customer(
            instance, user=request.user, **serializer.validated_data
        )
        return Response(self.get_serializer(customer).data)

    partial_update = update

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """pending -> approved (head only)."""
        from apps.ar.services import CustomerService
        from apps.core.approvals import require_approval_role

        require_approval_role(request.user, "head")
        customer = self.get_object()
        CustomerService.approve(customer, user=request.user)
        return Response(self.get_serializer(customer).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """pending -> rejected (head only, note required)."""
        from apps.ar.services import CustomerService
        from apps.core.approvals import require_approval_role

        require_approval_role(request.user, "head")
        customer = self.get_object()
        CustomerService.reject(
            customer, user=request.user, note=request.data.get("note", "")
        )
        return Response(self.get_serializer(customer).data)

    @action(detail=True, methods=["post"])
    def resubmit(self, request, pk=None):
        """rejected -> pending, so it re-enters the Head's queue."""
        from apps.ar.services import CustomerService

        customer = self.get_object()
        CustomerService.resubmit(customer, user=request.user)
        return Response(self.get_serializer(customer).data)

    @action(detail=True, methods=["get"])
    def ledger(self, request, pk=None):
        customer = self.get_object()
        return Response(CycleLedgerService.for_customer(customer))


class PriceSnapshotViewSet(viewsets.ModelViewSet):
    queryset = PriceSnapshot.objects
    serializer_class = PriceSnapshotSerializer
    filterset_fields = ["customer", "product_code", "tier"]


class ARInvoiceViewSet(viewsets.ModelViewSet):
    queryset = ARInvoice.objects.prefetch_related("lines")
    serializer_class = ARInvoiceSerializer
    search_fields = ["invoice_no"]
    filterset_fields = ["customer", "segment", "status"]


class AcknowledgmentReceiptViewSet(viewsets.ModelViewSet):
    queryset = AcknowledgmentReceipt.objects.select_related(
        "customer", "segment"
    ).prefetch_related("lines__account", "lines__segment")
    serializer_class = AcknowledgmentReceiptSerializer
    search_fields = ["receipt_no"]
    filterset_fields = ["customer", "segment", "payment_method", "status"]

    def create(self, request, *args, **kwargs):
        """Create a DRAFT receipt with its account distribution (no JE yet)."""
        from apps.foundation.models import Account, Segment

        data = request.data
        customer = get_object_or_404(Customer, pk=data.get("customer"))
        if not customer.is_approved:
            return Response(
                {
                    "detail": f"Customer {customer.code} is not approved yet "
                    f"({customer.get_approval_status_display()}); collections "
                    "require an approved customer."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        transaction_date = data.get("transaction_date")
        if not transaction_date:
            return Response(
                {"detail": "transaction_date is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lines = data.get("lines")
        cash_account = None
        if data.get("cash_account"):
            cash_account = Account.objects.get(pk=data["cash_account"])

        header_segment = Segment.objects.get(pk=data.get("segment")) if data.get("segment") else None
        norm_lines = None
        if lines:
            norm_lines = []
            for line in lines:
                norm_lines.append(
                    {
                        "account": Account.objects.get(pk=line["account"]),
                        "segment": Segment.objects.get(pk=line["segment"])
                        if line.get("segment")
                        else header_segment,
                        "cost_center": line.get("cost_center", ""),
                        "description": line.get("description", ""),
                        "debit": line.get("debit", 0),
                        "credit": line.get("credit", 0),
                    }
                )
        try:
            receipt = CollectionService.create_receipt(
                customer=customer,
                transaction_date=transaction_date,
                amount=data.get("amount"),
                cash_account=cash_account,
                payment_method=data.get("payment_method", "cash"),
                check_no=data.get("check_no", ""),
                transaction_no=data.get("transaction_no", ""),
                ref_po_no=data.get("ref_po_no", ""),
                applied_to=ARInvoice.objects.filter(pk=data["applied_to"]).first()
                if data.get("applied_to")
                else None,
                lines=norm_lines,
                created_by=request.user,
                segment=header_segment,
            )
        except AccountingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        out = self.get_serializer(receipt)
        return Response(out.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        receipt = self.get_object()
        try:
            CollectionService.submit(receipt, user=request.user)
        except AccountingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(receipt).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        receipt = self.get_object()
        try:
            CollectionService.approve(receipt, user=request.user)
        except AccountingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(receipt).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        receipt = self.get_object()
        try:
            CollectionService.reject(
                receipt, user=request.user, note=request.data.get("note", "")
            )
        except AccountingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(receipt).data)


class DepositViewSet(viewsets.ModelViewSet):
    queryset = Deposit.objects.select_related("bank_account", "journal_entry")
    serializer_class = DepositSerializer
    filterset_fields = ["bank_account"]

    def create(self, request, *args, **kwargs):
        """Record a bank deposit over one or more posted receipts (posts JE)."""
        from apps.foundation.models import Account

        receipt_ids = request.data.get("receipts") or []
        receipts = list(
            AcknowledgmentReceipt.objects.filter(pk__in=receipt_ids).select_related("segment")
        )
        try:
            bank_id = request.data.get("bank_account")
            bank_account = Account.objects.get(pk=bank_id) if bank_id else None
            deposit = DepositService.record_deposit(
                receipts=receipts,
                bank_account=bank_account,
                transaction_date=request.data.get("transaction_date"),
                reference=request.data.get("reference", ""),
                user=request.user,
                distribution=request.data.get("distribution"),
            )
        except AccountingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(deposit).data, status=status.HTTP_201_CREATED)
