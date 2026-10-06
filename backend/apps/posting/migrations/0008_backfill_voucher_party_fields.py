# Backfill voucher header party/refs (ACCTG-FOR-012) on existing entries.
#
# JEs created before supplier_name/po/ref_number were populated by the AR
# builders (and before reverse() copied them) render "—" on je_detail.
# This fills blanks from the linked source document, then copies originals
# onto their REV-* mirrors. Entries that already carry values are untouched.

from django.db import migrations


def _party(customer):
    owner = (customer.owner_name or "").strip()
    text = f"{customer.name} — {owner}" if owner else (customer.name or "")
    return text[:255]


def backfill(apps, schema_editor):
    JournalEntry = apps.get_model("posting", "JournalEntry")
    Receipt = apps.get_model("ar", "AcknowledgmentReceipt")
    SI = apps.get_model("ar", "ARInvoice")
    SSI = apps.get_model("ar", "SpecialSalesInvoice")

    # 1) Originals: AR / SI / SSI entries with a blank party, resolved via
    # the source-doc reverse FKs (receipt.journal_entry etc.).
    for je in JournalEntry.objects.filter(supplier_name="").exclude(entry_no__startswith="REV-").only(
        "id", "source_doc_type", "source_doc_no", "supplier_name", "po", "ref_number"
    ):
        stype, sno = (je.source_doc_type or "").upper(), je.source_doc_no or ""
        if stype == "AR":
            doc = Receipt.objects.select_related("customer").filter(journal_entry_id=je.id).first()
            if doc is None and sno:
                doc = Receipt.objects.select_related("customer").filter(receipt_no=sno).first()
            if doc is None:
                continue
            je.supplier_name = _party(doc.customer)
            if not je.po:
                je.po = (doc.ref_po_no or "")[:128]
            if not je.ref_number:
                je.ref_number = (doc.transaction_no or doc.check_no or "")[:128]
            je.save(update_fields=["supplier_name", "po", "ref_number"])
        elif stype == "SI":
            doc = SI.objects.select_related("customer").filter(journal_entry_id=je.id).first()
            if doc is None and sno:
                doc = SI.objects.select_related("customer").filter(invoice_no=sno).first()
            if doc is None:
                continue
            je.supplier_name = _party(doc.customer)
            je.save(update_fields=["supplier_name"])
        elif stype == "SSI":
            doc = SSI.objects.select_related("customer").filter(journal_entry_id=je.id).first()
            if doc is None and sno:
                doc = SSI.objects.select_related("customer").filter(invoice_no=sno).first()
            if doc is None:
                continue
            je.supplier_name = _party(doc.customer)
            if not je.ref_number:
                je.ref_number = (doc.delivery_receipt_no or "")[:128]
            je.save(update_fields=["supplier_name", "ref_number"])

    # 2) Reversals: blank REV-* entries inherit from the original sharing
    # the same reversal_token (reverse() stamps both sides).
    for rev in JournalEntry.objects.filter(supplier_name="", entry_no__startswith="REV-").only(
        "id", "reversal_token", "supplier_name", "po", "ref_number"
    ):
        if not rev.reversal_token:
            continue
        orig = (
            JournalEntry.objects.filter(reversal_token=rev.reversal_token)
            .exclude(pk=rev.pk)
            .exclude(entry_no__startswith="REV-")
            .only("supplier_name", "po", "ref_number")
            .first()
        )
        if orig is None or not orig.supplier_name:
            continue
        rev.supplier_name = orig.supplier_name
        rev.po = orig.po
        rev.ref_number = orig.ref_number
        rev.save(update_fields=["supplier_name", "po", "ref_number"])


class Migration(migrations.Migration):

    dependencies = [
        ("posting", "0007_reversalrequest"),
        ("ar", "0012_receipt_billing_link"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
