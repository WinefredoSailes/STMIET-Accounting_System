"""Seed the real petty-cash custodian funds (ADR-027) from the Sept 1, 2026
SUMMARY OF CASH beginning balance (CASH-SEPTEMBER-1-2026.xlsx).

The COA has a single shared 'Petty Cash Fund' account (10000). Each custodian
owns a PettyCashFund row (flexible per-custodian model, Phase-10 rebase) and
all funds point at 10000 via a ForeignKey — the aggregate PCF balance ties to
one GL while per-custodian float is tracked per fund. Idempotent: existing
fund codes are left untouched; re-runs are safe.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand

FUNDS = [
    # (fund_code, name, custodian_name, imprest)
    ("PCF-Ethelane", "Petty Cash - Ethelane O. Manuel", "Ethelane O. Manuel", "5000.00"),
    ("PCF-Leaslyn", "Petty Cash - Leaslyn L. Paghacian", "Leaslyn L. Paghacian", "10000.00"),
    ("PCF-Elleonor", "Petty Cash - Elleonor G. Quibong", "Elleonor G. Quibong", "10000.00"),
    ("PCF-Alywin", "Petty Cash - Alywin Aidan D. Baje", "Alywin Aidan D. Baje", "5000.00"),
]

PCF_GL = "10000"


class Command(BaseCommand):
    help = "Seed the real per-custodian petty cash funds (Sept 1, 2026 opening)."

    def handle(self, *args, **options):
        from apps.cash.models import PettyCashFund
        from apps.foundation.models import Account, Company

        company = Company.objects.first()
        if not company:
            self.stdout.write("skip: no company seeded yet (run import_coa first)")
            return
        account = Account.objects.filter(code=PCF_GL, is_postable=True).first()
        if account is None:
            self.stdout.write(f"skip: COA account {PCF_GL} not found (run import_coa first)")
            return

        created = 0
        for fund_code, name, custodian_name, imprest in FUNDS:
            if PettyCashFund.objects.filter(fund_code=fund_code).exists():
                continue
            PettyCashFund.objects.create(
                fund_code=fund_code,
                name=name,
                custodian_name=custodian_name,
                imprest_amount=Decimal(imprest),
                gl_account=account,
                company=company,
            )
            created += 1
            self.stdout.write(f"created {fund_code} -> {account.code} ({imprest})")
        self.stdout.write(self.style.SUCCESS(f"PCF funds seeded: {created} created."))
