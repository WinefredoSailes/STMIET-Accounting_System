# Data migration: collapse the old five approval roles into the three
# STMIET positions (staff / head / coo). Per the org structure:
#   checker, cashier -> staff (same access)
#   acctg, fin       -> head (Accounting & Finance Head is one person)
#   cnr              -> coo  (CNR is the COO)

from django.db import migrations, models


def forward(apps, schema_editor):
    UserProfile = apps.get_model("foundation", "UserProfile")
    UserProfile.objects.filter(approval_role="checker").update(approval_role="staff")
    UserProfile.objects.filter(approval_role="cashier").update(approval_role="staff")
    UserProfile.objects.filter(approval_role="acctg").update(approval_role="head")
    UserProfile.objects.filter(approval_role="fin").update(approval_role="head")
    UserProfile.objects.filter(approval_role="cnr").update(approval_role="coo")


def backward(apps, schema_editor):
    UserProfile = apps.get_model("foundation", "UserProfile")
    UserProfile.objects.filter(approval_role="staff").update(approval_role="checker")
    UserProfile.objects.filter(approval_role="head").update(approval_role="acctg")
    UserProfile.objects.filter(approval_role="coo").update(approval_role="cnr")


class Migration(migrations.Migration):

    dependencies = [
        ("foundation", "0003_user_approval_profiles"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userprofile",
            name="approval_role",
            field=models.CharField(
                blank=True,
                choices=[
                    ("staff", "Accounting Staff / Assistant / Bookkeeper / Cashier"),
                    ("head", "Accounting & Finance Head"),
                    ("coo", "COO (CNR)"),
                ],
                default="",
                max_length=16,
            ),
        ),
        migrations.RunPython(forward, backward),
    ]
