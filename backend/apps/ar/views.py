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
    queryset = Customer.objects
    serializer_class = CustomerSerializer
    search_fields = ["code", "name"]
    filterset_fields = ["group", "segment", "pricing_tier"]

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

        norm_lines = None
        if lines:
            norm_lines = []
            for line in lines:
                norm_lines.append(
                    {
                        "account": Account.objects.get(pk=line["account"]),
                        "segment": Segment.objects.get(pk=line["segment"])
                        if line.get("segment")
                        else customer.segment,
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
            deposit = DepositService.record_deposit(
                receipts=receipts,
                bank_account=Account.objects.get(pk=request.data.get("bank_account")),
                transaction_date=request.data.get("transaction_date"),
                reference=request.data.get("reference", ""),
                user=request.user,
            )
        except AccountingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(deposit).data, status=status.HTTP_201_CREATED)
