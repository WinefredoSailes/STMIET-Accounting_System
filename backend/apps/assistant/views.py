from __future__ import annotations

import json
from datetime import timedelta

from django.db.models import Count, Avg, F
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.utils import timezone
from django.views import View
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from apps.core.approvals import get_approval_role
from .models import SearchLog
from .services import AssistantService


@method_decorator(csrf_exempt, name="dispatch")
class ChatView(View):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = AssistantService()

    def post(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        message = data.get("message", "").strip()
        session_id = data.get("session_id")

        if not message:
            return JsonResponse({"error": "Message is required"}, status=400)

        response = self.service.process_query(request.user, message, session_id)
        return JsonResponse(response)

    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)

        session_id = request.GET.get("session_id")
        if not session_id:
            greeting = self.service.get_greeting(request.user)
            return JsonResponse(greeting)

        history = self.service.get_history(session_id, request.user)
        return JsonResponse({"messages": history})


class AnalyticsView(View):
    def get(self, request):
        if not self._can_access(request.user):
            return render(request, "ui/403.html", status=403)

        days = int(request.GET.get("days", 7))
        cutoff = timezone.now() - timedelta(days=days)

        logs = SearchLog.objects.filter(created_at__gte=cutoff)

        total_queries = logs.count()
        successful_queries = logs.filter(result_count__gt=0).count()
        success_rate = (successful_queries / total_queries * 100) if total_queries > 0 else 0
        unique_users = logs.values("user").distinct().count()
        avg_response_time = logs.aggregate(avg=Avg("response_time_ms"))["avg"] or 0

        top_keywords = (
            logs.values("query")
            .annotate(count=Count("id"))
            .order_by("-count")[:20]
        )

        module_usage = {}
        for log in logs:
            for module in log.detected_modules:
                module_usage[module] = module_usage.get(module, 0) + 1

        sorted_modules = sorted(module_usage.items(), key=lambda x: x[1], reverse=True)

        no_result_queries = (
            logs.filter(result_count=0)
            .values("query")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )

        daily_usage = (
            logs.annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(count=Count("id"))
            .order_by("date")
        )

        context = {
            "days": days,
            "total_queries": total_queries,
            "success_rate": round(success_rate, 1),
            "unique_users": unique_users,
            "avg_response_time": round(avg_response_time, 0),
            "top_keywords": top_keywords,
            "module_usage": sorted_modules,
            "no_result_queries": no_result_queries,
            "daily_usage": daily_usage,
        }
        return render(request, "assistant/analytics.html", context)

    def _can_access(self, user) -> bool:
        if user.is_superuser:
            return True
        role = get_approval_role(user)
        return role in ("head", "coo")
