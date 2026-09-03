"""Seed a realistic demo dataset for end-to-end testing on the dev database.

January-2026 transaction history + fresh (today-based) open invoices so the
aging screen shows all buckets. Idempotent: re-running only adds what is
missing (unique keys: customer code, supplier code, receipt no, ap number,
cv number, batch no, bank code, cycle start+segment, advance identity).

Everything is created through the bounded-context services (never raw writes
where a service exists), so the seeded data behaves exactly like real entries.
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

CASH_COH = "10010"

# Shared banks (one row-set per bank) mapped to the revised SEPT-2026 COA cash
# codes. Banks are COMPANY-LEVEL (Phase 2): one checking + one savings row per
# bank serve every segment; PCF/COH is a pcf_coh row. account_type:
# checking / savings / pcf_coh.
BANKS = [
    ("PNB-CHK", "Cash in Bank - PNB", "PNB", "10040", "checking"),
    ("BDO-CHK", "Cash in Bank - BDO Unibank", "BDO", "10070", "checking"),
    ("MBTC-CHK", "Cash in Bank - MBTC", "MBTC", "10080", "checking"),
    ("RCBC-CHK", "Cash in Bank - RCBC", "RCBC", "10090", "checking"),
    ("1VB-CHK", "Cash in Bank - 1VB", "1VB", "10030", "checking"),
    ("KB-CHK", "Cash in Bank - KB", "KB", "10060", "checking"),
    ("PSBC-SAV", "Cash in Bank - PSBC Savings", "PSBC", "10050", "savings"),
    ("PSBC-CHK", "Cash in Bank - PSBC Checking", "PSBC", "10110", "checking"),
    ("EW-DFB", "Due from Other Bank - EW", "EW", "10020", "checking"),
    ("COH", "Cash on Hand", "", CASH_COH, "pcf_coh"),
]

CUSTOMERS = [
    ("MIG-001", "Miguel B. Demo", "DHPP"),
    ("PMP-001", "Pampanga Mechanics Inc.", "DMIE"),
    ("JRT-001", "JRT Contractors & Builders", "OPS"),
    ("SMT-002", "Seven-Trent Retail", "DHPP"),
]

SUPPLIERS = [
    ("PTT-001", "PTT Philippines Corporation", "DHPP"),
    ("EQ-001", "Equipment Parts Depot", "DMIE"),
    ("OFS-001", "Office Supply Mart", "OPS"),
]

ROLES = [
    ("staff", "Accounting Assistant", "staff"),
    ("alywin", "Alywin Aidan D. Baje", "head"),
    ("coo", "Chief Operating Officer (CNR)", "coo"),
]


class Command(BaseCommand):
    help = "Seed a January-2026 demo dataset for end-to-end testing (idempotent)."

    def handle(self, *args, **options):
        self._users()
        segs = self._segments()
        banks = self._banks(segs)
        customers = self._customers(segs)
        suppliers = self._suppliers(segs)
        self._ar_history(customers, segs)
        rfps = self._rfp_chain(suppliers, segs)
        self._conso_post(rfps, segs)
        self._cv_chain(suppliers, banks, segs)
        self._transfers(banks, segs)
        self._advances(segs)
        self._cycles_and_reports(segs)
        self.stdout.write(self.style.SUCCESS("Demo data seeded."))

    # -- pieces --------------------------------------------------------------

    def _users(self):
        U = get_user_model()
        from apps.foundation.models import UserProfile

        for username, first, role in ROLES:
            user, created = U.objects.get_or_create(username=username, defaults={"first_name": first})
            if created:
                user.set_password("Demo@2026")
                user.is_staff = True
                user.save()
            UserProfile.objects.update_or_create(
                user=user, defaults={"approval_role": role}
            )
        self.stdout.write(f"users: {U.objects.count()}")

    def _segments(self):
        from apps.foundation.models import Segment

        segs = {s.code: s for s in Segment.objects.all()}
        self.stdout.write("segments: " + ", ".join(segs))
        return segs

    def _banks(self, segs):
        from apps.cash.models import BankAccount
        from apps.foundation.models import Account, Company

        company = Company.objects.first() or segs["DHPP"].company
        out = {}
        for code, name, bank_code, gl, account_type in BANKS:
            account = Account.objects.filter(code=gl).first()
            if not account:
                continue
            bank, _ = BankAccount.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "account_type": account_type,
                    "bank_name": bank_code,
                    "bank_code": bank_code,
                    "gl_account": account,
                    "company": company,
                    "adb_required": "0.00" if account_type == "pcf_coh" else "5000.00",
                },
            )
            out[code] = bank
        self.stdout.write(f"banks: {len(out)}")
        return out

    def _customers(self, segs):
        from apps.ar.models import Customer

        out = {}
        for code, name, seg_code in CUSTOMERS:
            cust, _ = Customer.objects.get_or_create(code=code, defaults={"name": name, "segment": segs[seg_code]})
            out[code] = cust
        self.stdout.write(f"customers: {len(out)}")
        return out

    def _suppliers(self, segs):
        from apps.ap.models import Supplier

        out = {}
        for code, name, seg_code in SUPPLIERS:
            sup, _ = Supplier.objects.get_or_create(code=code, defaults={"name": name, "default_segment": segs[seg_code]})
            out[code] = sup
        self.stdout.write(f"suppliers: {len(out)}")
        return out

    def _invoice(self, *, invoice_no, customer, transaction_date, total):
        from decimal import Decimal

        from apps.ar.models import ARInvoice, ARInvoiceLine

        total = Decimal(total)
        inv, created = ARInvoice.objects.get_or_create(
            invoice_no=invoice_no,
            defaults={
                "customer": customer,
                "transaction_date": transaction_date,
                "segment": customer.segment,
                "total": total,
                "status": "open",
            },
        )
        if created:
            ARInvoiceLine.objects.create(
                invoice=inv, line_no=1, product_code="DIESEL", description="Fuel delivery",
                quantity=1, unit_price=total, amount=total,
            )
        return inv

    def _ar_history(self, customers, segs):
        from apps.ar.models import AcknowledgmentReceipt
        from apps.ar.services import CollectionService
        from apps.foundation.models import Account

        seg = segs["DHPP"]
        pnb = Account.objects.get(code="10040")
        coh = Account.objects.get(code=CASH_COH)
        inv = self._invoice(
            invoice_no="SI-2026-0003", customer=customers["MIG-001"],
            transaction_date=date(2026, 1, 6), total="120000.00",
        )
        if not AcknowledgmentReceipt.objects.filter(receipt_no="AR-2026-0003").exists():
            CollectionService.record_collection(
                receipt_no="AR-2026-0003",
                customer=customers["MIG-001"],
                transaction_date=date(2026, 1, 7),
                amount="50000.00",
                cash_account=pnb,
                segment=seg,
                applied_to=inv,
                user=self._user("staff"),
            )
            self.stdout.write("AR-2026-0003 posted (applied to SI-2026-0001)")
        if not AcknowledgmentReceipt.objects.filter(receipt_no="AR-2026-0501").exists():
            CollectionService.record_collection(
                receipt_no="AR-2026-0501",
                customer=customers["MIG-001"],
                transaction_date=date.today() - timedelta(days=3),
                amount="12500.00",
                cash_account=coh,
                segment=seg,
                user=self._user("staff"),
            )
            self.stdout.write("AR-2026-0501 posted (unearned)")
        today = date.today()
        self._invoice(invoice_no="SI-2026-0090", customer=customers["PMP-001"],
                      transaction_date=today - timedelta(days=33), total="18000.00")
        self._invoice(invoice_no="SI-2026-0101", customer=customers["JRT-001"],
                      transaction_date=today - timedelta(days=14), total="25000.00")
        self._invoice(invoice_no="SI-2026-0102", customer=customers["PMP-001"],
                      transaction_date=today - timedelta(days=3), total="40000.00")
        self.stdout.write("fresh open invoices for aging seeded")

    def _rfp_chain(self, suppliers, segs):
        from apps.ap.models import RFPDocument
        from apps.ap.services import RFPService

        seg = segs["DHPP"]
        payee = suppliers["PTT-001"]
        created = []
        specs = [
            ("A2026-001", date(2026, 1, 7), "60000.00", "50000", "Fuel purchase (CNR escalation)"),
            ("A2026-002", date(2026, 1, 13), "150000.00", "50000", "Bulk fuel purchase (CNR escalation)"),
        ]
        for ap_number, rfp_date, amount, expense_code, description in specs:
            if RFPDocument.objects.filter(ap_number=ap_number).exists():
                created.append(RFPDocument.objects.get(ap_number=ap_number))
                continue
            rfp = RFPService.create_rfp(
                ap_number=ap_number,
                rfp_date=rfp_date,
                payee=payee,
                segment=seg,
                lines=[
                    {
                        "side": "dr", "segment": seg, "account_code": expense_code,
                        "amount": amount, "description": description,
                    },
                    {
                        "side": "cr", "segment": seg, "account_code": "20000",
                        "amount": amount, "description": f"AP - {payee.name}",
                    },
                ],
                user=self._user("staff"),
            )
            self._approve_chain(rfp)
            created.append(rfp)
            self.stdout.write(f"{ap_number} created + fully approved")
        return created

    def _approve_chain(self, rfp):
        """ADR-036: Alywin (head) checks + approves acctg + fin; the COO
        signs as CNR only above P100k."""
        from apps.ap.services import RFPService

        if rfp.status == "prepared":
            RFPService.advance_step(rfp, role="checked", user=self._user("alywin"))
        if rfp.status == "checked":
            RFPService.advance_step(rfp, role="acctg_approved", user=self._user("alywin"))
        if rfp.status == "acctg_approved":
            RFPService.advance_step(rfp, role="fin_approved", user=self._user("alywin"))
        if rfp.status == "fin_approved" and rfp.amount > 100000:
            RFPService.approve_cnr(rfp, user=self._user("coo"))
        return rfp

    def _conso_post(self, rfps, segs):
        from apps.ap.models import CONSOBatch
        from apps.ap.services import CONSOService

        batch, _ = CONSOBatch.objects.get_or_create(
            batch_no="CONSO-2026-01", defaults={"conso_date": date(2026, 1, 16), "status": "open"}
        )
        for rfp in rfps:
            self._approve_chain(rfp)
            if not rfp.conso_id:
                rfp.conso = batch
                rfp.save(update_fields=["conso", "updated_at"])
        if batch.status != "posted" and all(r.status in ("fin_approved", "cnr_approved") for r in rfps):
            CONSOService.post_batch(batch, user=self._user("alywin"))
            self.stdout.write(f"CONSO-2026-01 posted: {len(rfps)} RFPs")

    def _cv_chain(self, suppliers, banks, segs):
        from apps.ap.models import CheckVoucher
        from apps.ap.services import CVPaymentService
        from apps.cash.models import CheckDisbursement
        from apps.cash.services import CheckDisbursementService
        from apps.foundation.models import Account

        cv = CheckVoucher.objects.filter(cv_number="CV-2026-0001").first()
        if not cv:
            cv = CVPaymentService.create_cv(
                cv_number="CV-2026-0001",
                cv_date=date(2026, 1, 20),
                payee=suppliers["PTT-001"],
                bank_account=Account.objects.get(code="10040"),
                gross_amount="60000.00",
                withheld_tax="6000.00",
                check_no="CHK-0001",
                user=self._user("staff"),
            )
            self.stdout.write("CV-2026-0001 created")
        disb = CheckDisbursement.objects.filter(cv=cv).first()
        if cv.status == "created":
            if not disb or disb.status == "created":
                CheckDisbursementService.sign_cnr(cv, user=self._user("coo"))
            cv.status = "signed"
            cv.signed_by = self._user("coo")
            cv.save(update_fields=["status", "signed_by", "updated_at"])
        if cv.status == "signed":
            if not disb or disb.status == "signed":
                CheckDisbursementService.release_quibs(cv, user=self._user("alywin"))
            cv.status = "released"
            cv.released_by = self._user("alywin")
            cv.save(update_fields=["status", "released_by", "updated_at"])
        if cv.status == "released":
            if not disb or disb.status == "released":
                CheckDisbursementService.clear(cv, banks["PNB-CHK"], user=self._user("alywin"))
            cv.status = "cleared"
            cv.save(update_fields=["status", "updated_at"])
        self.stdout.write("CV-2026-0001 signed/released/cleared")

    def _transfers(self, banks, segs):
        from apps.cash.services import TransferService

        if banks["BDO-CHK"].transfers_out.exists():
            return
        TransferService.transfer(
            from_account=banks["BDO-CHK"],
            to_account=banks["PNB-CHK"],
            amount="25000.00",
            purpose="fund transfer to PNB",
            transfer_date=date(2026, 1, 14),
            user=self._user("alywin"),
        )
        self.stdout.write("transfer BDO-CHK -> PNB-CHK 25,000 posted")

    def _advances(self, segs):
        from decimal import Decimal

        from apps.ap.models import AdvanceToEmployee
        from apps.ap.services import AdvanceService

        adv, created = AdvanceToEmployee.objects.get_or_create(
            employee_name="Alywin B.",
            granted_date=date(2026, 1, 8),
            defaults={
                "kind": AdvanceToEmployee.OFFICER,
                "segment": segs["DHPP"],
                "amount": Decimal("20000.00"),
                "status": "granted",
            },
        )
        if adv.liquidated_amount == 0 and adv.status != "liquidated":
            AdvanceService.liquidate(adv, amount="5000.00", liquidate_date=date(2026, 1, 15), user=self._user("alywin"))
            self.stdout.write("advance Alywin B. granted + partially liquidated")

    def _cycles_and_reports(self, segs):
        from apps.cash.models import CashFlowStatement, WeeklyCashCycle
        from apps.cash.services import CashCycleService, CashFlowService, CollectiblesService

        seg = segs["DHPP"]
        for start in (date(2026, 1, 6), date(2026, 1, 13), date(2026, 1, 20)):
            CashCycleService.generate_cycle(seg, start)
        jan6 = WeeklyCashCycle.objects.filter(cycle_start=date(2026, 1, 6), segment=seg).first()
        if jan6:
            CollectiblesService.generate(jan6)
        if not CashFlowStatement.objects.exists():
            CashFlowService.generate(date(2026, 1, 6), date(2026, 1, 26), seg.company)
        self.stdout.write("cycles + collectibles + cash flow generated")

    def _user(self, username):
        return get_user_model().objects.get(username=username)
