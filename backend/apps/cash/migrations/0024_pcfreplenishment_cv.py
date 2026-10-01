"""Add CheckVoucher FK on PCFReplenishment (ACCTG-FOR-010).

Mirrors RFPDocument.rfp FK(CheckVoucher) so a posted PCF replenishment can
be settled with a check voucher. Each approved+posted PCF creates its own CV,
matching the current 1:1 batch-per-replenishment reality.
"""

import django.db.models.deletion
from django.db import migrations, models


def forward(apps, schema_editor):
    """Attach existing PCF→CONSO-posted vouchers to their CVs (none exist yet)."""
    pass  # no historical data to backfill


def backward(apps, schema_editor):
    pass  # reversible — just drops a nullable column


class Migration(migrations.Migration):

    dependencies = [
        ("ap", "0021_purchaseorder_attachment_rfpdocument_attachment"),
        ("cash", "0023_interaccounttransfer_cost_center"),
    ]

    operations = [
        migrations.AddField(
            model_name="pcfreplenishment",
            name="cv",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pcf_cvs",
                to="ap.checkvoucher",
            ),
            preserve_default=False,
        ),
    ]
