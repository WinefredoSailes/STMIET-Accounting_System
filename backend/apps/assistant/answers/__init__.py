"""Computed-answer dispatcher: catalog match -> RBAC gate -> handler run.

The dispatcher is intentionally small and deterministic:
  1. resolve entities from the parsed query;
  2. find the first catalog question that fires (phrases + entity needs);
  3. gate on the user's screen access (``effective_screens``);
  4. run the handler inside a guard so a faulty handler can never break the
     chat — on any error it falls back to the normal record search.

If no question fires, ``compute_answer`` returns None and the caller keeps
the pre-existing search pipeline untouched.
"""

from __future__ import annotations

import importlib
import logging

from apps.foundation.models import Company
from apps.ui.screens import SCREEN_LABELS, effective_screens

from ..catalog import CATEGORY_MODULES, match
from .base import Answer, denied
from .context import QContext, resolve_entities

logger = logging.getLogger(__name__)


def _resolve_handler(name: str):
    module_name, _, fn_name = name.partition(".")
    module = importlib.import_module(f"apps.assistant.answers.handlers.{module_name}")
    return getattr(module, fn_name)


def compute_answer(user, parsed, raw: str) -> Answer | None:
    lower = (raw or "").lower()
    companies = list(Company.objects.filter(is_active=True))

    entities = resolve_entities(user, parsed, raw, lower, companies)
    entry = match(lower, entities)
    if entry is None:
        return None

    screens = effective_screens(user)
    if entry.screen not in screens:
        return denied(entry.qid, SCREEN_LABELS.get(entry.screen, entry.screen))

    handler = _resolve_handler(entry.handler)
    terms = list(parsed.entities) + list(parsed.search_terms)
    ctx = QContext(
        user=user, raw=raw, lower=lower, terms=terms,
        companies=companies, entities=entities, entry=entry,
    )
    try:
        answer = handler(ctx, entities)
    except Exception:  # noqa: BLE001 — chat must never 500 on a bad handler
        logger.exception("computed answer handler failed for qid=%s", entry.qid)
        return None
    if answer is None:
        return None

    answer.qid = entry.qid
    if not answer.module:
        answer.module = CATEGORY_MODULES.get(entry.category, "assistant")
    return answer