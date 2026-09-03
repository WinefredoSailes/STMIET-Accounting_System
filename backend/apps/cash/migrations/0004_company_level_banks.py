# Phase 2: banks & PCF funds become COMPANY-LEVEL master data.
# Existing rows were segment-scoped (per-segment duplicates); point each row at
# its segment's company, drop the segment FK, and require company. Single-company
# assumption holds for the prototype (all segments belong to the same company).

import django.db.models.deletion
from django.db import migrations, models


def make_company_level(apps, schema_editor):
    Company = apps.get_model("foundation", "Company")
    BankAccount = apps.get_model("cash", "BankAccount")
    PettyCashFund = apps.get_model("cash", "PettyCashFund")

    company = Company.objects.order_by("id").first()
    if company is None and (BankAccount.objects.exists() or PettyCashFund.objects.exists()):
        # Integrity fallback: never leave a non-null company FK dangling.
        company = Company.objects.create(
            code="STMIET", name="Ss. Trinity Multi-Industry & Energy Tech."
        )
    company_id = company.pk if company else None

    for model in (BankAccount, PettyCashFund):
        for obj in model.objects.filter(company__isnull=True).select_related("segment"):
            if obj.segment is not None and obj.segment.company_id:
                obj.company_id = obj.segment.company_id
            else:
                obj.company_id = company_id
            obj.save(update_fields=["company"])


class Migration(migrations.Migration):

    dependencies = [
        ("cash", "0003_pcfreplenishment_payee_name_and_more"),
        ("foundation", "0005_company_cash_cycle_company_cycle_end_weekday_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="bankaccount",
            name="company",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bank_accounts",
                to="foundation.company",
            ),
        ),
        migrations.AddField(
            model_name="pettycashfund",
            name="company",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pcf_funds",
                to="foundation.company",
            ),
        ),
        migrations.RunPython(make_company_level, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="bankaccount",
            name="segment",
        ),
        migrations.RemoveField(
            model_name="pettycashfund",
            name="segment",
        ),
        migrations.AlterField(
            model_name="bankaccount",
            name="company",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bank_accounts",
                to="foundation.company",
            ),
        ),
        migrations.AlterField(
            model_name="pettycashfund",
            name="company",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pcf_funds",
                to="foundation.company",
            ),
        ),
    ]