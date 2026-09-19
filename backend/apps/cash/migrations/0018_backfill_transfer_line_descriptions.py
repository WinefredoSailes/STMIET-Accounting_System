"""Backfill per-line descriptions on existing inter-account transfer JEs.

Before the fix, ``TransferService.transfer()`` wrote generic
``"Transfer to <code>"`` / ``"Transfer from <code>"`` placeholders on the
JournalEntryLine rows, so the FTV Account Distribution and the JE detail
screen never showed the purpose the user actually entered. This migration
rewrites those placeholder rows to the parent transfer's ``purpose``.

Only rows still carrying the exact placeholder text are touched, so any
hand-edited description is left alone. The operation is idempotent and a
no-op on databases with no legacy transfers (e.g. fresh test DBs).
"""

from django.db import migrations


def forward(apps, schema_editor):
    InterAccountTransfer = apps.get_model("cash", "InterAccountTransfer")
    JournalEntryLine = apps.get_model("posting", "JournalEntryLine")

    updated = 0
    transfers = InterAccountTransfer.objects.select_related(
        "from_account", "to_account"
    ).filter(journal_entry__isnull=False)
    for transfer in transfers:
        purpose = transfer.purpose or ""
        placeholders = {
            f"Transfer to {transfer.to_account.code}",
            f"Transfer from {transfer.from_account.code}",
        }
        updated += JournalEntryLine.objects.filter(
            entry_id=transfer.journal_entry_id,
            description__in=placeholders,
        ).update(description=purpose)


class Migration(migrations.Migration):

    dependencies = [
        ("cash", "0017_alter_interaccounttransfer_purpose"),
        ("posting", "0001_initial"),
    ]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]