from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

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

    def create(self, request, *args, **kwargs):
        from apps.foundation.models import Segment
        from .models import AssetCategory, Asset

        data = request.data
        segment = Segment.objects.get(pk=data.get("segment"))
        category = AssetCategory.objects.get(pk=data.get("category"))
        vehicle = None
        if data.get("vehicle"):
            from apps.fleet.models import Vehicle

            vehicle = Vehicle.objects.get(pk=data.get("vehicle"))

        asset = AssetService.acquire(
            asset_no=data.get("asset_no"),
            name=data.get("name"),
            category=category,
            segment=segment,
            acquisition_date=data.get("acquisition_date"),
            cost=data.get("cost"),
            residual_value=data.get("residual_value", "0.00"),
            funding_source=data.get("funding_source", "cash"),
            financed_loan_reference=data.get("financed_loan_reference", ""),
            acquisition_fees=data.get("acquisition_fees", "0.00"),
            vehicle=vehicle,
            user=request.user,
        )
        out = self.get_serializer(asset)
        return Response(out.data, status=status.HTTP_201_CREATED)

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
