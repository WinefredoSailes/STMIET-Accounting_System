from rest_framework import serializers

from .models import (
    AdvanceToEmployee,
    CheckVoucher,
    CONSOBatch,
    RFPDocument,
    RFPLine,
    Supplier,
)


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ("id", "code", "name", "supplier_type", "tin", "address", "contact_no", "last_ap", "default_segment")


class RFPLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = RFPLine
        fields = ("id", "line_no", "segment", "account", "amount", "description")


class RFPDocumentSerializer(serializers.ModelSerializer):
    lines = RFPLineSerializer(many=True, read_only=True)

    class Meta:
        model = RFPDocument
        fields = (
            "id", "ap_number", "last_ap", "rfp_date", "payee", "particulars", "purpose",
            "segment", "amount", "advance_amount", "status", "ap_balance",
            "conso", "conso_line_no", "journal_entry", "created_by", "checked_by",
            "approved_by_acctg", "approved_by_fin", "approved_by_cnr", "lines",
        )
        read_only_fields = ("ap_balance", "journal_entry")


class CONSOBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = CONSOBatch
        fields = ("id", "batch_no", "conso_date", "status", "total_amount", "reviewed_by")


class CheckVoucherSerializer(serializers.ModelSerializer):
    class Meta:
        model = CheckVoucher
        fields = (
            "id", "cv_number", "cv_date", "rfp", "payee", "bank_account",
            "gross_amount", "withheld_tax", "net_amount", "check_no", "status",
            "journal_entry", "signed_by", "released_by",
        )


class AdvanceToEmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdvanceToEmployee
        fields = (
            "id", "employee_name", "kind", "rfp", "segment", "granted_date",
            "amount", "liquidated_amount", "liquidated_date", "status", "outstanding",
        )
        read_only_fields = ("outstanding",)