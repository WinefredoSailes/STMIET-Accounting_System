"""Seed/import base COA, companies, segments and fiscal calendar.

Usage:
    py manage.py import_coa --file excel-files/COA-STMIET-2026.xlsx --sheet COA
    py manage.py import_coa --company STMIET --fiscal-year 2026

Importing from the workbook is authoritative (PER REVIEW-ISSUES-RESOLUTIONS,
the COA file wins over the trial balance). Without a file, an empty COA is
seeded so the schema can be exercised in dev.
"""

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.foundation.models import Account, AccountType, Company, FiscalYear, Segment, SEGMENT_CHOICES

try:
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None


class Command(BaseCommand):
    help = "Seed companies, segments, fiscal calendar and the chart of accounts."

    def add_arguments(self, parser):
        parser.add_argument("--file", dest="file", default=None, help="COA xlsx path")
        parser.add_argument("--sheet", dest="sheet", default="COA")
        parser.add_argument("--company", dest="company", default="STMIET")
        parser.add_argument("--fiscal-year", dest="fiscal_year", default="2026")

    @transaction.atomic
    def handle(self, *args, **options):
        company, _ = Company.objects.get_or_create(
            code=options["company"],
            defaults={"name": "Seven-Trent Machineries Industrial Equipment Trading"},
        )
        segments = [
            ("DHPP", "Diesel & Heavy Parts Procurement", 0, company),
            ("DMIE", "Diesel Machinery & Industrial Equipment", 3, company),
            ("OPS", "Operations / Services", 6, company),
        ]
        for code, name, key, comp in segments:
            Segment.objects.get_or_create(code=code, defaults={"name": name, "coa_key_digit": key, "company": comp})

        fy, _ = FiscalYear.objects.get_or_create(
            company=company,
            code=options["fiscal_year"],
            defaults={"start_date": f"{options['fiscal_year']}-01-01", "end_date": f"{options['fiscal_year']}-12-31"},
        )

        file_path = Path(options["file"]) if options["file"] else None
        if file_path is None:
            self.stdout.write(self.style.WARNING("No --file given; COA left empty (foundation seeded)."))
            return

        if openpyxl is None:
            raise CommandError("openpyxl required; install with: pip install openpyxl")
        if not file_path.exists():
            raise CommandError(f"File not found: {file_path}")

        wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
        if options["sheet"] not in wb.sheetnames:
            raise CommandError(f"Sheet '{options['sheet']}' not in workbook.")
        ws = wb[options["sheet"]]

        # Tab-separated rows are also accepted (CSV with | delimiter).
        rows = []
        for row in ws.iter_rows(values_only=True):
            values = [str(v).strip() if v is not None else "" for v in row]
            rows.append(values)

        imported = 0
        for r in rows:
            if not r or not r[0]:
                continue
            code = r[0]
            if len(code) < 4 or not code.isdigit():
                continue
            name = r[1] if len(r) > 1 else ""
            # Explicit segment column (index 2) beats prefix derivation.
            segment = (r[2].strip().upper() if len(r) > 2 and r[2] else Account.segment_for_code(code))
            if segment not in dict(SEGMENT_CHOICES):
                segment = Account.segment_for_code(code)
            # The workbook's "major accounts" column is unreliable (it labels
            # expenses as Equity). Type is derived from the code prefix:
            # 1=Asset 2=Liability 3=Equity 4=Revenue 5/6=Expense.
            prefix = code[0]
            atype = {
                "1": AccountType.ASSET,
                "2": AccountType.LIABILITY,
                "3": AccountType.EQUITY,
                "4": AccountType.REVENUE,
                "5": AccountType.EXPENSE,
                "6": AccountType.EXPENSE,
            }.get(prefix, AccountType.ASSET)
            classification = r[3] if len(r) > 3 else ""
            category = r[4] if len(r) > 4 else ""
            sub_accounts = r[5] if len(r) > 5 else ""
            major_accounts = r[6] if len(r) > 6 else ""
            Account.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "account_type": atype,
                    "segment": segment,
                    "description": f"{classification} / {category}".strip(" /"),
                    "classification": classification,
                    "category": category,
                    "sub_accounts": sub_accounts,
                    "major_accounts": major_accounts,
                    "normal_balance": "debit" if atype in (AccountType.ASSET, AccountType.EXPENSE) else "credit",
                },
            )
            imported += 1

        self.stdout.write(self.style.SUCCESS(f"Imported {imported} accounts from {file_path.name} ({company.code})."))