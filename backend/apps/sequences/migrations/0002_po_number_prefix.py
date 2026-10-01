"""Give the PO document sequence its `PO-` prefix (ADR-042 numbering).

`DocumentSequence.next_number` only applies `pattern` when it CREATES a
sequence row (`get_or_create(defaults={"pattern": ...})`), so simply changing
the call site leaves every already-existing PO sequence row on the old
`{YYYY}-{SEQ:05d}` pattern. This backfills the stored pattern so the two
create paths (UI form and DRF viewset) cannot drift again.

Issued `PurchaseOrder.po_number` values are intentionally left untouched --
renumbering live documents would break references from the RFPs, assets and
audit trail that point at them.
"""

from django.db import migrations

OLD_PATTERN = "{YYYY}-{SEQ:05d}"
NEW_PATTERN = "PO-{YYYY}-{SEQ:05d}"


def forward(apps, schema_editor):
    DocumentSequence = apps.get_model("sequences", "DocumentSequence")
    DocumentSequence.objects.filter(
        form_code="PO", pattern=OLD_PATTERN
    ).update(pattern=NEW_PATTERN)


def backward(apps, schema_editor):
    DocumentSequence = apps.get_model("sequences", "DocumentSequence")
    DocumentSequence.objects.filter(
        form_code="PO", pattern=NEW_PATTERN
    ).update(pattern=OLD_PATTERN)


class Migration(migrations.Migration):
    dependencies = [
        ("sequences", "0001_initial"),
    ]

    operations = [migrations.RunPython(forward, backward)]
