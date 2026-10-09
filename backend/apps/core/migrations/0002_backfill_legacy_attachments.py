# Backfill legacy single-file evidence (RFP/PO/Deposit/Receipt) into
# DocumentAttachment as live row #1. Idempotent: skips docs that already
# have a live generic row with the same file name.
import mimetypes
import os

from django.db import migrations


def _backfill_model(apps, model_label, legacy_field, upload_prefix):
    ContentType = apps.get_model("contenttypes", "ContentType")
    DocumentAttachment = apps.get_model("core", "DocumentAttachment")
    app_label, model_name = model_label.split(".")
    Model = apps.get_model(app_label, model_name)
    try:
        ctype = ContentType.objects.get(app_label=app_label, model=model_name.lower())
    except Exception:  # noqa: BLE001 - content type table not seeded
        return 0
    rows = 0
    for obj in Model.objects.exclude(**{f"{legacy_field}": ""}).exclude(
        **{f"{legacy_field}__isnull": True}
    ).iterator():
        legacy_name = getattr(obj, legacy_field, None)
        name = getattr(legacy_name, "name", "") or str(legacy_name or "")
        if not name:
            continue
        exists = DocumentAttachment.objects.filter(
            content_type_id=ctype.pk, object_id=obj.pk, is_deleted=False, file=name
        ).exists()
        if exists:
            continue
        seg = getattr(obj, "segment", None)
        comp = getattr(seg, "company", None) if seg else getattr(obj, "company", None)
        # created_by may not exist on older rows; be defensive.
        uploader = getattr(obj, "created_by", None)
        size = 0
        try:
            size = getattr(obj, legacy_field).size or 0
        except Exception:  # noqa: BLE001 - missing file on disk
            size = 0
        mime, _ = mimetypes.guess_type(name)
        DocumentAttachment.objects.create(
            content_type_id=ctype.pk,
            object_id=obj.pk,
            file=name,  # same stored file, no byte duplication
            original_name=os.path.basename(name)[:255],
            size=size,
            mime=(mime or "")[:128],
            uploaded_by=uploader,
            created_by=uploader,
            segment=seg if getattr(seg, "pk", None) else None,
            company=comp if getattr(comp, "pk", None) else None,
        )
        rows += 1
    return rows


def forwards(apps, schema_editor):
    total = 0
    total += _backfill_model(apps, "ap.RFPDocument", "attachment", "rfp_supporting/")
    total += _backfill_model(apps, "ap.PurchaseOrder", "attachment", "po_supporting/")
    total += _backfill_model(apps, "ar.Deposit", "attachment", "ar_deposits/")
    total += _backfill_model(apps, "ar.AcknowledgmentReceipt", "attachment", "ar_attachments/")
    if total:
        print(f"Backfilled {total} legacy attachment(s) into DocumentAttachment.")


def backwards(apps, schema_editor):
    # Legacy FileFields are kept (read-only display), so reverse is a no-op:
    # generic rows remain as the canonical evidence.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_documentattachment"),
        ("ap", "0026_advance_recon_memorandum"),
        ("ar", "0012_receipt_billing_link"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
