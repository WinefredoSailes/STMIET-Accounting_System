from __future__ import annotations

import time
import uuid

from django.core.cache import cache

from .models import ChatSession, ChatMessage, SearchLog
from .parser.query_parser import QueryParser
from .parser.intent_router import IntentRouter
from .formatter.response_formatter import ResponseFormatter
from .answers import compute_answer
from .executors.ap_executor import APExecutor
from .executors.ar_executor import ARExecutor
from .executors.posting_executor import PostingExecutor
from .executors.cash_executor import CashExecutor
from .executors.asset_executor import AssetExecutor
from .executors.billing_executor import BillingExecutor
from .executors.fleet_executor import FleetExecutor
from .executors.payroll_executor import PayrollExecutor
from .executors.tax_executor import TaxExecutor
from .executors.inventory_executor import InventoryExecutor
from .executors.workflow_executor import WorkflowExecutor
from .executors.reporting_executor import ReportingExecutor
from .executors.foundation_executor import FoundationExecutor


EXECUTOR_MAP = {
    "ap": APExecutor,
    "ar": ARExecutor,
    "posting": PostingExecutor,
    "cash": CashExecutor,
    "assets": AssetExecutor,
    "billing": BillingExecutor,
    "fleet": FleetExecutor,
    "payroll": PayrollExecutor,
    "tax": TaxExecutor,
    "inventory": InventoryExecutor,
    "workflow": WorkflowExecutor,
    "reporting": ReportingExecutor,
    "foundation": FoundationExecutor,
}

# Group labels that are master-data lists (not transactions). Used to decide
# when a date-windowed named search should retry without the window.
MASTER_LABELS = {
    "Suppliers", "Customers", "Bank Accounts", "Petty Cash Funds",
    "COA Accounts", "Companies", "Assets", "Vehicles",
}


class AssistantService:
    def __init__(self):
        self.parser = QueryParser()
        self.router = IntentRouter()
        self.formatter = ResponseFormatter()

    def process_query(self, user, message: str, session_id: str | None = None) -> dict:
        start_time = time.time()

        session = None
        if session_id:
            session = ChatSession.objects.filter(
                session_id=session_id, user=user
            ).first()
        if session is None:
            session = ChatSession.objects.create(user=user, session_id=uuid.uuid4())

        ChatMessage.objects.create(
            session=session,
            role=ChatMessage.Role.USER,
            content=message,
        )

        # Cache only the lookup outcome, scoped to the user, so a repeat
        # question is fast without leaking another user's results and
        # without skipping history/search logging. The cache stores
        # (results, date_relaxed, answer_block) as a dict; older entries from
        # before computed answers stored a bare 2-tuple and are read
        # gracefully.
        cache_key = f"assistant:query:{user.pk}:{hash(message.lower().strip())}"
        cached = cache.get(cache_key)

        if cached is not None:
            if isinstance(cached, dict):
                results = cached.get("results", [])
                date_relaxed = cached.get("date_relaxed", False)
                answer_block = cached.get("answer")
            else:
                results, date_relaxed = cached
                answer_block = None
        else:
            parsed = self.parser.parse(message)
            answer_block = None
            date_relaxed = False

            # Computed answers first: when a catalog question fires, its
            # answer replaces the record search (the handler already embeds
            # supporting rows/links). None -> the pre-existing search chains.
            answer = compute_answer(user, parsed, message)
            if answer is not None:
                answer_block = answer.to_block()
                results = []
            else:
                results = self._collect(user, parsed, [i.module for i in self.router.route(parsed.keywords, parsed.intent)])

                # Smart fallback 1: a named entity found nothing in the
                # guessed module(s) -> sweep every module the user can see.
                if not results and parsed.search_terms:
                    results = self._collect(user, parsed, list(EXECUTOR_MAP.keys()))

                # Smart fallback 2: a date-windowed search came back empty, or
                # only returned master rows (a supplier/customer, no document).
                # Time phrasing is fuzzy ("earlier this week", "this month")
                # and the requested window may simply be empty, so drop the
                # window and retry.
                had_date = parsed.date_from or parsed.date_to
                only_master = bool(results) and all(g["label"] in MASTER_LABELS for g in results)
                if had_date and (not results or only_master):
                    parsed.date_from = None
                    parsed.date_to = None
                    retry_modules = (
                        list(EXECUTOR_MAP.keys()) if parsed.search_terms or only_master
                        else [i.module for i in self.router.route(parsed.keywords, parsed.intent)]
                    )
                    retried = self._collect(user, parsed, retry_modules)
                    if retried:
                        results = retried
                        date_relaxed = True

            cache.set(
                cache_key,
                {"results": results, "date_relaxed": date_relaxed, "answer": answer_block},
                timeout=300,
            )

        language = self.formatter.language_detector.detect(message)
        response = self.formatter.format_response(
            results,
            language=language,
            query_text=message,
            date_relaxed=date_relaxed,
            answer=answer_block,
        )

        ChatMessage.objects.create(
            session=session,
            role=ChatMessage.Role.ASSISTANT,
            content=response["text"],
            results=response["results"],
            answer=response.get("answer_block") or {},
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        SearchLog.objects.create(
            user=user,
            query=message,
            detected_language=language,
            detected_modules=(
                [answer_block.get("module", "assistant")] if answer_block
                else ([g["module"] for g in results] or ["none"])
            ),
            result_count=(
                (len(answer_block.get("rows", [])) or len(answer_block.get("metrics", [])))
                if answer_block
                else sum(r.get("count", 0) for r in results)
            ),
            response_time_ms=elapsed_ms,
        )

        response["session_id"] = str(session.session_id)
        return response

    def get_greeting(self, user) -> dict:
        return self.formatter.get_greeting()

    def _collect(self, user, parsed, module_names) -> list[dict]:
        results: list[dict] = []
        for module in module_names:
            executor_class = EXECUTOR_MAP.get(module)
            if not executor_class:
                continue
            exec_result = executor_class(user, parsed).execute()
            for group in exec_result.groups:
                results.append({
                    "module": group.module,
                    "label": group.label,
                    "count": group.count,
                    "items": group.items,
                })
        return results

    def get_history(self, session_id: str, user) -> list[dict]:
        try:
            session = ChatSession.objects.get(session_id=session_id, user=user)
        except ChatSession.DoesNotExist:
            return []

        messages = session.messages.all()[:50]
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "results": msg.results,
                "answer": msg.answer,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in messages
        ]
