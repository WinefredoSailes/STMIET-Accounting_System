from rest_framework.routers import DefaultRouter

from .views import (
    AdvanceToEmployeeViewSet,
    CheckVoucherViewSet,
    CONSOBatchViewSet,
    PurchaseOrderViewSet,
    RFPDocumentViewSet,
    SupplierViewSet,
)

router = DefaultRouter()
router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("rfps", RFPDocumentViewSet, basename="rfpdocument")
router.register("conso-batches", CONSOBatchViewSet, basename="consobatch")
router.register("check-vouchers", CheckVoucherViewSet, basename="checkvoucher")
router.register("advances", AdvanceToEmployeeViewSet, basename="advancetoemployee")
router.register("purchase-orders", PurchaseOrderViewSet, basename="purchaseorder")

urlpatterns = router.urls