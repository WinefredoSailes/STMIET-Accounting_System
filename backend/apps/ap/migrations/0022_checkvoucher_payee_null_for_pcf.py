"""Allow CheckVoucher.payee to be NULL for PCF-sourced CVs (ACCTG-FOR-010).

PCF replenishments settle via a check voucher but don't have a Supplier payee
like RFP-based CVs do. The FK is made nullable so a PCF-backed CV can exist
without polluting the Supplier master data.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ap", "0021_purchaseorder_attachment_rfpdocument_attachment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="checkvoucher",
            name="payee",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cv",
                to="ap.supplier",
            ),
        ),
    ]
