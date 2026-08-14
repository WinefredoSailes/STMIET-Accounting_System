from rest_framework.routers import DefaultRouter

from .views import ApprovalRequestViewSet

router = DefaultRouter()
router.register("requests", ApprovalRequestViewSet, basename="approvalrequest")

urlpatterns = router.urls