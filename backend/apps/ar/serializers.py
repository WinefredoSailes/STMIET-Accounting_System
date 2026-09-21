from rest_framework import serializers

from .models import (
    AcknowledgmentReceipt,
    AcknowledgmentReceiptLine,
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
            "lines",
        )
        read_only_fields = ("status", "balance")


class AcknowledgmentReceiptLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.code", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)
    segment_code = serializers.CharField(source="segment.code", read_only=True)

    class Meta:
        model = AcknowledgmentReceiptLine
        fields = (
            "id", "line_no", "account", "account_code", "account_name",
            "segment", "segment_code", "cost_center", "description",
            "debit", "credit",
        )


class AcknowledgmentReceiptSerializer(serializers.ModelSerializer):
    lines = AcknowledgmentReceiptLineSerializer(many=True, read_only=True)

    class Meta:
        model = AcknowledgmentReceipt
        fields = (
            "id", "receipt_no", "customer", "transaction_date", "amount",
            "payment_method", "cash_account", "check_no", "transaction_no", "ref_po_no",
            "segment", "applied_to", "journal_entry", "status", "lines",
            "approved_by", "approved_at", "rejected_by", "rejected_at",
            "rejection_note", "attachment", "deposit",
        )
        read_only_fields = (
            "journal_entry", "status", "approved_by", "approved_at",
            "rejected_by", "rejected_at", "rejection_note", "deposit",
        )


class DepositSerializer(serializers.ModelSerializer):
    class Meta:
        model = Deposit
        fields = (
            "id", "bank_account", "transaction_date", "deposit_no", "amount",
            "reference", "attachment", "journal_entry",
        )
        read_only_fields = ("deposit_no", "journal_entry")