"""Inventory integration bridge API (BUILD-PLAN Phase 5).

Machine-to-machine intake for the separate live inventory system (ADR-004,
ADR-009). `InventoryEventIngestView` accepts a POST with an idempotent event
and books the resulting JE into the GL; a status view exposes the queue and
a retry action reprocesses FAILED events (offline-tolerant handling).

Authentication: the endpoint is machine-to-machine; individual app settings
may pin it behind token auth. Validation errors map to 400 with the reason in
`detail`; the caller can retry.
"""

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import ValidationError

from .models import InventoryEvent, InventoryEventStatus, InventoryEventType
from .services import InventoryBridgeService


class InventoryEventIngestView(APIView):
    """POST /api/v1/inventory/events/ — ingest one inventory event (idempotent)."""

    permission_classes = [AllowAny]

    def post(self, request):
        payload = request.data or {}
        try:
            event_type = payload["event_type"]
            event_key = str(payload["event_key"])
            segment_code = payload["segment"]
            occurred_on = payload["occurred_on"]
            body = payload.get("payload") or {}
        except KeyError as exc:
            return Response(
                {"detail": f"Missing required field: {exc.args[0]}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if event_type not in InventoryEventType.values:
            return Response(
                {"detail": f"Unsupported event_type '{event_type}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            event = InventoryBridgeService.ingest(
                event_key=event_key, event_type=event_type,
                segment_code=segment_code, occurred_on=occurred_on, payload=body,
            )
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 - surfaced for retry
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        code = status.HTTP_201_CREATED
        if event.status == InventoryEventStatus.DUPLICATE:
            code = status.HTTP_200_OK
        elif event.status == InventoryEventStatus.FAILED:
            code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return Response(
            {
                "id": str(event.id),
                "event_key": event.event_key,
                "event_type": event.event_type,
                "status": event.status,
                "journal_entry": event.journal_entry.entry_no if event.journal_entry else None,
            },
            status=code,
        )


class InventoryEventStatusView(APIView):
    """GET /api/v1/inventory/events/ — list the intake queue (filterable)."""

    permission_classes = [AllowAny]

    def get(self, request):
        qs = InventoryEvent.objects.select_related("segment", "journal_entry")
        event_status = request.query_params.get("status")
        if event_status:
            qs = qs.filter(status=event_status)
        segment = request.query_params.get("segment")
        if segment:
            qs = qs.filter(segment__code=segment)
        events = qs.order_by("-occurred_on")[:100]
        return Response(
            [
                {
                    "id": str(e.id),
                    "event_key": e.event_key,
                    "event_type": e.event_type,
                    "segment": e.segment.code,
                    "occurred_on": e.occurred_on.isoformat(),
                    "status": e.status,
                    "retry_count": e.retry_count,
                    "error_message": e.error_message,
                    "journal_entry": e.journal_entry.entry_no if e.journal_entry else None,
                }
                for e in events
            ]
        )


class InventoryEventRetryView(APIView):
    """POST /api/v1/inventory/events/retry/ — reprocess failed events."""

    permission_classes = [AllowAny]

    def post(self, request):
        segment_code = (request.data or {}).get("segment")
        processed = InventoryBridgeService.run_retry_queue(segment=segment_code)
        return Response(
            {
                "reprocessed": len(processed),
                "statuses": [e.status for e in processed],
            }
        )