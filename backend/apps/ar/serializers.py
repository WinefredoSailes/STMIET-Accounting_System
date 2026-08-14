from rest_framework import serializers

from .models import (
    AcknowledgmentReceipt,
    ARInvoice,
    ARInvoiceLine,
    Customer,
    Deposit,
    PriceSnapshot,
)


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = (
            "id", "code", "name", "group", "segment", "pricing_tier",
            "tin", "address", "contact_no", "notes",
        )


class PriceSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceSnapshot
        fields = ("id", "customer", "product_code", "cycle_start", "unit_price", "tier")


class ARInvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ARInvoiceLine
        fields = ("id", "line_no", "product_code", "description", "quantity", "unit_price", "amount")


class ARInvoiceSerializer(serializers.ModelSerializer):
    lines = ARInvoiceLineSerializer(many=True, read_only=True)

    class Meta:
        model = ARInvoice
        fields = (
            "id", "invoice_no", "customer", "transaction_date", "segment",
            "total", "is_paid_on_delivery", "status", "balance", "booked_on_payment",
        )
        read_only_fields = ("status", "balance")


class AcknowledgmentReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcknowledgmentReceipt
        fields = (
            "id", "receipt_no", "customer", "transaction_date", "amount",
            "payment_method", "cash_account", "check_no", "segment",
            "applied_to", "journal_entry",
        )
        read_only_fields = ("journal_entry",)


class DepositSerializer(serializers.ModelSerializer):
    class Meta:
        model = Deposit
        fields = ("id", "bank_account", "transaction_date", "amount", "reference")