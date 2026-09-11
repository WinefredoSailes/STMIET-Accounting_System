import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posting", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="journalentryline",
            name="segment",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="je_lines", to="foundation.segment",
            ),
        ),
    ]
