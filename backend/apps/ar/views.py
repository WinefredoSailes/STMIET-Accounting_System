from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.sequences.models import DocumentSequence

from .models import AcknowledgmentReceipt, ARInvoice, Customer, Deposit, PriceSnapshot
from .serializers import (
    AcknowledgmentReceiptSerializer,
    ARInvoiceSerializer,
    CustomerSerializer,
    DepositSerializer,
    PriceSnapshotSerializer,
)
from .services import CollectionService, CycleLedgerService


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
    queryset = AcknowledgmentReceipt.objects.select_related("customer", "segment")
    serializer_class = AcknowledgmentReceiptSerializer
    search_fields = ["receipt_no"]
    filterset_fields = ["customer", "segment", "payment_method"]

    def create(self, request, *args, **kwargs):
        """Record a collection: auto-number AR#, post the cash.collection JE."""
        data = request.data.copy()
        customer = get_object_or_404(Customer, pk=data.get("customer"))
        cash_account = data.get("cash_account")
        if not cash_account:
            return Response({"detail": "cash_account is required."}, status=status.HTTP_400_BAD_REQUEST)

        from apps.foundation.models import Account

        cash_acct = Account.objects.get(pk=cash_account)
        receipt = CollectionService.record_collection(
            receipt_no=data.get("receipt_no") or DocumentSequence.next_number(
                company=customer.segment.company, form_code="AR", year=request.data.get("year", 2026),
            ),
            customer=customer,
            transaction_date=data.get("transaction_date"),
            amount=data.get("amount"),
            cash_account=cash_acct,
            payment_method=data.get("payment_method", "cash"),
            check_no=data.get("check_no", ""),
            applied_to=ARInvoice.objects.filter(pk=data["applied_to"]).first() if data.get("applied_to") else None,
            user=request.user,
        )
        out = self.get_serializer(receipt)
        return Response(out.data, status=status.HTTP_201_CREATED)


class DepositViewSet(viewsets.ModelViewSet):
    queryset = Deposit.objects
    serializer_class = DepositSerializer
    filterset_fields = ["bank_account"]