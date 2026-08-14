from rest_framework.routers import DefaultRouter

from .views import AccountViewSet, CompanyViewSet, FiscalPeriodViewSet, FiscalYearViewSet, SegmentViewSet

router = DefaultRouter()
router.register("companies", CompanyViewSet, basename="company")
router.register("segments", SegmentViewSet, basename="segment")
router.register("fiscal-years", FiscalYearViewSet, basename="fiscalyear")
router.register("fiscal-periods", FiscalPeriodViewSet, basename="fiscalperiod")
router.register("accounts", AccountViewSet, basename="account")

urlpatterns = router.urls