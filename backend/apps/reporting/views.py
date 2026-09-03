from datetime import date

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.exceptions import ValidationError
from apps.foundation.models import Company, Segment

from .excel_export import (
    build_income_statement,
    build_statement_of_changes_in_equity,
    build_statement_of_cost_of_sales,
    build_statement_of_financial_position,
    build_statement_of_total_expenses,
    build_trial_balance,
    xlsx_response,
)
from .models import FinancialStatement, MonthEndClose, StatementTemplate
from .serializers import (
    FinancialStatementSerializer,
    MonthEndCloseSerializer,
    MonthEndCloseWriteSerializer,
    StatementTemplateSerializer,
)
from .services import FinancialStatementService, MonthEndCloseService, StatementTemplateService, TrialBalanceService


class TrialBalanceViewSet(viewsets.ViewSet):
    """Trial Balance report from the posted GL (ADR-005)."""

    def list(self, request):
        company_id = request.query_params.get("company")
        if not company_id:
            return Response({"detail": "company is required."}, status=status.HTTP_400_BAD_REQUEST)
        company = Company.objects.get(pk=company_id)
        as_of = request.query_params.get("as_of") or request.query_params.get("period_end")
        as_of = date.fromisoformat(as_of) if as_of else None
        segment = request.query_params.get("segment")
        rows = TrialBalanceService.rows(company, as_of=as_of, segment=segment)
        total_dr = sum(r["balance"] for r in rows if r["balance"] >= 0)
        total_cr = sum(-r["balance"] for r in rows if r["balance"] < 0)
        return Response(
            {
                "company": company.id,
                "as_of": as_of.isoformat() if as_of else None,
                "segment": segment,
                "rows": rows,
                "totals": {"debit": str(total_dr), "credit": str(total_cr)},
            }
        )

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        """GET /api/reporting/trial-balance/export/?company=&year= — workbook
        mirroring TRIAL-BALANCE.xlsx (Opening + Jan..Dec + YTD Dr/Cr pairs)."""
        company_id = request.query_params.get("company")
        if not company_id:
            return Response({"detail": "company is required."}, status=status.HTTP_400_BAD_REQUEST)
        company = Company.objects.get(pk=company_id)
        year = request.query_params.get("year") or date.today().year
        wb = build_trial_balance(company, int(year))
        return xlsx_response(wb, f"TRIAL-BALANCE-{year}.xlsx")


class StatementTemplateViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StatementTemplate.objects.prefetch_related("lines")
    serializer_class = StatementTemplateSerializer
    filterset_fields = ["statement_type"]

    @action(detail=False, methods=["post"])
    def seed(self, request):
        StatementTemplateService.seed_defaults()
        out = self.get_queryset()
        return Response(StatementTemplateSerializer(out, many=True).data)


class FinancialStatementViewSet(viewsets.ReadOnlyModelViewSet):
    """Generated financial statements (IS / SFP / CoS / TE / SOCE)."""

    queryset = FinancialStatement.objects.select_related("company", "segment")
    serializer_class = FinancialStatementSerializer
    filterset_fields = ["statement_type", "company", "segment", "status", "period_start", "period_end"]

    def create(self, request):
        statement_type = request.data.get("statement_type")
        if not statement_type:
            return Response({"detail": "statement_type is required."}, status=status.HTTP_400_BAD_REQUEST)
        company = Company.objects.get(pk=request.data.get("company"))
        period_start = date.fromisoformat(request.data.get("period_start"))
        period_end = date.fromisoformat(request.data.get("period_end"))
        segment = None
        if request.data.get("segment"):
            segment = Segment.objects.get(pk=request.data.get("segment"))
        quantities = request.data.get("quantities") or {}
        inputs = request.data.get("inputs") or {}

        fs = FinancialStatementService.generate(
            company=company,
            statement_type=statement_type,
            period_start=period_start,
            period_end=period_end,
            segment=segment,
            quantities=quantities,
            inputs=inputs,
            user=request.user,
        )
        out = FinancialStatementSerializer(fs)
        return Response(out.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        """GET /api/reporting/statements/export/?statement_type=sfp|soce|cos|te

        &company=&period_start=&period_end=[&net_profit=] — downloads the
        workbook mirroring the source statement file (exact layout).
        """
        statement_type = request.query_params.get("statement_type")
        builders = {
            "is": ("INCOME-STATEMENT", build_income_statement),
            "sfp": ("STATEMENT-OF-FINANCIAL-POSITION", build_statement_of_financial_position),
            "soce": ("STATEMENT-OF-CHANGES-IN-EQUITY", build_statement_of_changes_in_equity),
            "cos": ("STATEMENT-OF-COST-OF-SALES", build_statement_of_cost_of_sales),
            "te": ("STATEMENT-OF-TOTAL-EXPENSES", build_statement_of_total_expenses),
        }
        if statement_type not in builders:
            return Response(
                {"detail": "statement_type must be one of: is, sfp, soce, cos, te."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        company = Company.objects.get(pk=request.query_params.get("company"))
        period_start = date.fromisoformat(request.query_params.get("period_start"))
        period_end = date.fromisoformat(request.query_params.get("period_end"))
        net_profit = request.query_params.get("net_profit")
        if statement_type in ("cos", "te"):
            StatementTemplateService.seed_defaults()  # layouts must exist
            wb = builders[statement_type][1](company, period_start, period_end)
        else:
            wb = builders[statement_type][1](company, period_start, period_end, net_profit)
        stem = builders[statement_type][0]
        return xlsx_response(wb, f"{stem}-{period_start:%Y%m%d}-{period_end:%Y%m%d}.xlsx")

    @action(detail=False, methods=["get"])
    def run_all(self, request):
        """Generate all statements for a period (used by month-end close)."""
        company = Company.objects.get(pk=request.query_params.get("company"))
        period_start = date.fromisoformat(request.query_params.get("period_start"))
        period_end = date.fromisoformat(request.query_params.get("period_end"))
        results = []
        for ttype in ("is", "sfp", "cos", "te", "soce"):
            inputs = {}
            if ttype == "sfp":
                is_fs = results[0]
                inputs = {"eq_net_profit": is_fs.rows_by_key()["net_profit"]["amounts"]["GRAND"]}
            if ttype == "soce":
                is_fs = results[0]
                inputs = {"soce_net_profit": is_fs.rows_by_key()["net_profit"]["amounts"]["GRAND"]}
            fs = FinancialStatementService.generate(
                company=company, statement_type=ttype,
                period_start=period_start, period_end=period_end, inputs=inputs,
                user=request.user,
            )
            results.append(fs)
        return Response(FinancialStatementSerializer(results, many=True).data)


class MonthEndCloseViewSet(viewsets.ModelViewSet):
    queryset = MonthEndClose.objects.select_related("fiscal_period", "company")
    serializer_class = MonthEndCloseSerializer

    def create(self, request):
        from apps.foundation.models import FiscalPeriod

        period = FiscalPeriod.objects.get(pk=request.data.get("fiscal_period"))
        mec = MonthEndCloseService.get_or_create(period, user=request.user)
        return Response(MonthEndCloseSerializer(mec).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def advance(self, request, pk=None):
        mec = self.get_object()
        step = request.data.get("step")
        try:
            mec = MonthEndCloseService.advance(mec, step, user=request.user)
        except ValueError as exc:
            raise ValidationError(str(exc))
        return Response(MonthEndCloseSerializer(mec).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        mec = self.get_object()
        try:
            mec = MonthEndCloseService.complete(mec, user=request.user)
        except ValueError as exc:
            raise ValidationError(str(exc))
        return Response(MonthEndCloseSerializer(mec).data)
