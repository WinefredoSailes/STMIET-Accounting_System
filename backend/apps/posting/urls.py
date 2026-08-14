from rest_framework.routers import DefaultRouter

from .views import JournalEntryViewSet, PostingRuleViewSet

router = DefaultRouter()
router.register("entries", JournalEntryViewSet, basename="journalentry")
router.register("rules", PostingRuleViewSet, basename="postingrule")

urlpatterns = router.urls