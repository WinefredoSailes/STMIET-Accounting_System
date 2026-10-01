"""Backfill GL account titles into stored PCF replenishment expense lines.

Before the name-capture fix, expense lines were persisted with only
``account_code``, so the voucher detail screen showed a bare code instead of
``63800 Petron``. New saves (create, draft-edit, revise) now store the title,
and the detail view resolves legacy rows live from the chart of accounts;
this migration repairs the stored JSON itself so exports and snapshots agree
with what the UI renders.

Only lines that still carry an ``account_code`` without an ``account_name``
are touched, so existing titles are left alone. Idempotent, and a no-op on
databases with no legacy vouchers. Runs automatically on deploy via the
entrypoint's ``migrate --run-sync`` (ADR-040), mirroring the transfer-
description (cash 0018) and PO-prefix (sequences 0002) data backfills.
"""

from django.db import migrations


def forward(apps, schema_editor):
    PCFReplenishment = apps.get_model("cash", "PCFReplenishment")
    Account = apps.get_model("foundation", "Account")

    name_by_code = dict(Account.objects.values_list("code", "name"))
    for replen in PCFReplenishment.objects.iterator():
        expenses = list(replen.expenses or [])
        updated = False
        for exp in expenses:
            code = exp.get("account_code") or ""
            if code and not exp.get("account_name") and name_by_code.get(code):
                exp["account_name"] = name_by_code[code]
                updated = True
        if updated:
            replen.expenses = expenses
            replen.save(update_fields=["expenses"])


class Migration(migrations.Migration):

    dependencies = [
        ("cash", "0021_alter_pcfreplenishment_status"),
        ("foundation", "0001_initial"),
    ]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
