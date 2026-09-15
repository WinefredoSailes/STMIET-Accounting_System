from rest_framework import serializers

from .models import (
    AdvanceToEmployee,
    CheckVoucher,
    CONSOBatch,
    POLine,
    PurchaseOrder,
    RFPDocument,
    RFPLine,
    Supplier,
    SupplierContact,
)


class SupplierContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierContact
        fields = ("id", "name", "position", "phone", "email", "is_primary")


class SupplierSerializer(serializers.ModelSerializer):
    contacts = SupplierContactSerializer(many=True, read_only=True)

    class Meta:
        model = Supplier
        fields = ("id", "code", "name", "supplier_type", "tin", "address", "contact_no",
                  "owner_name", "email", "contact_person", "position", "attachments_required",
                  "last_ap", "default_segment", "contacts")


class RFPLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = RFPLine
        fields = ("id", "line_no", "side", "segment", "account", "amount", "description", "cost_center")


class RFPDocumentSerializer(serializers.ModelSerializer):
    lines = RFPLineSerializer(many=True, read_only=True)

    class Meta:
        model = RFPDocument
        fields = (
            "id", "ap_number", "last_ap", "rfp_date", "payee", "particulars", "purpose",
            "segment", "amount", "status",
            "conso", "conso_line_no", "journal_entry", "created_by", "checked_by",
            "approved_by_acctg", "approved_by_fin", "approved_by_cnr", "po", "lines",
        )
        read_only_fields = ("journal_entry",)


class POLineSerializer(serializers.ModelSerializer):
    account_code = serializers.SerializerMethodField()
    account_name = serializers.SerializerMethodField()

    def get_account_code(self, obj):
        return obj.account.code if obj.account else ""

    def get_account_name(self, obj):
        return obj.account.name if obj.account else ""

    class Meta:
        model = POLine
        fields = (
            "id", "line_no", "pr_number", "qty", "unit", "description",
            "unit_price", "amount", "account", "account_code", "account_name",
        )


class PurchaseOrderSerializer(serializers.ModelSerializer):
    lines = POLineSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = (
            "id", "po_number", "po_date", "supplier", "segment", "particulars",
            "subtotal", "discount", "vat_amount", "other_charges", "amount",
            "payment_terms", "contract_duration", "ship_to_company", "ship_to_address",
            "contact_person", "notes", "status",
            "billed_amount", "reserved_amount", "available_amount", "lines",
        )
        read_only_fields = ("billed_amount", "reserved_amount", "available_amount")


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
            "journal_entry", "approved_by", "approved_at",
        )


class AdvanceToEmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdvanceToEmployee
        fields = (
            "id", "employee_name", "kind", "rfp", "segment", "granted_date",
            "amount", "liquidated_amount", "liquidated_date", "status", "outstanding",
        )
        read_only_fields = ("outstanding",)