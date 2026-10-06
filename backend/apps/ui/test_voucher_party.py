"""Voucher header party fields (Supplier/Customer, PO/REF) on AR JEs + reversals.

Covers: AR/SI/SSI approval populates the JE header (Business Name + Owner),
PostingService.reverse() carries the fields onto the REV-* mirror, je_detail
renders them, blank owners have no dangling separator, and the backfill
migration fills pre-existing blank vouchers.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.ar.models import Customer
from apps.ar.services import CollectionService, InvoiceService, SpecialInvoiceService
from apps.foundation.models import Account
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService

pytestmark = pytest.mark.django_db

SI_LINES = [
    {"product_code": "DIESEL", "description": "Diesel 1,000L", "quantity": "1000", "unit_price": "15.00"}
]


@pytest.fixture
def sales_account(db, accounts):
    return Account.objects.create(
        code="40000", name="Sales - Fuel Hauling", account_type="revenue",
        segment=Account.segment_for_code("40000"),
    )


def _receipt(customer, segment, accounts, staff, head, **kw):
    args = dict(
        customer=customer, transaction_date=date(2026, 1, 15),
        cash_account=accounts["10010"], payment_method="cash",
        amount="15000.00", segment=segment, created_by=staff,
    )
    args.update(kw)
    receipt = CollectionService.create_receipt(**args)
    CollectionService.submit(receipt, user=staff)
    CollectionService.approve(receipt, user=head)
    receipt.refresh_from_db()
    assert receipt.journal_entry_id is not None
    return receipt


# ------------------------------------------------------------------ reverse()

def _posted_je(company, segment, accounts, **fields):
    je = JournalEntry.objects.create(
        entry_no="JE-PARTY-1", company=company, segment=segment,
        transaction_date=date(2026, 1, 15), status=PostingStatus.DRAFT,
        description="party test",
    )
    JournalEntryLine.objects.create(entry=je, line_no=1, account=accounts["10010"], debit=Decimal("100.00"))
    JournalEntryLine.objects.create(entry=je, line_no=2, account=accounts["41010"], credit=Decimal("100.00"))
    je.recalc_totals()
    for k, v in fields.items():
        setattr(je, k, v)
    je.status = PostingStatus.APPROVED
    je.save()
    PostingService.post(je)
    return je


def test_reverse_copies_party_fields(company, segment, accounts):
    je = _posted_je(company, segment, accounts,
                    supplier_name="Acme Trading — Juan Dela Cruz",
                    po="PO-77", ref_number="TR-1")
    rev = PostingService.reverse(je, reason="wrong account", reversal_date=date(2026, 1, 20))
    rev.refresh_from_db()
    assert rev.supplier_name == "Acme Trading — Juan Dela Cruz"
    assert rev.po == "PO-77"
    assert rev.ref_number == "TR-1"


def test_reverse_blank_stays_blank(company, segment, accounts):
    je = _posted_je(company, segment, accounts)
    rev = PostingService.reverse(je, reason="x", reversal_date=date(2026, 1, 20))
    rev.refresh_from_db()
    assert rev.supplier_name == ""
    assert rev.po == ""
    assert rev.ref_number == ""


# ------------------------------------------------------------------ builders

def test_receipt_je_carries_name_owner_po_ref(company, segment, accounts, fiscal_period, role_users, sales_account):
    c = Customer.objects.create(code="C-VP1", name="Acme Trading", owner_name="Juan Dela Cruz")
    # NOTE: ref/transaction nos live on the receipt, not the customer.
    from apps.ar.models import AcknowledgmentReceipt
    receipt = CollectionService.create_receipt(
        customer=c, transaction_date=date(2026, 1, 15), cash_account=accounts["10010"],
        payment_method="cash", amount="15000.00", segment=segment, created_by=role_users["staff"])
    receipt.ref_po_no = "PO-77"
    receipt.transaction_no = "TR-1"
    receipt.save(update_fields=["ref_po_no", "transaction_no"])
    CollectionService.submit(receipt, user=role_users["staff"])
    CollectionService.approve(receipt, user=role_users["head"])
    je = AcknowledgmentReceipt.objects.get(pk=receipt.pk).journal_entry
    assert je.supplier_name == "Acme Trading — Juan Dela Cruz"
    assert je.po == "PO-77"
    assert je.ref_number == "TR-1"


def test_receipt_je_blank_owner_no_dangling_dash(company, segment, accounts, fiscal_period, role_users, sales_account):
    c = Customer.objects.create(code="C-VP2", name="Solo Corp", owner_name="")
    receipt = _receipt(c, segment, accounts, role_users["staff"], role_users["head"])
    je = receipt.journal_entry
    assert je.supplier_name == "Solo Corp"
    assert "—" not in je.supplier_name


def test_si_je_carries_party_only(company, segment, fiscal_period, role_users, sales_account):
    c = Customer.objects.create(code="C-VP3", name="SI Buyer", owner_name="SI Owner")
    inv = InvoiceService.create_invoice(customer=c, transaction_date=date(2026, 1, 15),
                                        segment=segment, is_paid_on_delivery=False,
                                        lines=SI_LINES, created_by=None)
    InvoiceService.submit(inv, user=role_users["staff"])
    InvoiceService.approve(inv, user=role_users["head"])
    inv.refresh_from_db()
    assert inv.journal_entry.supplier_name == "SI Buyer — SI Owner"
    assert inv.journal_entry.po == ""
    assert inv.journal_entry.ref_number == ""


def test_ssi_je_carries_party_and_dr_ref(company, segment, accounts, fiscal_period, role_users, sales_account):
    c = Customer.objects.create(code="C-VP4", name="SSI Buyer", owner_name="SSI Owner")
    inv = SpecialInvoiceService.create_ssi(
        customer=c, transaction_date=date(2026, 2, 10), segment=segment,
        delivery_receipt_no="DR-9", notes="", created_by=role_users["staff"],
        lines=[
            {"account": accounts["12030"], "segment": segment, "debit": "15000.00",
             "credit": "0", "description": "AR - fuel", "cost_center": "GEN-FUEL"},
            {"account": sales_account, "segment": segment, "debit": "0",
             "credit": "15000.00", "description": "Fuel sales", "cost_center": ""},
        ])
    SpecialInvoiceService.submit(inv, user=role_users["staff"])
    SpecialInvoiceService.approve(inv, user=role_users["head"])
    inv.refresh_from_db()
    assert inv.journal_entry.supplier_name == "SSI Buyer — SSI Owner"
    assert inv.journal_entry.ref_number == "DR-9"


def test_voucher_party_name_truncates_to_255():
    from apps.ar.services import _voucher_party_name

    class C:
        name = "N" * 250
        owner_name = "O" * 50

    assert len(_voucher_party_name(C())) == 255


# ------------------------------------------------------------------ UI render

def test_je_detail_shows_customer_on_original_and_reversal(
    client, company, segment, accounts, fiscal_period, role_users, sales_account
):
    client.force_login(role_users["staff"])
    c = Customer.objects.create(code="C-VP5", name="Detail Corp", owner_name="Detail Owner")
    receipt = _receipt(c, segment, accounts, role_users["staff"], role_users["head"])
    je = receipt.journal_entry
    rev = PostingService.reverse(je, reason="test", reversal_date=date(2026, 1, 20))
    for pk in (je.pk, rev.pk):
        body = client.get(f"/journal/{pk}/").content.decode()
        assert "Detail Corp" in body
        assert "Detail Owner" in body


# ------------------------------------------------------------------ backfill

def test_backfill_migration_fills_blank_original_and_reversal(
    company, segment, accounts, fiscal_period, role_users, sales_account
):
    import importlib

    backfill_mod = importlib.import_module("apps.posting.migrations.0008_backfill_voucher_party_fields")
    from django.apps import apps as live_apps
    from apps.ar.models import AcknowledgmentReceipt

    c = Customer.objects.create(code="C-VP6", name="Backfill Corp", owner_name="Backfill Owner")
    receipt = CollectionService.create_receipt(
        customer=c, transaction_date=date(2026, 1, 15), cash_account=accounts["10010"],
        payment_method="cash", amount="15000.00", segment=segment, created_by=role_users["staff"])
    receipt.ref_po_no = "PO-BF"
    receipt.transaction_no = "TR-BF"
    receipt.save(update_fields=["ref_po_no", "transaction_no"])

    # Simulate a pre-fix posted JE: blank header, linked to the receipt.
    je = JournalEntry.objects.create(
        entry_no="AR-2026-00008", company=company, segment=segment,
        transaction_date=date(2026, 1, 15), status=PostingStatus.POSTED,
        description="Collection AR-2026-00008 Backfill Corp",
        source_doc_type="AR", source_doc_no="AR-2026-00008",
    )
    receipt.journal_entry = je
    receipt.save(update_fields=["journal_entry"])
    rev = JournalEntry.objects.create(
        entry_no="REV-AR-2026-00008", company=company, segment=segment,
        transaction_date=date(2026, 1, 20), status=PostingStatus.POSTED,
        description="Reversal of AR-2026-00008: test",
        source_doc_type="AR", source_doc_no="AR-2026-00008",
        reversal_token="REV:AR-2026-00008:999",
    )
    je.reversal_token = "REV:AR-2026-00008:999"
    je.save(update_fields=["reversal_token"])

    backfill_mod.backfill(live_apps, None)
    je.refresh_from_db()
    rev.refresh_from_db()
    assert je.supplier_name == "Backfill Corp — Backfill Owner"
    assert je.po == "PO-BF"
    assert je.ref_number == "TR-BF"
    assert rev.supplier_name == "Backfill Corp — Backfill Owner"
    assert rev.po == "PO-BF"
    assert rev.ref_number == "TR-BF"


def test_backfill_leaves_unrelated_entries_alone(company, segment, accounts):
    import importlib

    backfill_mod = importlib.import_module("apps.posting.migrations.0008_backfill_voucher_party_fields")
    from django.apps import apps as live_apps

    je = JournalEntry.objects.create(
        entry_no="DEP-2026-1", company=company, segment=segment,
        transaction_date=date(2026, 1, 15), status=PostingStatus.POSTED,
        description="Bank deposit DEP-2026-1",
        source_doc_type="DEP", source_doc_no="DEP-2026-1",
    )
    backfill_mod.backfill(live_apps, None)
    je.refresh_from_db()
    assert je.supplier_name == ""

