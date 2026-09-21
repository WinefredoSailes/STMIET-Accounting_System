from rest_framework.routers import DefaultRouter

from .views import BillingViewSet

router = DefaultRouter()
router.register("billings", BillingViewSet, basename="billingdocument")

urlpatterns = router.urls