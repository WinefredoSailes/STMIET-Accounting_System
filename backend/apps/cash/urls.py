from rest_framework.routers import DefaultRouter

from .views import (
    BankAccountViewSet,
    BankReconciliationViewSet,
    CashFlowStatementViewSet,
    CashShortExcessViewSet,
    CheckDisbursementViewSet,
    CollectiblesViewSet,
    InterAccountTransferViewSet,
    PCFReplenishmentViewSet,
    PettyCashFundViewSet,
    WeeklyCashCycleViewSet,
)

router = DefaultRouter()
router.register("bank-accounts", BankAccountViewSet, basename="bankaccount")
router.register("cycles", WeeklyCashCycleViewSet, basename="weeklycashcycle")
router.register("reconciliations", BankReconciliationViewSet, basename="bankreconciliation")
router.register("pcf-funds", PettyCashFundViewSet, basename="pcffund")
router.register("pcf-replenishments", PCFReplenishmentViewSet, basename="pcfreplenishment")
router.register("transfers", InterAccountTransferViewSet, basename="interaccounttransfer")
router.register("cash-flow", CashFlowStatementViewSet, basename="cashflowstatement")
router.register("disbursements", CheckDisbursementViewSet, basename="checkdisbursement")
router.register("collectibles", CollectiblesViewSet, basename="collectiblesworksheet")
router.register("cash-short", CashShortExcessViewSet, basename="cashshortexcess")

urlpatterns = router.urls