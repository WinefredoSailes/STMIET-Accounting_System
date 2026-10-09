"""Hard-delete soft-removed attachments past their 7-year retention.

Usage: py manage.py purge_attachments [--dry-run]
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Purge DocumentAttachment rows past retain_until (bytes + rows)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from apps.core.models import DocumentAttachment

        today = timezone.now().date()
        qs = DocumentAttachment.objects.filter(is_deleted=True, retain_until__lte=today)
        count = qs.count()
        if opts["dry_run"]:
            self.stdout.write(f"Would purge {count} attachment(s).")
            return
        files = 0
        for att in qs.iterator():
            try:
                att.file.delete(save=False)
                files += 1
            except Exception:  # noqa: BLE001 - file may already be gone
                pass
            att.delete()
        self.stdout.write(f"Purged {count} attachment row(s), {files} file(s).")
