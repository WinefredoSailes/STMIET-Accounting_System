"""Backfill JE audit-log rows for Journal Entries that predate audit logging.

The JE-scoped ActionLog rows (``created``/``approved``/``posted`` and the
reversal chain) are only written by the posting lifecycle going forward. This
command replays them for already-existing entries from the data models so the
merged doc+JE audit trail (cv/transfer/billing detail screens) reads complete
for historical documents too.

Idempotent: only inserts rows that are missing for a given entry; re-running
is a no-op. ``posted`` is stamped from ``approved_at`` (or the approving
reversal request's timestamp for reversal mirrors); entries with no reliable
posting timestamp are skipped and reported.

Usage:
    python manage.py backfill_je_audit_trail
"""

from django.core.management.base import BaseCommand

from apps.ap.models import ActionLog


class Command(BaseCommand):
    help = "Backfill JE audit-trail ActionLog rows for existing Journal Entries (idempotent)."

    def handle(self, *args, **options):
        from apps.posting.models import JournalEntry, PostingStatus, ReversalRequest

        scans = {
            "created": 0,
            "approved": 0,
            "posted": 0,
            "reversal_requested": 0,
            "reversal_approved": 0,
            "reversal_rejected": 0,
        }
        skipped = 0
        scanned = 0

        for entry in JournalEntry.objects.order_by("id").iterator():
            scanned += 1
            existing = set(
                ActionLog.objects.filter(
                    doc_type=ActionLog.DocType.JE, doc_id=entry.id
                ).values_list("action", flat=True)
            )

            def _insert(action, actor, when, note=""):
                if when is None or action in existing:
                    return
                row = ActionLog.objects.create(
                    doc_type=ActionLog.DocType.JE,
                    doc_id=entry.id,
                    action=action,
                    actor=actor,
                    note=note,
                )
                ActionLog.objects.filter(pk=row.pk).update(created_at=when)
                existing.add(action)
                scans[action] += 1

            _insert("created", entry.created_by, entry.created_at)
            if entry.approved_by_id and entry.approved_at:
                _insert("approved", entry.approved_by, entry.approved_at)

            # Reversal chain (fully timestamped on the request row itself).
            for req in entry.reversal_requests.order_by("id"):
                _insert(
                    "reversal_requested",
                    req.requested_by,
                    req.requested_at,
                    note=req.reason,
                )
                if req.status == ReversalRequest.Status.APPROVED:
                    _insert(
                        "reversal_approved",
                        req.approved_by,
                        req.approved_at,
                        note=req.reason,
                    )
                elif req.status == ReversalRequest.Status.REJECTED:
                    _insert(
                        "reversal_rejected",
                        req.rejected_by,
                        req.rejected_at,
                        note=req.reject_note,
                    )

            # Posted stamp: posting follows approval; for a reversal mirror the
            # posting time is the approving request's timestamp; for a transfer
            # the JE posts the moment the head approves the FTV.
            if entry.status in (PostingStatus.POSTED, PostingStatus.REVERSED) and "posted" not in existing:
                mirror_request = entry.reversal_of_requests.first()
                when = actor = None
                if mirror_request is not None:
                    when, actor = mirror_request.approved_at, mirror_request.approved_by
                elif entry.approved_at:
                    when, actor = entry.approved_at, entry.approved_by
                else:
                    from apps.cash.models import InterAccountTransfer

                    transfer = InterAccountTransfer.objects.filter(journal_entry=entry).first()
                    if transfer is not None:
                        when, actor = transfer.approved_at, transfer.approved_by
                if when is None:
                    skipped += 1
                else:
                    _insert("posted", actor, when)

        self.stdout.write(
            self.style.SUCCESS(
                f"backfill done: {scanned} entries scanned "
                f"(created={scans['created']} approved={scans['approved']} "
                f"posted={scans['posted']} "
                f"reversal_requested={scans['reversal_requested']} "
                f"reversal_approved={scans['reversal_approved']} "
                f"reversal_rejected={scans['reversal_rejected']} "
                f"posted_skipped={skipped})"
            )
        )