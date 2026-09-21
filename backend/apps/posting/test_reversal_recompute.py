"""Downstream recompute after a JE reversal (ADR-004/013).

A reversal must not just post the mirror entry — derived documents and reports
must reflect it: PO balances restore, AR invoices re-open, GL nets to zero.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.ap.models import PurchaseOrder, RFPDocument, Supplier
from apps.ar.models import ARInvoice, AcknowledgmentReceipt, Customer
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService, ReversalService

pytestmark = pytest.mark.django_db


def _posted_je(company, segment, accounts, *, ref, source_type, source_no):
    je = JournalEntry.objects.create(
        entry_no=ref, company=company, segment=segment,
        transaction_date=date(2026, 9, 15), status=PostingStatus.DRAFT,
        description="recompute test", source_doc_type=source_type, source_doc_no=source_no,
    )
    JournalEntryLine.objects.create(
        entry=je, line_no=1, account=accounts["10010"], debit=Decimal("1000.00")
    )
    JournalEntryLine.objects.create(
        entry=je, line_no=2, account=accounts["41010"], credit=Decimal("1000.00")
    )
    je.recalc_totals()
    je.status = PostingStatus.APPROVED
    je.save(update_fields=["status", "updated_at"])
    PostingService.post(je)
    return je


def test_po_balance_restored_when_rfp_reversed(company, segment, accounts, role_users):
    supplier = Supplier.objects.create(
        code="SUP-R1", name="Reversal Vendor", default_segment=segment
    )
    po = PurchaseOrder.objects.create(
        po_number="PO-REV-1", po_date=date(2026, 9, 1), supplier=supplier,
        segment=segment, amount=Decimal("10000.00"), status="approved",
    )
    rfp = RFPDocument.objects.create(
        ap_number="A-REV-1", rfp_date=date(2026, 9, 1), payee=supplier,
        segment=segment, amount=Decimal("1000.00"), status="posted", po=po,
    )
    je = _posted_je(
        company, segment, accounts,
        ref="RFP-A-REV-1", source_type="RFP", source_no="A-REV-1",
    )
    rfp.journal_entry = je
    rfp.save(update_fields=["journal_entry", "updated_at"])

    assert po.billed_amount == Decimal("1000.00")
    assert po.available_amount == Decimal("9000.00")

    req = ReversalService.request(je, reason="duplicate posting", user=role_users["staff"])
    ReversalService.approve(req, user=role_users["head"])

    # The reversed RFP is no longer billed against the PO → balance restored.
    assert po.billed_amount == Decimal("0.00")
    assert po.available_amount == Decimal("10000.00")


def test_ar_invoice_reopens_when_receipt_reversed(company, segment, accounts, role_users):
    customer = Customer.objects.create(
        code="CUST-R1", name="Reversal Customer", segment=segment
    )
    invoice = ARInvoice.objects.create(
        invoice_no="SI-REV-1", customer=customer, transaction_date=date(2026, 9, 1),
        segment=segment, total=Decimal("1000.00"), status="paid",
    )
    receipt = AcknowledgmentReceipt.objects.create(
        receipt_no="AR-REV-1", customer=customer, transaction_date=date(2026, 9, 5),
        amount=Decimal("1000.00"), cash_account=accounts["10010"], segment=segment,
        status="posted", applied_to=invoice,
    )
    je = _posted_je(
        company, segment, accounts,
        ref="AR-JE-REV-1", source_type="AR", source_no="AR-REV-1",
    )
    receipt.journal_entry = je
    receipt.save(update_fields=["journal_entry", "updated_at"])

    assert invoice.balance == Decimal("0.00")

    req = ReversalService.request(je, reason="bounced check", user=role_users["staff"])
    ReversalService.approve(req, user=role_users["head"])

    invoice.refresh_from_db()
    assert invoice.balance == Decimal("1000.00")
    assert invoice.status == "open"  # re-opened by the reversal