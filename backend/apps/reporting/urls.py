from rest_framework.routers import DefaultRouter

from .views import (
    FinancialStatementViewSet,
    MonthEndCloseViewSet,
    StatementTemplateViewSet,
    TrialBalanceViewSet,
)

router = DefaultRouter()
router.register("trial-balance", TrialBalanceViewSet, basename="trialbalance")
router.register("templates", StatementTemplateViewSet, basename="statementtemplate")
router.register("statements", FinancialStatementViewSet, basename="financialstatement")
router.register("month-end-close", MonthEndCloseViewSet, basename="monthendclose")

urlpatterns = router.urls
