"""Backfill statement-period fields on existing bank reconciliations.

Existing rows were created per weekly cycle (ADR-026): their statement period
is the cycle's own bounds and their frequency is weekly. The captured
unadjusted balances seed from the already-stored book/statement balances so
legacy rows behave as "captured". Idempotent and a no-op when empty.
"""

from django.db import migrations


def forward(apps, schema_editor):
    BankReconciliation = apps.get_model("cash", "BankReconciliation")
    for recon in BankReconciliation.objects.select_related("cycle").iterator():
        updates = {}
        if recon.period_start is None and recon.cycle_id:
            updates["period_start"] = recon.cycle.cycle_start
        if recon.period_end is None and recon.cycle_id:
            updates["period_end"] = recon.cycle.cycle_end
        if not recon.frequency:
            updates["frequency"] = "weekly"
        if recon.unadjusted_book_balance is None:
            updates["unadjusted_book_balance"] = recon.book_balance
        if recon.unadjusted_bank_balance is None:
            updates["unadjusted_bank_balance"] = recon.bank_statement_balance
        if not recon.is_balances_captured:
            updates["is_balances_captured"] = True
        if updates:
            for field, value in updates.items():
                setattr(recon, field, value)
            recon.save(update_fields=list(updates))


class Migration(migrations.Migration):

    dependencies = [
        ("cash", "0026_recon_statement_module"),
    ]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
