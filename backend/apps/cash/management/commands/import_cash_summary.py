"""Import the real bank + petty-cash master from the Sept 1, 2026 SUMMARY OF CASH
beginning balance (CASH-SEPTEMBER-1-2026.xlsx) — Phase-10 UAT re-base.

This is the data-driven way to seed the live/UAT chart from the finance-head's
file without hardcoding bank names in logic: each bank row is keyed by its
ACCOUNT NUMBER and mapped to an EXISTING 185-account COA cash GL. Idempotent:
re-runs update in place (update_or_create).

Handles the workbook's multi-row signatory cells: rows with a blank Bank column
carry additional signatory names for the preceding bank.

Usage:
    py manage.py import_cash_summary --file excel-files/CASH-SEPTEMBER-1-2026.xlsx
    py manage.py import_cash_summary --post-opening   # also post the opening JE

The `--post-opening` flag delegates to import_opening_balances with the parsed
beginning balances so the Sept 1 opening JE (Dr cash | Cr opening-equity) is
posted in the same pass (grand total from the file = 1,862,959.78).
"""

import csv
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.cash.models import BankAccount, BankAccountType
from apps.core.money import money
from apps.foundation.models import Account, Company

try:
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None

PCF_GL = "10000"

# Keyed by the file's ACCOUNT NUMBER -> (bank code, COA GL code, account_type).
# This is master-data (finance-head account numbers), not business logic.
BANK_MAP = {
    "0000009049586014": ("RCBC-SAV", "10090", BankAccountType.SAVINGS),   # RCBC
    "117602055064":     ("CHINA-SAV", "10100", BankAccountType.SAVINGS),  # Chinabank
    "001200042182":     ("KB-SAV", "10060", BankAccountType.SAVINGS),     # Katipunan Bank
    "121851059721":     ("PSBC-SAV", "10050", BankAccountType.SAVINGS),   # Producer's Savings (Savings)
    "121820002735":     ("PSBC-CHK", "10110", BankAccountType.CHECKING),  # Producer's Savings (Checking)
    "002160729468":     ("UNION-CHK", "10123", BankAccountType.CHECKING), # Union Bank (space-stripped)
    "412770005714":     ("PNB-CHK", "10040", BankAccountType.CHECKING),   # PNB 5714
    "412770007648":     ("PNB-7648", "10140", BankAccountType.CHECKING),  # PNB 7648 OPEX
    # "412770007693": PNB Savings 0.00 - no COA assigned yet; deliberately skipped.
    "1247124520238":    ("MB-CHK", "10080", BankAccountType.CHECKING),    # Metrobank
    "01521006505":      ("1VB-CHK", "10030", BankAccountType.CHECKING),   # First Valley Bank (1VB)
    "047430007632":     ("BDO-CHK", "10070", BankAccountType.CHECKING),   # BDO Network Bank
}

# The four Petty Cash custodians from the file (all share PCF_GL 10000).
PCF_FUNDS = [
    ("PCF-Ethelane", "Petty Cash - Ethelane O. Manuel", "Ethelane O. Manuel", "5000.00"),
    ("PCF-Leaslyn", "Petty Cash - Leaslyn L. Paghacian", "Leaslyn L. Paghacian", "10000.00"),
    ("PCF-Elleonor", "Petty Cash - Elleonor G. Quibong", "Elleonor G. Quibong", "10000.00"),
    ("PCF-Alywin", "Petty Cash - Alywin Aidan D. Baje", "Alywin Aidan D. Baje", "5000.00"),
]

SKIP_ACCOUNTS = {"412770007693"}  # PNB Savings (0.00) - no COA yet, unused.


def _clean(value):
    if value is None:
        return ""
    return str(value).strip()


def _acct_key(value):
    """Normalize an account number for keying (strip spaces/punctuation)."""
    return "".join(ch for ch in _clean(value) if ch.isdigit())


def _to_decimal(value):
    if value is None or value == "":
        return Decimal("0.00")
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    return Decimal(str(value).replace(",", ""))


class Command(BaseCommand):
    help = "Seed the real bank + PCF master from the Sept 1, 2026 Summary of Cash."

    def add_arguments(self, parser):
        parser.add_argument("--file", dest="file", default=None)
        parser.add_argument("--company", dest="company", default="STMIET")
        parser.add_argument("--post-opening", dest="post_opening", action="store_true",
                            help="Also post the Sept 1 opening JE via import_opening_balances.")

    def _resolve_file(self, options):
        file_path = Path(options["file"]) if options.get("file") else None
        if file_path is None or not file_path.exists():
            repo_root = Path(__file__).resolve().parents[5]
            for cand in (
                repo_root / "excel-files" / "CASH-SEPTEMBER-1-2026.xlsx",
                Path.cwd() / "excel-files" / "CASH-SEPTEMBER-1-2026.xlsx",
            ):
                if cand.exists():
                    file_path = cand
                    break
        if file_path is None or not file_path.exists():
            raise CommandError(
                "Summary of Cash not found. Pass --file, or place "
                "CASH-SEPTEMBER-1-2026.xlsx under /excel-files."
            )
        return file_path

    def _parse(self, file_path):
        """Return list of dicts: {kind, code, gl, name, acct_no, branch,
        signatories, amount, type} for banks and PCF rows."""
        if file_path.suffix.lower() == ".csv":
            rows = self._parse_csv(file_path)
        else:
            rows = self._parse_xlsx(file_path)
        return self._assemble(rows)

    def _parse_csv(self, file_path):
        with open(file_path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            return [list(r) for r in reader]

    def _parse_xlsx(self, file_path):
        if openpyxl is None:
            raise CommandError("openpyxl required for xlsx input; pip install openpyxl")
        wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
        sheet = wb.active
        return [list(r) for r in sheet.iter_rows(values_only=True)]

    def _assemble(self, grid):
        header_idx = None
        for i, row in enumerate(grid):
            upper = [_clean(v).upper() for v in row]
            if any("ACCOUNT NUMBER" in h for h in upper) and any(
                "BEGINNING" in h for h in upper
            ):
                header_idx = i
                break
        if header_idx is None:
            raise CommandError("No 'ACCOUNT NUMBER'/'BEGINNING BALANCES' header found.")

        header = [_clean(v).upper() for v in grid[header_idx]]
        col = {name: header.index(name) for name in header if _clean(name)}

        def c(row, name):
            idx = col.get(name)
            if idx is None or idx >= len(row):
                return ""
            return _clean(row[idx])

        items = []
        for row in grid[header_idx + 1:]:
            if not row or not any(_clean(v) for v in row):
                continue
            bank = c(row, "BANK")
            acct_raw = c(row, "ACCOUNT NUMBER")
            signatory = c(row, "SIGNATORIES")
            row_type = c(row, "TYPE")
            if bank and acct_raw:
                items.append({
                    "bank": bank,
                    "acct": _acct_key(acct_raw),
                    "acct_raw": acct_raw,
                    "branch": c(row, "BRANCH"),
                    "name": c(row, "ACCOUNT NAME"),
                    "type": row_type,
                    "amount": _to_decimal(c(row, "BEGINNING BALANCES")),
                    "signatories": [s for s in [signatory] if s],
                })
            elif bank and not acct_raw:
                # PCF fund header: bank name present but no account number.
                items.append({
                    "bank": bank, "acct": "", "acct_raw": "",
                    "branch": "", "name": c(row, "ACCOUNT NAME"),
                    "type": row_type,
                    "amount": _to_decimal(c(row, "BEGINNING BALANCES")),
                    "signatories": [s for s in [signatory] if s],
                })
            elif items and signatory:
                # Multi-row signatory continuation for the preceding bank.
                items[-1]["signatories"].append(signatory)
        return items

    @transaction.atomic
    def handle(self, *args, **options):
        file_path = self._resolve_file(options)
        company = Company.objects.filter(code=options["company"]).first()
        if company is None:
            raise CommandError(f"Company '{options['company']}' not found. Run import_coa first.")

        pcf_gl = Account.objects.filter(code=PCF_GL, is_postable=True).first()

        items = self._parse(file_path)
        bank_created = bank_updated = bank_skipped = 0
        opening_balances = []  # [(gl_code, debit_amount)] for the opening JE

        for it in items:
            acct = it["acct"]
            # Petty Cash rows -> PCF funds (share 10000).
            if it["bank"].upper() in ("PETTY CASH", "PCF") or (not acct):
                if pcf_gl is None:
                    self.stdout.write(self.style.WARNING(
                        "  PCF funds skipped: COA 10000 not found (run import_coa)."
                    ))
                    bank_skipped += 1
                    continue
                self._upsert_pcf_fund(it)
                opening_balances.append((PCF_GL, it["amount"]))
                continue

            if acct in SKIP_ACCOUNTS:
                self.stdout.write(self.style.WARNING(
                    f"  skip {it['bank']} {it['acct_raw']}: no COA account assigned yet (0.00)."
                ))
                bank_skipped += 1
                continue

            mapping = BANK_MAP.get(acct)
            if mapping is None:
                self.stdout.write(self.style.WARNING(
                    f"  skip {it['bank']} {it['acct_raw']}: no BANK_MAP entry for this account."
                ))
                bank_skipped += 1
                continue
            code, gl_code, account_type = mapping
            gl_account = Account.objects.filter(code=gl_code, is_postable=True).first()
            if gl_account is None:
                self.stdout.write(self.style.ERROR(
                    f"  {code}: COA account {gl_code} missing. Run import_coa first."
                ))
                bank_skipped += 1
                continue

            # Avoid the BankAccount.gl_account OneToOne collision: if any bank
            # already claims this GL account, update it in place (keeping its
            # code) rather than creating a conflicting new row.
            existing = BankAccount.objects.filter(gl_account=gl_account).first()
            target_code = existing.code if existing is not None else code

            _, was_created = BankAccount.objects.update_or_create(
                code=target_code,
                defaults={
                    "name": it["name"] or target_code,
                    "account_type": account_type,
                    "bank_name": it["bank"],
                    "bank_code": target_code.split("-")[0],
                    "account_number": it["acct_raw"],
                    "branch": it["branch"],
                    "signatories": it["signatories"],
                    "gl_account": gl_account,
                    "company": company,
                },
            )
            if was_created:
                bank_created += 1
            else:
                bank_updated += 1
            opening_balances.append((gl_code, it["amount"]))

        self.stdout.write(self.style.SUCCESS(
            f"import_cash_summary: {bank_created} banks created, {bank_updated} updated, "
            f"{bank_skipped} skipped. Opening total ~ {money(sum(a for _, a in opening_balances))}"
        ))

        if options["post_opening"]:
            self._post_opening(opening_balances, company)

    def _upsert_pcf_fund(self, it):
        from apps.cash.models import PettyCashFund
        from django.contrib.auth import get_user_model

        # Find-or-create a login account for the custodian so they can enter
        # petty-cash vouchers; link the fund's custodian FK to it. Real
        # employees get a temporary default password to be changed on first
        # login; the custodian_name text always stays authoritative.
        User = get_user_model()
        custodian = (it["name"] or it["bank"]).strip()
        user = self._get_or_create_custodian_user(custodian)

        # Deterministic, stable fund codes per known custodian; fall back to a
        # slug of the custodian name for any future custodian row.
        words = custodian.replace(",", " ").split()
        first = words[0] if words else "Custodian"
        fund_code = f"PCF-{first}"

        from apps.foundation.models import Account
        pcf_gl = Account.objects.filter(code=PCF_GL, is_postable=True).first()
        PettyCashFund.objects.update_or_create(
            fund_code=fund_code,
            defaults={
                "name": f"Petty Cash - {custodian}",
                "custodian_name": custodian,
                "custodian": user,
                "imprest_amount": it["amount"],
                "gl_account": pcf_gl,
                "company": Company.objects.first(),
            },
        )

    def _get_or_create_custodian_user(self, name):
        from django.contrib.auth import get_user_model
        from django.db.models import Q

        words = [w for w in name.replace(",", " ").split() if w]
        if not words:
            return None
        first_name = words[0]
        last_name = " ".join(words[1:]) if len(words) > 1 else ""
        username = first_name.lower()
        # Match by full name first (e.g. the existing 'alywin' user), then by
        # username, so we don't create duplicate accounts.
        User = get_user_model()
        user = User.objects.filter(
            Q(first_name__iexact=first_name, last_name__iexact=last_name)
            | Q(username__iexact=username)
        ).first()
        if user is not None:
            return user
        user = User(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email="",
        )
        user.set_password("ChangeMe-PCF-2026")  # temp; staff to reset on login
        user.is_staff = True
        user.is_active = True
        user.save()
        return user

    def _post_opening(self, opening_balances, company):
        from django.core.management import call_command
        from io import StringIO
        import csv as _csv
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as fh:
            writer = _csv.writer(fh)
            writer.writerow(["COA", "SEGMENT", "OPENING DR"])
            for gl_code, amount in opening_balances:
                if amount:
                    writer.writerow([gl_code, "", str(amount)])
            tmp = fh.name
        try:
            out = StringIO()
            call_command(
                "import_opening_balances", file=tmp, as_of="2026-09-01",
                entry_prefix="OB-SEP1", company=company.code, stdout=out,
            )
            self.stdout.write(out.getvalue())
        finally:
            Path(tmp).unlink(missing_ok=True)
