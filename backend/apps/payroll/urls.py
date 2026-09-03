"""Payroll GL feed routes (BUILD-PLAN Phase 6, ADR-033)."""

from django.urls import path

from .views import (
    PayrollFeedDetailView,
    PayrollFeedListView,
    PayrollFeedUploadView,
)

urlpatterns = [
    path("feeds/", PayrollFeedUploadView.as_view(), name="payroll-feeds"),
    path("feeds/list/", PayrollFeedListView.as_view(), name="payroll-feeds-list"),
    path("feeds/<str:batch_reference>/", PayrollFeedDetailView.as_view(), name="payroll-feed-detail"),
]