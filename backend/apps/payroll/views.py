"""Payroll GL feed API (BUILD-PLAN Phase 6, ADR-033).

The payroll team uploads/ingests the feed (external system → accounting);
reviewers approve or reject via the UI (or this API). Posting produces one
immutable JE. This mirrors the tax module split: domain logic here, staff
screens in apps.ui.
"""

from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import ValidationError

from .models import PayrollFeed, PayrollFeedStatus
from .services import PayrollFeedService


class PayrollFeedUploadView(APIView):
    """POST /api/v1/payroll/feeds/ — ingest a feed from structured JSON or file."""

    permission_classes = [AllowAny]
    parser_classes = [FormParser, MultiPartParser, JSONParser]

    def post(self, request):
        data = request.data or {}
        try:
            if "file" in request.FILES and not data.get("batch_reference"):
                feed_data = PayrollFeedService.parse_workbook(request.FILES["file"])
            else:
                feed_data = {
                    "batch_reference": data["batch_reference"],
                    "period_start": data["period_start"],
                    "period_end": data["period_end"],
                    "entity": data["entity"],
                    "segment_code": data.get("segment"),
                    "cost_center": data.get("cost_center", ""),
                    "lines": data.get("lines", []),
                }
            feed = PayrollFeedService.ingest(
                **feed_data, user=_request_user(request),
            )
        except (ValidationError, KeyError, ValueError, IndexError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(_feed_payload(feed), status=status.HTTP_201_CREATED)


class PayrollFeedListView(APIView):
    """GET /api/v1/payroll/feeds/ — list feed batches (filterable by status)."""

    permission_classes = [AllowAny]

    def get(self, request):
        qs = PayrollFeed.objects.select_related("segment", "journal_entry", "review_user")
        status_ = request.query_params.get("status")
        if status_:
            qs = qs.filter(status=status_)
        return Response([_feed_payload(f) for f in qs.order_by("period_start")[:100]])


class PayrollFeedDetailView(APIView):
    """GET/POST on /api/v1/payroll/feeds/<batch_reference>/."""

    permission_classes = [AllowAny]

    def get(self, request, batch_reference):
        feed = _get_feed(batch_reference)
        body = _feed_payload(feed)
        if feed.status == PayrollFeedStatus.VALIDATED:
            body["preview"] = PayrollFeedService.preview(feed)
        return Response(body)

    def post(self, request, batch_reference):
        feed = _get_feed(batch_reference)
        action = request.data.get("action")
        try:
            if action == "post":
                feed = PayrollFeedService.post(feed, user=_request_user(request))
            elif action == "reject":
                feed = PayrollFeedService.reject(
                    feed, reason=request.data.get("reason", ""), user=_request_user(request)
                )
            else:
                return Response({"detail": "action must be 'post' or 'reject'."},
                                status=status.HTTP_400_BAD_REQUEST)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_feed_payload(feed))


def _get_feed(batch_reference):
    try:
        return PayrollFeed.objects.get(batch_reference=batch_reference)
    except PayrollFeed.DoesNotExist:
        raise Http404(f"Payroll feed '{batch_reference}' not found.")


def _request_user(request):
    """Anonymous machine callers carry no creator/reviewer attribution."""
    return None if request.user.is_anonymous else request.user


def _feed_payload(feed):
    return {
        "batch_reference": feed.batch_reference,
        "schema_version": feed.schema_version,
        "period_start": feed.period_start.isoformat(),
        "period_end": feed.period_end.isoformat(),
        "entity": feed.entity,
        "segment": feed.segment.code if feed.segment else None,
        "cost_center": feed.cost_center,
        "net_pay_total": str(feed.net_pay_total),
        "er_share_total": str(feed.er_share_total),
        "remittance_total": str(feed.remittance_total),
        "status": feed.status,
        "validation_error": feed.validation_error,
        "journal_entry": feed.journal_entry.entry_no if feed.journal_entry else None,
    }