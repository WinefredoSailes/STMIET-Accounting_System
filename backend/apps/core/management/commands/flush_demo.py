"""Remove all transactional/demo data while preserving the foundation.

Keeps: Company, Segment, FiscalYear, FiscalPeriod, Account, UserProfile,
auth User (so login still works after a reset).

Removes: all journal entries + general ledger, AR, AP, cash/banks, PCF,
assets, fleet, reporting statements/templates, sequences, workflow
approvals — i.e. every day-to-day transaction record.

The result is a clean slate ready for a fresh COA import, so the accounting
team can validate the revised chart of accounts without demo residue.

Deletion order is derived at runtime: at every step we delete the rows of a
model that no (still pending) model PROTECT/RESTRICT-references. Self-referential
PROTECT keys (e.g. StatementLineDef.parent) are unwound by deleting rows
child-first (rows nobody references as a parent) until the table is empty,
because PROTECT raises at collection time even when the whole table is in the
deletion set.

Usage:
    py manage.py flush_demo [--assume-yes]
"""

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.deletion import PROTECT, RESTRICT

# Foundation models are intentionally EXCLUDED and preserved:
#   Company, Segment, FiscalYear, FiscalPeriod, Account, UserProfile, auth.User
# Every other model in the transaction apps is flushed. The list below only
# guards the scope; order is computed dynamically in ``handle``.
FLUSH_LABELS = [
    "posting:PostingRuleLine",
    "posting:PostingRule",
    "posting:GeneralLedger",
    "posting:JournalEntryLine",
    "posting:JournalEntry",
    "reporting:MonthEndClose",
    "reporting:FinancialStatement",
    "reporting:StatementLineDef",
    "reporting:StatementTemplate",
    "workflow:ApprovalAction",
    "workflow:ApprovalRequest",
    "cash:CheckDisbursement",
    "cash:CashShortExcessWorksheet",
    "cash:CollectiblesWorksheet",
    "cash:CashFlowStatement",
    "cash:InterAccountTransfer",
    "cash:PCFReplenishment",
    "cash:PettyCashFund",
    "cash:BankReconciliation",
    "cash:CashCycleActivity",
    "cash:WeeklyCashCycle",
    "cash:BankAccount",
    "assets:AssetDisposal",
    "assets:DepreciationSchedule",
    "assets:Asset",
    "assets:AssetCategory",
    "fleet:Vehicle",
    "ap:AdvanceToEmployee",
    "ap:CheckVoucher",
    "ap:CONSOBatch",
    "ap:RFPLine",
    "ap:RFPDocument",
    "ap:Supplier",
    "ar:CashShortExcess",
    "ar:Deposit",
    "ar:ARInvoiceLine",
    "ar:ARInvoice",
    "ar:AcknowledgmentReceipt",
    "ar:PriceSnapshot",
    "ar:Customer",
    "sequences:DocumentSequence",
]


class Command(BaseCommand):
    help = "Remove all transactional/demo data, preserving the foundation (company, segments, COA, users)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--assume-yes",
            action="store_true",
            help="Do not prompt for confirmation.",
        )

    @staticmethod
    def _restrict_keys():
        return (PROTECT, RESTRICT)

    @staticmethod
    def _other_model_protect_refs(target, pending):
        """Return True if any *other* pending model PROTECT/RESTRICT-references target.

        Self-references (the target PROTECT-referencing itself) are excluded
        here: those are unwound child-first inside ``_delete_model_rows``.
        """
        for model in pending:
            if model is target:
                continue
            for f in model._meta.concrete_fields:
                if (
                    f.is_relation
                    and f.related_model is target
                    and f.remote_field.on_delete in Command._restrict_keys()
                ):
                    return True
        return False

    @staticmethod
    def _delete_model_rows(model):
        """Delete every row of *model*, handling self-referential PROTECT keys."""
        qs = getattr(model, "all_objects", model.objects)
        if not qs.exists():
            return 0

        self_refs = [
            f
            for f in model._meta.concrete_fields
            if f.is_relation
            and f.related_model is model
            and f.remote_field.on_delete in Command._restrict_keys()
        ]

        if not self_refs:
            return qs.all().delete()[0]

        # Self-referencing PROTECT: remove leaves first (rows that are not
        # referenced as a parent by any surviving row), repeating until empty.
        total = 0
        while qs.exists():
            referenced_ids = set()
            for f in self_refs:
                fk_col = f.attname  # e.g. 'parent_id'
                referenced_ids |= set(
                    qs.exclude(**{f"{fk_col}__isnull": True}).values_list(fk_col, flat=True)
                )
            leaves = qs.exclude(pk__in=referenced_ids)
            if not leaves.exists():
                raise RuntimeError(
                    f"Circular self-referential PROTECT keys in {model.__name__}; "
                    "cannot flush."
                )
            total += leaves.delete()[0]
        return total

    @transaction.atomic
    def handle(self, *args, **options):
        if not options["assume_yes"]:
            answer = input(
                "This permanently deletes ALL transactional/demo data "
                "(journal entries, AR/AP, cash, assets, reporting). "
                "Foundation (COA, segments, users) is kept. Continue? [y/N] "
            ).strip().lower()
            if answer not in ("y", "yes"):
                self.stdout.write(self.style.WARNING("Aborted."))
                return

        pending = set()
        skipped = []
        for label in FLUSH_LABELS:
            app_label, model_name = label.split(":")
            try:
                pending.add(django_apps.get_model(app_label, model_name))
            except Exception:
                skipped.append(label)

        total = 0
        rounds = 0
        while pending:
            rounds += 1
            if rounds > 10_000:
                raise RuntimeError("Flush did not converge on deletion order.")
            progressed = False
            for model in sorted(pending, key=lambda m: m.__name__):
                if Command._other_model_protect_refs(model, pending):
                    continue
                count = Command._delete_model_rows(model)
                total += count
                pending.discard(model)
                progressed = True
                self.stdout.write(f"  {model._meta.app_label}:{model.__name__:25} {count}")
            if not progressed:
                remaining = ", ".join(
                    sorted(m.__name__ for m in pending)
                )
                raise RuntimeError(
                    f"Circular PROTECT/RESTRICT dependencies among: {remaining}"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Flushed {total} records. Foundation kept "
                "(company, segments, fiscal calendar, COA, users)."
            )
        )
        for skipped_label in skipped:
            self.stdout.write(self.style.WARNING(f"  skip (no model): {skipped_label}"))