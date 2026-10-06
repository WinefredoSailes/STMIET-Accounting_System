"""Billing REST API (ADR-010 API-first).

The UI and the API post to the same ``BillingService`` so they cannot drift.
"""

from datetime import date

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.exceptions import ValidationError
from apps.foundation.models import Account, Segment
from apps.sequences.models import DocumentSequence

from .models import BillingDocument
from .serializers import BillingDocumentSerializer
from .services import BillingService


class BillingViewSet(viewsets.ModelViewSet):
    queryset = BillingDocument.objects.prefetch_related("lines")
    serializer_class = BillingDocumentSerializer
    search_fields = ["billing_no", "party_name", "particulars"]
    filterset_fields = ["billing_type", "status", "segment"]

    # ------------------------------------------------------------------ create

    def _segment(self, value):
        if not value:
            return None
        seg = Segment.objects.filter(pk=value).first() if str(value).isdigit() else None
        if seg is None:
            seg = Segment.objects.filter(code=value).first()
        return seg

    def _lines(self, payload, header_segment):
        out = []
        for raw in payload.get("lines", []):
            seg = self._segment(raw.get("segment")) or header_segment
            account = None
            if raw.get("account"):
                account = Account.objects.filter(pk=raw["account"]).first()
            elif raw.get("account_code"):
                account = Account.objects.filter(code=raw["account_code"]).first()
            if account is None:
                raise ValidationError("Each billing line needs a valid COA account.")
            out.append(
                {
                    "side": raw.get("side", "dr"),
                    "segment": seg,
                    "account": account,
                    "amount": raw.get("amount"),
                    "description": raw.get("description", ""),
                    "cost_center": raw.get("cost_center", ""),
                }
            )
        return out

    def create(self, request, *args, **kwargs):
        from apps.ap.models import RFPDocument
        from apps.ar.models import Customer

        data = request.data
        segment = self._segment(data.get("segment"))
        if segment is None:
            raise ValidationError("A valid segment is required.")
        billing_date = data.get("billing_date")
        if not billing_date:
            raise ValidationError("billing_date is required.")
        billing_date = date.fromisoformat(str(billing_date))
        billing_type = data.get("billing_type", "third_party")

        rfp = RFPDocument.objects.filter(pk=data.get("rfp")).first() if data.get("rfp") else None
        if data.get("supplier"):
            raise ValidationError("Billing parties must be customers; suppliers are no longer accepted.")
        customer = Customer.objects.filter(pk=data.get("customer")).first() if data.get("customer") else None
        if customer is not None and not customer.is_approved:
            raise ValidationError(
                f"Customer {customer.code} is not approved yet "
                f"({customer.get_approval_status_display()}); only approved "
                "customers can be linked to billing."
            )

        party_name = (data.get("party_name") or "").strip()
        if billing_type == "stpc" and not party_name:
            party_name = "STPC"
        if not party_name and customer:
            party_name = customer.name
        if not party_name:
            raise ValidationError("A party (customer) is required.")

        billing_no = data.get("billing_no") or DocumentSequence.next_number(
            company=segment.company,
            form_code="BILL",
            year=billing_date.year,
            pattern="BI-{YYYY}-{SEQ:04d}",
        )
        billing = BillingService.create_billing(
            billing_no=billing_no,
            billing_date=billing_date,
            billing_type=billing_type,
            company=segment.company,
            segment=segment,
            party_name=party_name,
            lines=self._lines(data, segment),
            customer=customer,
            rfp=rfp,
            reference=data.get("reference", ""),
            particulars=data.get("particulars", ""),
            user=request.user,
        )
        return Response(self.get_serializer(billing).data, status=status.HTTP_201_CREATED)

    # ---------------------------------------------------------------- actions

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        billing = BillingService.submit(self.get_object(), user=request.user)
        return Response(self.get_serializer(billing).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        billing = BillingService.approve(self.get_object(), user=request.user)
        return Response(self.get_serializer(billing).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        billing = BillingService.reject(
            self.get_object(), user=request.user, note=request.data.get("note", "")
        )
        return Response(self.get_serializer(billing).data)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        billing = self.get_object()
        entry = BillingService.post(billing, user=request.user)
        return Response(
            {"billing": self.get_serializer(billing).data, "journal_entry": entry.entry_no}
        )

    @action(detail=False, methods=["get"], url_path="available-for-ar")
    def available_for_ar(self, request):
        """Approved third-party billings usable on an AR receipt.

        GET ?customer= — compliance and AR preparers pick from this list when
        making Acknowledgment Receipts (STPC + 3rd-party billing flows through
        the Billing Module first).
        """
        from apps.ar.models import ARBillingApplication, Customer

        from .models import BillingStatus, BillingType

        qs = BillingDocument.objects.filter(
            status=BillingStatus.APPROVED,
            billing_type=BillingType.THIRD_PARTY,
        ).select_related("customer", "segment").order_by("-billing_date")
        if request.query_params.get("customer"):
            qs = qs.filter(customer_id=request.query_params.get("customer"))
        used_ids = set(ARBillingApplication.objects.values_list("billing_id", flat=True))
        return Response([
            {
                "id": b.id, "billing_no": b.billing_no,
                "billing_date": b.billing_date, "party_name": b.party_name,
                "customer": b.customer_id, "amount": b.amount,
            }
            for b in qs if b.id not in used_ids
        ])