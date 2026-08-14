from rest_framework.routers import DefaultRouter

from .views import (
    AcknowledgmentReceiptViewSet,
    ARInvoiceViewSet,
    CustomerViewSet,
    DepositViewSet,
    PriceSnapshotViewSet,
)

router = DefaultRouter()
router.register("customers", CustomerViewSet, basename="customer")
router.register("price-snapshots", PriceSnapshotViewSet, basename="pricesnapshot")
router.register("invoices", ARInvoiceViewSet, basename="arinvoice")
router.register("receipts", AcknowledgmentReceiptViewSet, basename="ackreceipt")
router.register("deposits", DepositViewSet, basename="deposit")

urlpatterns = router.urls