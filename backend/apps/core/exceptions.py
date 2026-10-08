"""Domain exceptions and the API exception handler (ADR-010: consistent errors)."""

import logging

from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class AccountingError(Exception):
    """Base class for all domain rule violations."""

    code = "accounting_error"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY


class PostingError(AccountingError):
    """Raised by the posting engine when an entry is not postable."""

    code = "posting_error"


class ValidationError(AccountingError):
    """Raised when an operation violates a business rule (before DB writes)."""

    code = "validation_error"


class UnbalancedEntryError(PostingError):
    """Raised when a JE's debits != credits.

    Per ADR-002 the system never force-balances: it surfaces the difference
    for human reconciliation instead of silently adjusting.
    """

    code = "unbalanced_entry"


def api_exception_handler(exc, context):
    """Maps domain exceptions to stable, documented API error shapes."""
    if isinstance(exc, AccountingError):
        return Response(
            {"detail": exc.message, "code": exc.code},
            status=exc.status_code,
        )
    if isinstance(exc, IntegrityError):
        # Duplicate document numbers (sequence lag / allocation races) and
        # other constraint conflicts: a retryable 400, never a 500.
        logger.warning("API integrity conflict: %s", exc)
        return Response(
            {
                "detail": "This record conflicts with an existing one — please retry.",
                "code": "conflict",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    return drf_exception_handler(exc, context)
