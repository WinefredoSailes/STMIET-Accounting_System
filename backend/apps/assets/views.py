from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.exceptions import ValidationError as CoreValidationError

from .models import Asset, AssetCategory, AssetDisposal, DepreciationSchedule
from .serializers import (
    AssetCategorySerializer,
    AssetDisposalSerializer,
    AssetSerializer,
    DepreciationScheduleSerializer,
)
from .services import AssetService, DepreciationService, DisposalService


class AssetCategoryViewSet(viewsets.ModelViewSet):
    queryset = AssetCategory.objects
    serializer_class = AssetCategorySerializer
    search_fields = ["code", "name"]
    filterset_fields = ["segment", "is_active"]


class AssetViewSet(viewsets.ModelViewSet):
    queryset = Asset.objects.select_related("category", "segment")
    serializer_class = AssetSerializer
    search_fields = ["asset_no", "name"]
    filterset_fields = ["category", "segment", "status"]

    def update(self, request, *args, **kwargs):
        asset = self.get_object()
        if asset.approval_status == "posted":
            raise ValidationError("Posted assets are locked. Reversal or disposal applies.")
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        asset = self.get_object()
        if asset.approval_status in ("submitted", "approved", "posted"):
            raise ValidationError("Submitted, approved or posted assets cannot be deleted.")
        return super().destroy(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        from apps.foundation.models import Account, Segment
        from .models import AssetCategory, Asset

        data = request.data
        try:
            segment = Segment.objects.get(pk=data.get("segment"))
            category = AssetCategory.objects.get(pk=data.get("category"))
            vehicle = None
            if data.get("vehicle"):
                from apps.fleet.models import Vehicle

                vehicle = Vehicle.objects.get(pk=data.get("vehicle"))

            supplier = po = None
            if data.get("supplier"):
                from apps.ap.models import Supplier

                supplier = Supplier.objects.get(pk=data.get("supplier"))
            if data.get("po"):
                from apps.ap.models import PurchaseOrder

                po = PurchaseOrder.objects.get(pk=data.get("po"))

            lines = data.get("lines") or [
                {
                    "side": "dr", "segment": segment.id,
                    "account": data.get("asset_account"),
                    "amount": data.get("cost"),
                    "description": f"Acquisition of {data.get('name')}",
                },
                {
                    "side": "cr", "segment": segment.id,
                    "account": self._funding_account(segment, data.get("funding_source", "cash")),
                    "amount": data.get("cost"),
                    "description": f"Funded by {data.get('funding_source', 'cash')}",
                },
            ]
            resolved_lines = []
            for raw in lines:
                line = dict(raw)
                acc = Account.objects.filter(pk=line.get("account")).first()
                if acc is None:
                    acc = Account.objects.filter(code=line.get("account")).first()
                if acc is None:
                    raise ValidationError(f"Unknown account '{line.get('account')}'.")
                line["account"] = acc
                line["account_code"] = acc.code
                line["segment"] = Segment.objects.get(pk=line["segment"]) if line.get("segment") else segment
                resolved_lines.append(line)

            asset = AssetService.create_asset(
                asset_no=data.get("asset_no"),
                name=data.get("name"),
                category=category,
                segment=segment,
                acquisition_date=data.get("acquisition_date"),
                lines=resolved_lines,
                residual_value=data.get("residual_value", "0.00"),
                useful_life_months=data.get("useful_life_months") or None,
                supplier=supplier,
                po=po,
                reference=data.get("reference", ""),
                vehicle=vehicle,
                user=request.user,
            )
        except CoreValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        out = self.get_serializer(asset)
        return Response(out.data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _funding_account(segment, funding_source):
        from apps.foundation.models import SegmentAccountMap, resolve_segment_account

        role = {
            "ap": SegmentAccountMap.ROLE_AP,
            "cash": SegmentAccountMap.ROLE_CASH,
            "loan": SegmentAccountMap.ROLE_LOANS,
        }.get(funding_source, SegmentAccountMap.ROLE_CASH)
        return resolve_segment_account(segment, role).id

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        asset = self.get_object()
        try:
            AssetService.submit(asset, user=request.user)
        except (CoreValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(asset).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        asset = self.get_object()
        try:
            AssetService.approve(asset, user=request.user)
        except (CoreValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(asset).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        asset = self.get_object()
        try:
            asset = AssetService.reject(asset, user=request.user, note=request.data.get("note", ""))
        except (CoreValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(asset).data)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        asset = self.get_object()
        try:
            AssetService.post(asset, user=request.user)
        except (CoreValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(asset).data)

    @action(detail=True, methods=["post"])
    def build_schedule(self, request, pk=None):
        asset = self.get_object()
        rows = DepreciationService.build_schedule(asset, as_of=request.data.get("as_of") or None)
        out = DepreciationScheduleSerializer(rows, many=True)
        return Response(out.data)

    @action(detail=True, methods=["post"])
    def post_depreciation(self, request, pk=None):
        asset = self.get_object()
        period_start = request.data.get("period_start")
        from datetime import date

        row = DepreciationService.post_month(
            asset, period_start=date.fromisoformat(period_start), user=request.user
        )
        out = DepreciationScheduleSerializer(row)
        return Response(out.data)

    @action(detail=True, methods=["post"])
    def dispose(self, request, pk=None):
        from apps.foundation.models import Account
        from apps.foundation.models import Segment

        asset = self.get_object()
        from datetime import date

        cash_account = None
        if request.data.get("cash_account"):
            cash_account = Account.objects.get(pk=request.data.get("cash_account"))
        disposal = DisposalService.dispose(
            asset=asset,
            disposal_date=date.fromisoformat(request.data.get("disposal_date")),
            proceeds=request.data.get("proceeds", "0.00"),
            reason=request.data.get("reason", ""),
            cash_account=cash_account,
            user=request.user,
        )
        out = AssetDisposalSerializer(disposal)
        return Response(out.data, status=status.HTTP_201_CREATED)


class DepreciationScheduleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DepreciationSchedule.objects
    serializer_class = DepreciationScheduleSerializer
    filterset_fields = ["asset", "status", "is_still_in_use"]


class AssetDisposalViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AssetDisposal.objects
    serializer_class = AssetDisposalSerializer
    filterset_fields = ["asset", "status"]
