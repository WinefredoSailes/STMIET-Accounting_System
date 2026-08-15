from rest_framework.routers import DefaultRouter

from .views import (
    AssetCategoryViewSet,
    AssetDisposalViewSet,
    AssetViewSet,
    DepreciationScheduleViewSet,
)

router = DefaultRouter()
router.register("asset-categories", AssetCategoryViewSet, basename="assetcategories")
router.register("assets", AssetViewSet, basename="asset")
router.register("depreciation-schedule", DepreciationScheduleViewSet, basename="depreciationschedule")
router.register("disposals", AssetDisposalViewSet, basename="assetdisposal")

urlpatterns = router.urls
