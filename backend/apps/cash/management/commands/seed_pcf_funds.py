"""Seed the three imprest PCF funds (ADR-027) for whatever PCF GL accounts exist.

The COA master (COA-STMIET-2026.xlsx) defines one "Petty Cash Fund" account per
segment: 10000-DHPP / 10003-DMIE / 10006-OPS. Each fund needs its own unclaimed
asset GL account (OneToOne), so this seeds:
    PCF-General      -> DHPP  (custodian: first active user)
    PCF-Maintenance  -> DMIE
    PCF-Technical    -> OPS
and skips segments whose PCF GL account is missing from the COA. Idempotent:
existing fund codes are left untouched.
"""

from django.core.management.base import BaseCommand

FUNDS = [
    ("PCF-General", "General/Admin — office & general expenses", "DHPP"),
    ("PCF-Maintenance", "Maintenance — repairs & maintenance", "DMIE"),
    ("PCF-Technical", "Technical — allowances & field expenses", "OPS"),
]

IMPREST = "20000.00"


class Command(BaseCommand):
    help = "Seed the three ADR-027 imprest petty cash funds."

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model

        from apps.cash.models import PettyCashFund
        from apps.foundation.models import Account, Segment

        custodian = get_user_model().objects.filter(is_active=True).order_by("id").first()
        created = 0
        for fund_code, name, seg_code in FUNDS:
            if PettyCashFund.objects.filter(fund_code=fund_code).exists():
                continue
            segment = Segment.objects.filter(code=seg_code).first()
            if not segment:
                self.stdout.write(f"skip {fund_code}: segment {seg_code} not found")
                continue
            account = Account.objects.filter(
                code__startswith="1000", segment=seg_code, is_postable=True,
                pcf_fund__isnull=True,
            ).order_by("code").first()
            if not account:
                self.stdout.write(
                    f"skip {fund_code}: no unclaimed PCF GL account for {seg_code} "
                    f"(add e.g. 10003/10006 'Petty Cash Fund - {seg_code}' in COA/admin)"
                )
                continue
            PettyCashFund.objects.create(
                fund_code=fund_code,
                name=name,
                custodian=custodian,
                imprest_amount=IMPREST,
                gl_account=account,
                segment=segment,
            )
            created += 1
            self.stdout.write(f"created {fund_code} -> {account.code} ({seg_code})")
        self.stdout.write(self.style.SUCCESS(f"PCF funds seeded: {created} created."))
