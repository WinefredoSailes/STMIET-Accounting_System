"""Seed the three imprest PCF funds (ADR-027) for whatever PCF GL accounts exist.

The COA master (CHART-OF-ACCOUNTS_REVISED-SEPT-2026.xlsx) has a single shared
"Petty Cash Fund" account (10000). Funds are company-level (Phase 2); each fund
needs its own unclaimed asset GL account (OneToOne), so three funds share the
company and are distinguished by fund_code. Segments retain the historical
fund->segment affinity via the funds' GL accounts where per-segment PCF accounts
still exist. Idempotent: existing fund codes are left untouched.
"""

from django.core.management.base import BaseCommand

FUNDS = [
    ("PCF-General", "General/Admin — office & general expenses"),
    ("PCF-Maintenance", "Maintenance — repairs & maintenance"),
    ("PCF-Technical", "Technical — allowances & field expenses"),
]

IMPREST = "20000.00"


class Command(BaseCommand):
    help = "Seed the three ADR-027 imprest petty cash funds."

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model

        from apps.cash.models import PettyCashFund
        from apps.foundation.models import Account, Company

        company = Company.objects.first()
        if not company:
            self.stdout.write("skip: no company seeded yet (run import_coa first)")
            return
        custodian = get_user_model().objects.filter(is_active=True).order_by("id").first()
        created = 0
        for fund_code, name in FUNDS:
            if PettyCashFund.objects.filter(fund_code=fund_code).exists():
                continue
            account = Account.objects.filter(
                code__startswith="1000", is_postable=True, pcf_fund__isnull=True,
            ).order_by("code").first()
            if not account:
                self.stdout.write(
                    f"skip {fund_code}: no unclaimed PCF GL account "
                    f"(add e.g. 10000 'Petty Cash Fund' in COA/admin)"
                )
                continue
            PettyCashFund.objects.create(
                fund_code=fund_code,
                name=name,
                custodian=custodian,
                imprest_amount=IMPREST,
                gl_account=account,
                company=company,
            )
            created += 1
            self.stdout.write(f"created {fund_code} -> {account.code}")
        self.stdout.write(self.style.SUCCESS(f"PCF funds seeded: {created} created."))