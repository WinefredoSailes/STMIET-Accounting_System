"""Inventory integration bridge routes (BUILD-PLAN Phase 5)."""

from django.urls import path

from .views import InventoryEventIngestView, InventoryEventRetryView, InventoryEventStatusView

urlpatterns = [
    path("events/", InventoryEventIngestView.as_view(), name="inventory-ingest"),
    path("events/status/", InventoryEventStatusView.as_view(), name="inventory-status"),
    path("events/retry/", InventoryEventRetryView.as_view(), name="inventory-retry"),
]