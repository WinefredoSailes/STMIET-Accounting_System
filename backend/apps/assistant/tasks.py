from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.core.scheduler import register_job


@register_job(
    "assistant_cleanup",
    crontab="0 2 * * *",
    label="Delete chat messages older than 7 days",
)
def cleanup_old_chat_messages() -> dict:
    from .models import ChatMessage

    cutoff = timezone.now() - timedelta(days=7)
    deleted, _ = ChatMessage.objects.filter(created_at__lt=cutoff).delete()
    return {"deleted": deleted}
