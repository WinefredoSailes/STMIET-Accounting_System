from rest_framework.routers import DefaultRouter

from .views import (
    AdvanceToEmployeeViewSet,
    CheckVoucherViewSet,
    CONSOBatchViewSet,
    RFPDocumentViewSet,
    SupplierViewSet,
)

router = DefaultRouter()
router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("rfps", RFPDocumentViewSet, basename="rfpdocument")
router.register("conso-batches", CONSOBatchViewSet, basename="consobatch")
router.register("check-vouchers", CheckVoucherViewSet, basename="checkvoucher")
router.register("advances", AdvanceToEmployeeViewSet, basename="advancetoemployee")

urlpatterns = router.urls