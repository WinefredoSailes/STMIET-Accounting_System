from rest_framework import viewsets

from .models import Account, Company, FiscalPeriod, FiscalYear, Segment
from .serializers import (
    AccountSerializer,
    CompanySerializer,
    FiscalPeriodSerializer,
    FiscalYearSerializer,
    SegmentSerializer,
)


class CompanyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Company.objects
    serializer_class = CompanySerializer
    filterset_fields = ["code"]


class SegmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Segment.objects
    serializer_class = SegmentSerializer


class FiscalYearViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = FiscalYear.objects
    serializer_class = FiscalYearSerializer


class FiscalPeriodViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = FiscalPeriod.objects
    serializer_class = FiscalPeriodSerializer


class AccountViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Account.objects
    serializer_class = AccountSerializer
    filterset_fields = ["code", "account_type", "segment", "is_control", "is_postable"]
    search_fields = ["code", "name"]