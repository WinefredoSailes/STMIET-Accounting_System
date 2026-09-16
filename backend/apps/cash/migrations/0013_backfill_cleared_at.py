from django.db import migrations


def forward(apps, schema_editor):
    CheckDisbursement = apps.get_model("cash", "CheckDisbursement")
    updated = 0
    for disb in CheckDisbursement.objects.filter(cleared_at__isnull=True):
        cv = disb.cv
        # Use the CV's approved_at date (chronologically correct: clearing
        # happens after approval), falling back to the CV's cv_date.
        if cv.approved_at:
            disb.cleared_at = cv.approved_at
        elif cv.cv_date:
            disb.cleared_at = cv.cv_date
        else:
            disb.cleared_at = timezone.now()
        disb.save(update_fields=["cleared_at"])
        updated += 1


class Migration(migrations.Migration):
    dependencies = [
        ("cash", "0012_interaccounttransfer_voucher_no"),
    ]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]