"""Tax & Compliance contract tests (BUILD-PLAN Phase 9).

- VAT extraction at SI level (12% VAT-inclusive -> output VAT derived)
- WHT certificates (2307/2306) derived from posted CV withholding
- Income tax provision: Dr 64600 | Cr income tax payable, posted + balanced
- Tax calendar upsert + mark filed/paid
"""

from datetime import date
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def tax_accounts(db, company, segment):
    """COA slice needed by the tax services: revenue, AR, tax expense, payables."""
    from apps.foundation.models import Account, SegmentAccountMap

    accounts = {}
    for code, name, atype in [
        ("12030", "A/R - Fuel Clients", "asset"),
        ("20000", "A/P - Current - DHPP", "liability"),
        ("21010", "Accounts Payable-Trade", "liability"),
        ("41010", "Sales - Retail", "revenue"),
        ("61100", "Cost of Sales", "expense"),
        ("64600", "Income Tax Expense", "expense"),
        ("20200", "Income Tax Payable", "liability"),
        ("20300", "Output VAT Payable", "liability"),
        ("64110", "WHT - Expanded", "liability"),
    ]:
        accounts[code] = Account.objects.create(
            code=code, name=name, account_type=atype, segment="DHPP"
        )
    # Map the income-tax + VAT roles to their segment accounts (data-driven).
    SegmentAccountMap.objects.create(
        segment=segment.code and segment, role=SegmentAccountMap.ROLE_INCOME_TAX, account=accounts["20200"]
    )
    SegmentAccountMap.objects.create(
        segment=segment, role=SegmentAccountMap.ROLE_VAT_OUTPUT, account=accounts["20300"]
    )
    return accounts


@pytest.fixture
def supplier(db, segment):
    from apps.ap.models import Supplier

    return Supplier.objects.create(
        code="S001", name="Shell Fuel Depot", supplier_type="depot",
        tin="123-456-789", default_segment=segment,
    )


@pytest.fixture
def posted_invoice(db, company, segment, tax_accounts):
    """A posted, paid-on-delivery sales invoice (AR :: SI booking)."""
    from apps.ar.models import ARInvoice, ARInvoiceLine, Customer
    from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
    from apps.posting.services import PostingService

    cust = Customer.objects.create(code="C001", name="Test Fleet", segment=segment)
    inv = ARInvoice.objects.create(
        invoice_no="SI-2026-0001",
        customer=cust,
        transaction_date=date(2026, 1, 15),
        segment=segment,
        total=Decimal("1120.00"),  # 1000 net + 120 VAT
        is_paid_on_delivery=True,
        status="open",
    )
    ARInvoiceLine.objects.create(
        invoice=inv, line_no=1, product_code="DIESEL", description="Fuel",
        quantity="1.00", unit_price="1120.00", amount="1120.00",
    )
    # A simple balanced JE linking this SI (Dr AR 1120 | Cr Sales 1120).
    je = JournalEntry.objects.create(
        entry_no="JE-VAT-1", company=company, segment=segment,
        transaction_date=date(2026, 1, 15), status=PostingStatus.DRAFT,
        description="Fuel delivery", source_doc_type="SI", source_doc_no="SI-2026-0001",
    )
    JournalEntryLine.objects.create(entry=je, line_no=1, account=tax_accounts["12030"], debit=Decimal("1120.00"))
    JournalEntryLine.objects.create(entry=je, line_no=2, account=tax_accounts["41010"], credit=Decimal("1120.00"))
    je.recalc_totals()
    PostingService.post(je)
    inv.journal_entry = je
    inv.save(update_fields=["journal_entry"])
    return inv


class TestVATService:
    def test_extract_from_invoice(self, posted_invoice):
        from apps.tax.services import VATService

        comp = VATService.extract_from_invoice(posted_invoice)
        assert comp.gross_amount == Decimal("1120.00")
        # 1120 * 0.12 / 1.12 = 120.00 output VAT; net 1000.
        assert comp.output_vat == Decimal("120.00")
        assert comp.net_amount == Decimal("1000.00")
        assert comp.is_balanced

    def test_extract_for_period(self, company, posted_invoice):
        from apps.tax.services import VATService

        comps = VATService.extract_for_period(company, date(2026, 1, 1), date(2026, 1, 31))
        assert len(comps) == 1
        summary = VATService.period_summary(comps)
        assert summary["output_vat"] == Decimal("120.00")
        assert summary["net"] == Decimal("1000.00")


class TestWithholdingService:
    def test_build_2307_from_cv(self, segment, supplier, tax_accounts, user=None):
        from apps.ap.models import CheckVoucher
        from apps.foundation.models import Segment
        from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
        from apps.posting.services import PostingService
        from apps.tax.services import WithholdingService

        seg = Segment.objects.create(code="WHT", name="WHT Test", company=segment.company)
        cv = CheckVoucher.objects.create(
            cv_number="CV-2026-0001", cv_date=date(2026, 1, 20),
            payee=supplier, bank_account=tax_accounts["12030"],
            gross_amount="10000.00", withheld_tax="200.00", net_amount="9800.00", status="cleared",
        )
        # Link a posted JE so the CV is a real remittance source.
        je = JournalEntry.objects.create(
            entry_no="CV-2026-0001", company=segment.company, segment=seg,
            transaction_date=date(2026, 1, 20), status=PostingStatus.DRAFT,
            description="CV test", source_doc_type="CV", source_doc_no="CV-2026-0001",
        )
        JournalEntryLine.objects.create(entry=je, line_no=1, account=tax_accounts["20000"], debit=Decimal("10000.00"))
        JournalEntryLine.objects.create(entry=je, line_no=2, account=tax_accounts["12030"], credit=Decimal("9800.00"))
        JournalEntryLine.objects.create(entry=je, line_no=3, account=tax_accounts["64110"], credit=Decimal("200.00"))
        je.recalc_totals()
        PostingService.post(je)
        cv.journal_entry = je
        cv.save(update_fields=["journal_entry"])

        rows = WithholdingService.build_certificates(cert_type="2307",
                                                     period_start=date(2026, 1, 1), period_end=date(2026, 1, 31))
        assert len(rows) == 1
        assert rows[0]["tax_amount"] == Decimal("200.00")
        assert rows[0]["gross_amount"] == Decimal("10000.00")
        assert rows[0]["tin"] == "123-456-789"

    def test_empty_when_no_wht(self, segment, supplier, tax_accounts):
        from apps.tax.services import WithholdingService

        rows = WithholdingService.build_certificates()
        assert rows == []


class TestIncomeTaxProvision:
    def test_provision_posts_balanced(self, company, segment, tax_accounts, user=None):
        from apps.tax.services import IncomeTaxService

        prov = IncomeTaxService.provision(
            company=company, segment=segment, taxable_income="50000.00",
            filing_period="Q1 2026", rate="0.20", user=None,
        )
        assert prov.tax_amount == Decimal("10000.00")
        je = prov.journal_entry
        assert je.is_posted
        assert je.is_balanced
        # Dr 64600 10,000 | Cr income tax payable 10,000
        lines = {l.account.code: l for l in je.lines.all()}
        assert lines["64600"].debit == Decimal("10000.00")
        assert lines["20200"].credit == Decimal("10000.00")

    def test_provision_negative_basis_zero(self, company, segment, tax_accounts):
        from apps.tax.services import IncomeTaxService

        prov = IncomeTaxService.provision(
            company=company, segment=segment, taxable_income="-1000.00",
            filing_period="Q2 2026", user=None,
        )
        assert prov.tax_amount == Decimal("0.00")
        assert prov.taxable_income == Decimal("0.00")


class TestTaxCalendar:
    def test_upsert_and_mark(self, company):
        from apps.tax.models import TaxCalendar
        from apps.tax.services import TaxCalendarService

        cal = TaxCalendarService.upsert(
            company=company, form="1702Q", filing_period="Q1 2026", due_date=date(2026, 5, 15),
            amount_due="15000.00",
        )
        assert cal.status == "not_due"
        TaxCalendarService.mark(cal, status="filed", filed_date=date(2026, 5, 14))
        cal.refresh_from_db()
        assert cal.status == "filed"
        assert cal.filed_date == date(2026, 5, 14)

    def test_upsert_idempotent(self, company):
        from apps.tax.models import TaxCalendar
        from apps.tax.services import TaxCalendarService

        TaxCalendarService.upsert(company=company, form="2307", filing_period="Jan 2026", due_date=date(2026, 2, 10))
        TaxCalendarService.upsert(company=company, form="2307", filing_period="Jan 2026", due_date=date(2026, 2, 10))
        assert TaxCalendar.objects.count() == 1