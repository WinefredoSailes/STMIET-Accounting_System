# Memorandum redesign: AdvanceReconciliation drops verified-balance/memo/JE-link
# fields in favour of AdvanceReconEntry rows; workflow becomes
# draft -> submitted -> approved (reject returns to draft).

from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ap', '0025_alter_actionlog_doc_type'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AdvanceReconEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('date', models.DateField(db_index=True)),
                ('description', models.CharField(max_length=500)),
                ('amount', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=18)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('recon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='entries', to='ap.advancereconciliation')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['date', 'id'],
            },
        ),
        migrations.RemoveField(
            model_name='advancereconciliation',
            name='adjustment_je',
        ),
        migrations.RemoveField(
            model_name='advancereconciliation',
            name='locked_by',
        ),
        migrations.RemoveField(
            model_name='advancereconciliation',
            name='locked_at',
        ),
        migrations.RemoveField(
            model_name='advancereconciliation',
            name='memo',
        ),
        migrations.RemoveField(
            model_name='advancereconciliation',
            name='reviewed_at',
        ),
        migrations.RemoveField(
            model_name='advancereconciliation',
            name='reviewed_balance',
        ),
        migrations.RemoveField(
            model_name='advancereconciliation',
            name='reviewed_by',
        ),
        migrations.AddField(
            model_name='advancereconciliation',
            name='approved_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='advancereconciliation',
            name='approved_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='advancereconciliation',
            name='rejected_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='advancereconciliation',
            name='rejected_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='advancereconciliation',
            name='rejection_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='advancereconciliation',
            name='submitted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='advancereconciliation',
            name='submitted_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='advancereconciliation',
            name='status',
            field=models.CharField(choices=[('draft', 'Draft'), ('submitted', 'Submitted'), ('approved', 'Approved'), ('rejected', 'Rejected')], db_index=True, default='draft', max_length=16),
        ),
    ]
