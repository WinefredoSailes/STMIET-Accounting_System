"""AR contract tests (BUILD-PLAN Phase 2).

- collection posts the single `cash.collection` JE (Dr Cash | Cr Unearned)
- collection applied to prior AR posts Cr AR with no double-booking
- deposit is a state change with NO JE (ADR-016)
- cycle ledger derives cumulative over/(short) (ADR-013)
- aging buckets 30/60/90/120+
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.ar.models import (
    AcknowledgmentReceipt,
    ARInvoice,
    ARInvoiceLine,
    Customer,
    Deposit,
    DepositLine,
    ReceiptStatus,
)
from apps.ar.services import CollectionService, CycleLedgerService, DepositService
from apps.foundation.models import Account, Company, Segment
from apps.core.exceptions import ValidationError
from apps.foundation.calendar import cycle_range_for
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus

from django.core.management import call_command
from io import StringIO


@pytest.fixture
def customer(db, segment, company):
    return Customer.objects.create(code="C001", name="ABC Trading")


@pytest.fixture
def bank_account(db, accounts):
    return accounts["10010"]


@pytest.fixture
def invoice(db, customer, segment, accounts):
    inv = ARInvoice.objects.create(
        invoice_no="SI-2026-0001",
        customer=customer,
        transaction_date=date(2026, 1, 15),
        segment=segment,
        total=Decimal("5000.00"),
    )
    ARInvoiceLine.objects.create(
        invoice=inv, line_no=1, product_code="DIESEL",
        description="Diesel fuel", quantity=Decimal("100"), unit_price=Decimal("50.00"),
        amount=Decimal("5000.00"),
    )
    return inv


class TestCollectionPosting:
    def test_collection_posts_unearned_je(self, customer, bank_account, segment):
        receipt = CollectionService.record_collection(
            receipt_no="AR-2026-00001",
            customer=customer,
            transaction_date=date(2026, 1, 15),
            amount="1000.00",
            cash_account=bank_account,
            segment=segment,
        )
        receipt.refresh_from_db()
        assert receipt.journal_entry is not None
        je = receipt.journal_entry
        assert je.status == PostingStatus.POSTED
        assert je.is_balanced
        lines = {l.line_no: l for l in je.lines.all()}
        # Dr cash, Cr unearned 21000 (DHPP segment).
        assert lines[1].debit == Decimal("1000.00")
        assert lines[2].credit == Decimal("1000.00")
        assert lines[2].account.code == "21000"

    def test_collection_applied_to_invoice_credits_ar(self, customer, bank_account, segment, invoice):
        receipt = CollectionService.record_collection(
            receipt_no="AR-2026-00002",
            customer=customer,
            transaction_date=date(2026, 1, 16),
            amount="3000.00",
            cash_account=bank_account,
            applied_to=invoice,
            segment=segment,
        )
        je = receipt.journal_entry
        line2 = je.lines.get(line_no=2)
        assert line2.account.code.startswith("120")  # AR account, not Unearned
        invoice.refresh_from_db()
        assert invoice.status == "partially_paid"
        assert invoice.balance == Decimal("2000.00")

    def test_full_payment_marks_invoice_paid(self, customer, bank_account, segment, invoice):
        CollectionService.record_collection(
            receipt_no="AR-2026-00003",
            customer=customer,
            transaction_date=date(2026, 1, 16),
            amount="5000.00",
            cash_account=bank_account,
            applied_to=invoice,
            segment=segment,
        )
        invoice.refresh_from_db()
        assert invoice.status == "paid"

    def test_invalid_customer_on_applied_invoice_rejected(self, customer, bank_account, segment, invoice):
        other = Customer.objects.create(code="C002", name="Other Co")
        with pytest.raises(ValidationError):
            CollectionService.record_collection(
                receipt_no="AR-2026-00004",
                customer=other,
                transaction_date=date(2026, 1, 16),
                amount="100.00",
                cash_account=bank_account,
                applied_to=invoice,
                segment=segment,
            )

    def test_over_application_rejected(self, customer, bank_account, segment, invoice):
        # ADR-049 polish: applying more than the outstanding balance would
        # hide a phantom prepayment inside a "paid" invoice.
        with pytest.raises(ValidationError, match="exceeds the outstanding balance"):
            CollectionService.record_collection(
                receipt_no="AR-2026-00009",
                customer=customer,
                transaction_date=date(2026, 1, 16),
                amount="6000.00",
                cash_account=bank_account,
                applied_to=invoice,
                segment=segment,
            )
        invoice.refresh_from_db()
        assert invoice.status == "open"

    def test_update_draft_over_application_rejected(self, customer, bank_account, segment, invoice):
        from apps.ar.services import segment_ar_account

        draft = CollectionService.create_receipt(
            customer=customer,
            transaction_date=date(2026, 1, 16),
            cash_account=bank_account,
            amount="3000.00",
            segment=segment,
            applied_to=invoice,
        )
        ar = segment_ar_account(segment)
        with pytest.raises(ValidationError, match="exceeds the outstanding balance"):
            CollectionService.update_draft(
                receipt=draft,
                lines=[
                    {"account": bank_account, "segment": segment, "debit": "6000.00", "credit": "0"},
                    {"account": ar, "segment": segment, "debit": "0", "credit": "6000.00"},
                ],
            )

    def test_zero_amount_rejected(self, customer, bank_account, segment):
        with pytest.raises(ValidationError):
            CollectionService.record_collection(
                receipt_no="AR-2026-00005",
                customer=customer,
                transaction_date=date(2026, 1, 16),
                amount="0.00",
                cash_account=bank_account,
                segment=segment,
            )


class TestDepositMultiBank:
    """Multi-bank distribution + JE posting for deposits."""

    def test_deposit_with_two_banks_posts_correct_je(self, customer, segment, role_users, accounts):
        seg = segment
        # Use existing 10110 (BDO Checking) as bank1; create second bank 10020.
        bank1 = accounts["10110"]
        bank2 = Account.objects.create(code="10020", name="Cash in Bank MBTC", is_postable=True)

        user = role_users["staff"]
        head = role_users["head"]

        receipt = CollectionService.create_receipt(
            customer=customer,
            transaction_date=date(2026, 1, 15),
            amount="115000.00",
            cash_account=bank1,
            segment=seg,
            created_by=user,
        )
        assert receipt.status == ReceiptStatus.DRAFT
        # Post it first
        CollectionService.submit(receipt, user=user)
        CollectionService.approve(receipt, user=head)
        receipt.refresh_from_db()
        assert receipt.status == ReceiptStatus.POSTED
        assert receipt.journal_entry_id is not None

        # Deposit across two banks.
        dist = [
            {"account": bank1.pk, "amount": "100000.00"},
            {"account": bank2.pk, "amount": "15000.00"},
        ]
        dep = DepositService.record_deposit(
            receipts=[receipt],
            bank_account=bank1,
            transaction_date=date(2026, 1, 20),
            user=head,
            distribution=dist,
        )
        assert dep.amount == Decimal("115000.00")
        assert dep.lines.count() == 2
        line1 = dep.lines.filter(line_no=1).first()
        line2 = dep.lines.filter(line_no=2).first()
        assert line1.account_id == bank1.pk
        assert line1.debit == Decimal("100000.00")
        assert line2.account_id == bank2.pk
        assert line2.debit == Decimal("15000.00")

        je = dep.journal_entry
        assert je.source_doc_type == "DEP"
        assert je.total_debit == Decimal("115000.00")
        assert je.total_credit == Decimal("115000.00")
        assert je.is_posted
        # Two debit lines (one per bank) + one credit line (COH).
        debit_lines = list(je.lines.filter(debit__gt=0))
        credit_lines = list(je.lines.filter(credit__gt=0))
        assert len(debit_lines) == 2
        assert sum(l.debit for l in debit_lines) == Decimal("115000.00")
        assert len(credit_lines) == 1
        assert credit_lines[0].credit == Decimal("115000.00")

    def test_deposit_distribution_mismatch_raises(self, customer, segment, role_users, accounts):
        seg = segment
        bank1 = accounts["10110"]
        _ = Account.objects.create(code="10020", name="Cash in Bank MBTC", is_postable=True)

        user = role_users["staff"]
        head = role_users["head"]

        receipt = CollectionService.create_receipt(
            customer=customer,
            transaction_date=date(2026, 1, 15),
            amount="10000.00",
            cash_account=bank1,
            segment=seg,
            created_by=user,
        )
        CollectionService.submit(receipt, user=user)
        CollectionService.approve(receipt, user=head)
        receipt.refresh_from_db()
        assert receipt.status == ReceiptStatus.POSTED

        # Sums to less than total -> should raise ValidationError.
        with pytest.raises(ValidationError):
            DepositService.record_deposit(
                receipts=[receipt],
                bank_account=bank1,
                transaction_date=date(2026, 1, 20),
                user=head,
                distribution=[{"account": bank1.pk, "amount": "9000.00"}],
            )

    def test_deposit_single_bank_backwards_compat(self, customer, segment, role_users, accounts):
        seg = segment
        bank1 = accounts["10110"]

        user = role_users["staff"]
        head = role_users["head"]

        receipt = CollectionService.create_receipt(
            customer=customer,
            transaction_date=date(2026, 1, 15),
            amount="5000.00",
            cash_account=bank1,
            segment=seg,
            created_by=user,
        )
        CollectionService.submit(receipt, user=user)
        CollectionService.approve(receipt, user=head)
        receipt.refresh_from_db()
        assert receipt.status == ReceiptStatus.POSTED

        # No distribution -> falls back to single bank.
        dep = DepositService.record_deposit(
            receipts=[receipt],
            bank_account=bank1,
            transaction_date=date(2026, 1, 20),
            user=head,
        )
        assert dep.lines.count() == 1
        assert dep.lines.first().debit == Decimal("5000.00")

    def _post_receipt(self, customer, segment, bank, amount, user, head):
        receipt = CollectionService.create_receipt(
            customer=customer,
            transaction_date=date(2026, 1, 15),
            amount=amount,
            cash_account=bank,
            segment=segment,
            created_by=user,
        )
        CollectionService.submit(receipt, user=user)
        CollectionService.approve(receipt, user=head)
        receipt.refresh_from_db()
        assert receipt.status == ReceiptStatus.POSTED
        return receipt

    def test_deposit_batch_two_receipts_one_je(self, customer, segment, role_users, accounts):
        user = role_users["staff"]
        head = role_users["head"]
        bank1 = accounts["10110"]
        bank2 = Account.objects.create(code="10020", name="Cash in Bank MBTC", account_type="asset")
        customer2 = Customer.objects.create(code="C002", name="Second Client")

        r1 = self._post_receipt(customer, segment, bank1, "115000.00", user, head)
        r2 = self._post_receipt(customer2, segment, bank1, "5000.00", user, head)

        dep = DepositService.record_deposit(
            receipts=[r1, r2],
            bank_account=None,
            transaction_date=date(2026, 1, 20),
            user=head,
            distribution=[
                {"account": bank1.pk, "amount": "100000.00"},
                {"account": bank2.pk, "amount": "20000.00"},
            ],
        )
        assert dep.amount == Decimal("120000.00")
        assert dep.lines.count() == 2
        je = dep.journal_entry
        assert je.total_debit == Decimal("120000.00") == je.total_credit
        assert je.lines.filter(debit__gt=0).count() == 2
        # Same segment -> one grouped Cash on Hand credit.
        credit_lines = list(je.lines.filter(credit__gt=0))
        assert len(credit_lines) == 1
        assert credit_lines[0].credit == Decimal("120000.00")
        r1.refresh_from_db()
        r2.refresh_from_db()
        assert r1.deposit_id == dep.pk
        assert r2.deposit_id == dep.pk

    def test_deposit_mixed_company_rejected(self, customer, segment, company, role_users, accounts):
        user = role_users["staff"]
        bank1 = accounts["10110"]
        company2 = Company.objects.create(code="OTHER", name="Other Company")
        seg2 = Segment.objects.create(code="DMIE", name="Other Segment", company=company2)
        Account.objects.create(code="21023", name="Unearned Revenue - DMIE", account_type="liability")

        r1 = CollectionService.create_receipt(
            customer=customer,
            transaction_date=date(2026, 1, 15),
            amount="10000.00",
            cash_account=bank1,
            segment=segment,
            created_by=user,
        )
        customer2 = Customer.objects.create(code="C002", name="Second Client")
        r2 = CollectionService.create_receipt(
            customer=customer2,
            transaction_date=date(2026, 1, 15),
            amount="5000.00",
            cash_account=bank1,
            segment=seg2,
            receipt_no="AR-2026-0099",
            created_by=user,
        )
        with pytest.raises(ValidationError):
            DepositService.record_deposit(
                receipts=[r1, r2],
                bank_account=bank1,
                transaction_date=date(2026, 1, 20),
                user=user,
                distribution=[{"account": bank1.pk, "amount": "15000.00"}],
            )


class TestCycleLedger:
    def test_cumulative_over_short_derivation(self, customer, bank_account, segment):
        # Cycle 1: billed 5000, paid 3000 -> short -2000, cumulative -2000.
        inv1 = ARInvoice.objects.create(
            invoice_no="SI-2026-0010", customer=customer,
            transaction_date=date(2026, 1, 13), segment=segment, total=Decimal("5000.00"),
        )
        CollectionService.record_collection(
            receipt_no="AR-2026-00010", customer=customer,
            transaction_date=date(2026, 1, 14), amount="3000.00",
            cash_account=bank_account,
            segment=segment,
        )
        # Cycle 2 (Tue 01-20): paid 4000 -> over +4000, cumulative +2000.
        CollectionService.record_collection(
            receipt_no="AR-2026-00011", customer=customer,
            transaction_date=date(2026, 1, 21), amount="4000.00",
            cash_account=bank_account,
            segment=segment,
        )

        rows = CycleLedgerService.for_customer(customer)
        assert len(rows) == 2
        assert rows[0]["over_short"] == Decimal("-2000.00")
        assert rows[0]["cumulative"] == Decimal("-2000.00")
        assert rows[1]["over_short"] == Decimal("4000.00")
        assert rows[1]["cumulative"] == Decimal("2000.00")

    def test_aging_excludes_future_and_includes_same_day(
        self, customer, bank_account, segment
    ):
        as_of = date(2026, 1, 31)
        ARInvoice.objects.create(
            invoice_no="OLD", customer=customer, transaction_date=date(2025, 10, 1),
            segment=segment, total=Decimal("7000.00"),
        )
        ARInvoice.objects.create(
            invoice_no="TODAY", customer=customer, transaction_date=as_of,
            segment=segment, total=Decimal("1000.00"),
        )
        ARInvoice.objects.create(
            invoice_no="FUTURE", customer=customer, transaction_date=as_of + timedelta(days=1),
            segment=segment, total=Decimal("4000.00"),
        )

        aging = CycleLedgerService.aging(as_of=as_of)
        by_bucket = {row["bucket"]: row["amount"] for row in aging}
        assert by_bucket["120+"] == Decimal("7000.00")
        assert by_bucket["0-30"] == Decimal("1000.00")
        assert by_bucket["31-60"] == Decimal("0.00")
        assert by_bucket["61-90"] == Decimal("0.00")
        assert by_bucket["91-120"] == Decimal("0.00")


class TestImportCustomers:
    def test_creates_and_is_idempotent(self, tmp_path, company):
        from apps.ar.models import CustomerGroup, PricingTier

        path = tmp_path / "customers.csv"
        import csv
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["CODE", "NAME", "GROUP", "PRICING TIER", "TIN"])
            writer.writerow(["X001", "Client One", "fuel", "volume", "111"])
            writer.writerow(["X002", "Client Two", "equipment", "patron", "222"])
        call_command("import_customers", file=str(path), stdout=StringIO())

        c1 = Customer.objects.get(code="X001")
        assert c1.group == CustomerGroup.FUEL
        assert c1.pricing_tier == PricingTier.VOLUME
        assert c1.tin == "111"
        c2 = Customer.objects.get(code="X002")
        assert c2.group == CustomerGroup.EQUIPMENT

        call_command("import_customers", file=str(path), stdout=StringIO())
        assert Customer.objects.filter(code="X001").count() == 1


@pytest.fixture
def billing_accts(db):
    from apps.foundation.models import Account

    rows = [
        ("15560", "Due from Customers—Unbilled", "asset"),
        ("41010", "Sales-Retail", "revenue"),
    ]
    out = {}
    for code, name, atype in rows:
        out[code], _ = Account.objects.get_or_create(
            code=code,
            defaults={"name": name, "account_type": atype,
                      "segment": Account.segment_for_code(code)},
        )
    return out


def _approved_billing(company, segment, billing_accts, customer, *, billing_no="BI-2026-0001",
                      billing_type="third_party", status="approved", role_users=None):
    from apps.billing.services import BillingService

    billing = BillingService.create_billing(
        billing_no=billing_no,
        billing_date=date(2026, 2, 1),
        billing_type=billing_type,
        company=company,
        segment=segment,
        party_name=customer.name,
        lines=[
            {"side": "dr", "segment": segment, "account": billing_accts["41010"],
             "amount": "1000.00", "description": "Service billed"},
            {"side": "cr", "segment": segment, "account": billing_accts["15560"],
             "amount": "1000.00", "description": "Unbilled receivable"},
        ],
        customer=customer,
    )
    staff = role_users["staff"] if role_users else None
    head = role_users["head"] if role_users else None
    if status in ("submitted", "approved"):
        BillingService.submit(billing, user=staff)
    if status == "approved":
        BillingService.approve(billing, user=head)
    return billing


def _draft_receipt(customer, segment, accounts):
    return CollectionService.create_receipt(
        customer=customer,
        transaction_date=date(2026, 2, 5),
        amount="1000.00",
        cash_account=accounts["10010"],
        segment=segment,
    )


class TestReceiptBillingApplications:
    """AR links/attaches approved Billing Module invoices when making AR."""

    def test_attach_approved_billing(self, company, segment, customer, accounts, billing_accts, role_users):
        from apps.ar.models import ARBillingApplication

        billing = _approved_billing(company, segment, billing_accts, customer, role_users=role_users)
        receipt = _draft_receipt(customer, segment, accounts)
        CollectionService.attach_billings(receipt, [billing.id])
        app = ARBillingApplication.objects.get(receipt=receipt, billing=billing)
        assert app.applied_amount == Decimal("1000.00")

    def test_reject_unapproved_billing(self, company, segment, customer, accounts, billing_accts, role_users):
        billing = _approved_billing(company, segment, billing_accts, customer, status="draft", role_users=role_users)
        receipt = _draft_receipt(customer, segment, accounts)
        with pytest.raises(ValidationError):
            CollectionService.attach_billings(receipt, [billing.id])

    def test_reject_wrong_customer(self, company, segment, customer, accounts, billing_accts, role_users):
        other = Customer.objects.create(code="C002", name="Other Corp")
        billing = _approved_billing(company, segment, billing_accts, other, role_users=role_users)
        receipt = _draft_receipt(customer, segment, accounts)
        with pytest.raises(ValidationError):
            CollectionService.attach_billings(receipt, [billing.id])

    def test_reject_stpc_billing(self, company, segment, customer, accounts, billing_accts, role_users):
        billing = _approved_billing(
            company, segment, billing_accts, customer,
            billing_no="BI-2026-0002", billing_type="stpc", role_users=role_users,
        )
        receipt = _draft_receipt(customer, segment, accounts)
        with pytest.raises(ValidationError):
            CollectionService.attach_billings(receipt, [billing.id])

    def test_detach_and_resubmit_allowed(self, company, segment, customer, accounts, billing_accts, role_users):
        billing = _approved_billing(company, segment, billing_accts, customer, role_users=role_users)
        receipt = _draft_receipt(customer, segment, accounts)
        CollectionService.attach_billings(receipt, [billing.id])
        CollectionService.detach_billing(receipt, billing.id)
        from apps.ar.models import ARBillingApplication

        assert not ARBillingApplication.objects.filter(receipt=receipt).exists()
        CollectionService.submit(receipt)

    def test_available_excludes_used(self, company, segment, customer, accounts, billing_accts, role_users):
        b1 = _approved_billing(company, segment, billing_accts, customer, role_users=role_users)
        _approved_billing(company, segment, billing_accts, customer, billing_no="BI-2026-0002", role_users=role_users)
        receipt = _draft_receipt(customer, segment, accounts)
        CollectionService.attach_billings(receipt, [b1.id])
        available = CollectionService.available_billings_for(customer)
        assert {b.billing_no for b in available} == {"BI-2026-0002"}

    def test_api_attach_and_picker(self, company, segment, customer, accounts, billing_accts, user, role_users):
        from rest_framework.test import APIClient

        billing = _approved_billing(company, segment, billing_accts, customer, role_users=role_users)
        receipt = _draft_receipt(customer, segment, accounts)
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(
            f"/api/v1/ar/receipts/{receipt.id}/attach-billings/",
            {"billing_ids": [billing.id]}, format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["billing_applications"][0]["billing_no"] == billing.billing_no
        resp = client.get(f"/api/v1/ar/receipts/available-billings/?customer={customer.id}")
        assert resp.status_code == 200
        assert all(b["billing_no"] != billing.billing_no for b in resp.json())
