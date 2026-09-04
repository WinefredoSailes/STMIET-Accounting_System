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
)
from apps.ar.services import CollectionService, CycleLedgerService
from apps.core.exceptions import ValidationError
from apps.foundation.calendar import cycle_range_for
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus

from django.core.management import call_command
from io import StringIO


@pytest.fixture
def customer(db, segment, company):
    return Customer.objects.create(code="C001", name="ABC Trading", segment=segment)


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
        )
        invoice.refresh_from_db()
        assert invoice.status == "paid"

    def test_invalid_customer_on_applied_invoice_rejected(self, customer, bank_account, segment, invoice):
        other = Customer.objects.create(code="C002", name="Other Co", segment=segment)
        with pytest.raises(ValidationError):
            CollectionService.record_collection(
                receipt_no="AR-2026-00004",
                customer=other,
                transaction_date=date(2026, 1, 16),
                amount="100.00",
                cash_account=bank_account,
                applied_to=invoice,
            )

    def test_zero_amount_rejected(self, customer, bank_account):
        with pytest.raises(ValidationError):
            CollectionService.record_collection(
                receipt_no="AR-2026-00005",
                customer=customer,
                transaction_date=date(2026, 1, 16),
                amount="0.00",
                cash_account=bank_account,
            )


class TestDepositNoJe:
    def test_deposit_is_state_change_only(self, customer, bank_account, segment):
        d = Deposit.objects.create(
            bank_account=bank_account, transaction_date=date(2026, 1, 15),
            amount=Decimal("500.00"), reference="D1",
        )
        d.refresh_from_db()
        # No journal entry is created by a deposit (ADR-016).
        assert JournalEntry.objects.filter(source_doc_type="DEP").count() == 0


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
        )
        # Cycle 2 (Tue 01-20): paid 4000 -> over +4000, cumulative +2000.
        CollectionService.record_collection(
            receipt_no="AR-2026-00011", customer=customer,
            transaction_date=date(2026, 1, 21), amount="4000.00",
            cash_account=bank_account,
        )

        rows = CycleLedgerService.for_customer(customer)
        assert len(rows) == 2
        assert rows[0]["over_short"] == Decimal("-2000.00")
        assert rows[0]["cumulative"] == Decimal("-2000.00")
        assert rows[1]["over_short"] == Decimal("4000.00")
        assert rows[1]["cumulative"] == Decimal("2000.00")

    def test_aging_buckets(self, customer, bank_account, segment):
        ARInvoice.objects.create(
            invoice_no="OLD", customer=customer, transaction_date=date(2025, 10, 1),
            segment=segment, total=Decimal("7000.00"),
        )
        ARInvoice.objects.create(
            invoice_no="NEW", customer=customer, transaction_date=date(2026, 1, 10),
            segment=segment, total=Decimal("3000.00"),
        )
        aging = CycleLedgerService.aging(as_of=date(2026, 1, 31))
        by_bucket = {row["bucket"]: row["amount"] for row in aging}
        assert by_bucket["120+"] == Decimal("7000.00")
        assert by_bucket["0-30"] == Decimal("3000.00")


class TestImportCustomers:
    def test_creates_and_is_idempotent(self, tmp_path, company, segment):
        from apps.ar.models import CustomerGroup, PricingTier
        from apps.foundation.models import Segment as SegmentModel

        SegmentModel.objects.create(code="DMIE", name="DMIE", company=company)

        path = tmp_path / "customers.csv"
        import csv
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["CODE", "NAME", "SEGMENT", "GROUP", "PRICING TIER", "TIN"])
            writer.writerow(["X001", "Client One", "DHPP", "fuel", "volume", "111"])
            writer.writerow(["X002", "Client Two", "DMIE", "equipment", "patron", "222"])
        call_command("import_customers", file=str(path), stdout=StringIO())

        c1 = Customer.objects.get(code="X001")
        assert c1.segment.code == "DHPP"
        assert c1.group == CustomerGroup.FUEL
        assert c1.pricing_tier == PricingTier.VOLUME
        assert c1.tin == "111"
        c2 = Customer.objects.get(code="X002")
        assert c2.segment.code == "DMIE"

        call_command("import_customers", file=str(path), stdout=StringIO())
        assert Customer.objects.filter(code="X001").count() == 1
