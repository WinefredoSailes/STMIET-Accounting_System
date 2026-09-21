"""Seed the "unbilled" non-trade receivable accounts 15550 / 15560.

The live server already carries these; this migration brings local/dev
databases to parity. It only CREATES a missing account (``get_or_create``) so
an existing live row is never overwritten.

Values mirror the COA workbook row and the sibling 15xxx accounts:
    15550  Reimbursable Expenses—Unbilled   (Non-Trade Receivables / Other Current Asset)
    15560  Due from Customers—Unbilled      (Non-Trade Receivables / Other Current Asset)
Both are debit-normal current assets, shared (segment ALL).
"""

from django.db import migrations

ACCOUNTS = [
    {
        "code": "15550",
        "name": "Reimbursable Expenses—Unbilled",
        "account_type": "asset",
        "normal_balance": "debit",
        "segment": "ALL",
        "classification": "Non-Trade Receivables",
        "category": "Other Current Asset",
        "sub_accounts": "Current Assets",
        "major_accounts": "Assets",
        "behavior": "",
        "traceability": "",
        "controllability": "",
        "is_control": False,
        "is_postable": True,
    },
    {
        "code": "15560",
        "name": "Due from Customers—Unbilled",
        "account_type": "asset",
        "normal_balance": "debit",
        "segment": "ALL",
        "classification": "Non-Trade Receivables",
        "category": "Other Current Asset",
        "sub_accounts": "Current Assets",
        "major_accounts": "Assets",
        "behavior": "",
        "traceability": "",
        "controllability": "",
        "is_control": False,
        "is_postable": True,
    },
]


def seed(apps, schema_editor):
    Account = apps.get_model("foundation", "Account")
    for row in ACCOUNTS:
        defaults = {k: v for k, v in row.items() if k != "code"}
        Account.objects.get_or_create(code=row["code"], defaults=defaults)


def unseed(apps, schema_editor):
    Account = apps.get_model("foundation", "Account")
    Account.objects.filter(code__in=[r["code"] for r in ACCOUNTS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0001_initial"),
        ("foundation", "0001_initial"),
    ]

    operations = [migrations.RunPython(seed, unseed)]