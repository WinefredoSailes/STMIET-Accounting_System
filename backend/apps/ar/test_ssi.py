"""Special Sales Invoice (Fuel Delivery) — service coverage.

Covers numbering, the draft/submitted/posted lifecycle, distribution-line
validation (Dr == Cr, debit-XOR-credit, approved-customer gate), Head-only
approval/rejection, the JE built exactly from the lines, GL projection, the
approval-threshold gate, and standalone-ness (never touches ARInvoice).
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.ar.models import (
    ARInvoice,
    Customer,
    SpecialSalesInvoice,
    SpecialSalesInvoiceLine,
)
from apps.ar.services import SpecialInvoiceService
from apps.core.exceptions import ValidationError
from apps.foundation.models import Account
from apps.posting.models import GeneralLedger, JournalEntry, PostingStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def fuel_sales_account(db, accounts):
    """DHPP fuel-sales revenue account (the Cr side of a fuel delivery)."""
    return Account.objects.create(
        code="40000",
        name="Sales - Fuel",
        account_type="revenue",
        segment=Account.segment_for_code("40000"),
    )


@pytest.fixture
def customer(db):
    return Customer.objects.create(code="C-SSI", name="SSI Fuel Client")


def _lines(segment, ar="12030", sales="40000", amount="15000.00"):
    return [
        {
            "account": ar,
            "segment": segment,
            "debit": amount,
            "credit": "0",
            "description": "AR - fuel delivery DR-001",
            "cost_center": "GEN-FUEL",
        },
        {
            "account": sales,
            "segment": segment,
            "debit": "0",
            "credit": amount,
            "description": "Fuel sales",
            "cost_center": "",
        },
    ]


@pytest.fixture
def draft_ssi(customer, segment, fuel_sales_account, accounts):
    return SpecialInvoiceService.create_ssi(
        customer=customer,
        transaction_date=date(2026, 2, 10),
        segment=segment,
        delivery_receipt_no="DR-001",
        notes="Tanker 7",
        lines=_lines(segment),
    )


# ---------------------------------------------------------------------- create


def test_ssi_numbering_and_header(customer, segment, fuel_sales_account, accounts):
    ssi = SpecialInvoiceService.create_ssi(
        customer=customer,
        transaction_date=date(2026, 2, 10),
        segment=segment,
        delivery_receipt_no="DR-001",
        lines=_lines(segment),
    )
    assert ssi.status == "draft"
    assert ssi.invoice_no.startswith("SSI-2026-")
    assert ssi.journal_entry_id is None
    assert ssi.total == Decimal("15000.00")
    assert ssi.delivery_receipt_no == "DR-001"
    assert [line.line_no for line in ssi.lines.order_by("line_no")] == [1, 2]
    first = ssi.lines.get(line_no=1)
    assert first.account.code == "12030"
    assert first.debit == Decimal("15000.00")
    assert first.cost_center == "GEN-FUEL"
    second = ssi.lines.get(line_no=2)
    assert second.account.code == "40000"
    assert second.credit == Decimal("15000.00")


def test_ssi_numbers_sequence(customer, segment, fuel_sales_account, accounts):
    first = SpecialInvoiceService.create_ssi(
        customer=customer,
        transaction_date=date(2026, 2, 10),
        segment=segment,
        lines=_lines(segment),
    )
    second = SpecialInvoiceService.create_ssi(
        customer=customer,
        transaction_date=date(2026, 2, 11),
        segment=segment,
        lines=_lines(segment),
    )
    assert first.invoice_no != second.invoice_no
    assert second.invoice_no > first.invoice_no


def test_ssi_accepts_model_objects(customer, segment, fuel_sales_account, accounts):
    ssi = SpecialInvoiceService.create_ssi(
        customer=customer,
        transaction_date=date(2026, 2, 10),
        segment=segment,
        lines=[
            {
                "account": accounts["12030"],
                "segment": segment,
                "debit": "100.00",
                "credit": "0",
            },
            {
                "account": fuel_sales_account,
                "segment": segment,
                "debit": "0",
                "credit": "100.00",
            },
        ],
    )
    assert ssi.total == Decimal("100.00")


def test_ssi_rejects_unbalanced(customer, segment, fuel_sales_account, accounts):
    lines = _lines(segment)
    lines[1]["credit"] = "14000.00"
    with pytest.raises(ValidationError, match="out of balance"):
        SpecialInvoiceService.create_ssi(
            customer=customer,
            transaction_date=date(2026, 2, 10),
            segment=segment,
            lines=lines,
        )


def test_ssi_rejects_both_sides_row(customer, segment, fuel_sales_account, accounts):
    lines = _lines(segment)
    lines[0]["credit"] = "15000.00"
    with pytest.raises(ValidationError, match="only one of Debit or Credit"):
        SpecialInvoiceService.create_ssi(
            customer=customer,
            transaction_date=date(2026, 2, 10),
            segment=segment,
            lines=lines,
        )


def test_ssi_rejects_empty_lines(customer, segment):
    with pytest.raises(ValidationError, match="at least one line"):
        SpecialInvoiceService.create_ssi(
            customer=customer,
            transaction_date=date(2026, 2, 10),
            segment=segment,
            lines=[],
        )


def test_ssi_rejects_unknown_account(customer, segment):
    with pytest.raises(ValidationError, match="COA account 99999 not found"):
        SpecialInvoiceService.create_ssi(
            customer=customer,
            transaction_date=date(2026, 2, 10),
            segment=segment,
            lines=[{"account": "99999", "segment": segment, "debit": "1.00"}],
        )


def test_ssi_rejects_missing_segment(customer, fuel_sales_account, accounts):
    with pytest.raises(ValidationError, match="segment is required"):
        SpecialInvoiceService.create_ssi(
            customer=customer,
            transaction_date=date(2026, 2, 10),
            segment=None,
            lines=[{"account": "12030", "segment": None, "debit": "1.00"}],
        )


def test_ssi_rejects_pending_customer(segment, fuel_sales_account, accounts):
    from apps.ar.models import CustomerApprovalStatus

    pending = Customer.objects.create(
        code="C-PEND", name="Pending", approval_status=CustomerApprovalStatus.PENDING
    )
    with pytest.raises(ValidationError, match="not approved yet"):
        SpecialInvoiceService.create_ssi(
            customer=pending,
            transaction_date=date(2026, 2, 10),
            segment=segment,
            lines=_lines(segment),
        )


# ---------------------------------------------------------------------- submit


def test_ssi_submit_flow(draft_ssi, user):
    SpecialInvoiceService.submit(draft_ssi, user=user)
    draft_ssi.refresh_from_db()
    assert draft_ssi.status == "submitted"
    with pytest.raises(ValidationError, match="Only draft"):
        SpecialInvoiceService.submit(draft_ssi, user=user)


def test_ssi_submit_requires_lines(customer, segment):
    ssi = SpecialSalesInvoice.objects.create(
        invoice_no="SSI-2026-09999",
        customer=customer,
        transaction_date=date(2026, 2, 10),
        segment=segment,
        total=Decimal("0.00"),
        status="draft",
    )
    with pytest.raises(ValidationError, match="at least one"):
        SpecialInvoiceService.submit(ssi)


# ---------------------------------------------------------------------- approve


def test_ssi_approve_posts_je_from_lines(draft_ssi, user, role_users):
    head = role_users["head"]
    staff = role_users["staff"]
    with pytest.raises(ValidationError, match="head"):
        SpecialInvoiceService.approve(draft_ssi, user=staff)

    SpecialInvoiceService.submit(draft_ssi, user=user)
    SpecialInvoiceService.approve(draft_ssi, user=head)
    draft_ssi.refresh_from_db()

    assert draft_ssi.status == "posted"
    assert draft_ssi.approved_by_id == head.id
    assert draft_ssi.approved_at is not None

    entry = draft_ssi.journal_entry
    assert entry is not None
    assert entry.entry_no == draft_ssi.invoice_no
    assert entry.status == PostingStatus.POSTED
    assert entry.source_doc_type == "SSI"
    assert entry.source_doc_no == draft_ssi.invoice_no
    assert entry.total_debit == Decimal("15000.00")
    assert entry.total_credit == Decimal("15000.00")

    je_lines = list(entry.lines.order_by("line_no"))
    assert [(str(l.account.code), l.debit, l.credit) for l in je_lines] == [
        ("12030", Decimal("15000.00"), Decimal("0.00")),
        ("40000", Decimal("0.00"), Decimal("15000.00")),
    ]
    assert je_lines[0].cost_center == "GEN-FUEL"
    assert je_lines[0].segment.code == draft_ssi.segment.code

    # GL projection: the entry now feeds Journal, Ledger, Trial Balance.
    gl = GeneralLedger.objects.filter(entry=entry).order_by("line__line_no")
    assert gl.count() == 2
    assert sum((g.debit for g in gl), Decimal("0.00")) == Decimal("15000.00")
    assert sum((g.credit for g in gl), Decimal("0.00")) == Decimal("15000.00")


def test_ssi_approve_requires_submitted(draft_ssi, role_users):
    with pytest.raises(ValidationError, match="Only submitted"):
        SpecialInvoiceService.approve(draft_ssi, user=role_users["head"])


def test_ssi_double_approve_blocked(draft_ssi, user, role_users):
    head = role_users["head"]
    SpecialInvoiceService.submit(draft_ssi, user=user)
    SpecialInvoiceService.approve(draft_ssi, user=head)
    with pytest.raises(ValidationError, match="Only submitted"):
        SpecialInvoiceService.approve(draft_ssi, user=head)


def test_ssi_large_amount_posts_after_head_approval(
    customer, segment, fuel_sales_account, accounts, user, role_users
):
    """Above-threshold SSI posts: the JE is pre-approved by the Head's sign,
    satisfying the ADR-033 gate inside PostingService.post."""
    ssi = SpecialInvoiceService.create_ssi(
        customer=customer,
        transaction_date=date(2026, 2, 10),
        segment=segment,
        delivery_receipt_no="DR-BIG",
        lines=_lines(segment, amount="250000.00"),
    )
    SpecialInvoiceService.submit(ssi, user=user)
    SpecialInvoiceService.approve(ssi, user=role_users["head"])
    ssi.refresh_from_db()
    assert ssi.status == "posted"
    assert ssi.journal_entry.status == PostingStatus.POSTED


def test_ssi_never_touches_ar_invoice(draft_ssi, user, role_users):
    SpecialInvoiceService.submit(draft_ssi, user=user)
    SpecialInvoiceService.approve(draft_ssi, user=role_users["head"])
    assert ARInvoice.objects.count() == 0
    assert not JournalEntry.objects.filter(source_doc_type="SI").exists()


# ---------------------------------------------------------------------- reject


def test_ssi_reject_returns_to_draft(draft_ssi, user, role_users):
    head = role_users["head"]
    SpecialInvoiceService.submit(draft_ssi, user=user)
    with pytest.raises(ValidationError, match="rejection note"):
        SpecialInvoiceService.reject(draft_ssi, user=head, note="  ")
    SpecialInvoiceService.reject(draft_ssi, user=head, note="Wrong DR number")
    draft_ssi.refresh_from_db()
    assert draft_ssi.status == "draft"
    assert draft_ssi.rejection_note == "Wrong DR number"
    assert draft_ssi.rejected_by_id == head.id
    # Preparer resubmits after fixing.
    SpecialInvoiceService.submit(draft_ssi, user=user)
    assert draft_ssi.status == "submitted"


def test_ssi_reject_head_only_and_submitted_only(draft_ssi, user, role_users):
    with pytest.raises(ValidationError):
        SpecialInvoiceService.reject(draft_ssi, user=role_users["staff"], note="x")
    SpecialInvoiceService.submit(draft_ssi, user=user)
    with pytest.raises(ValidationError):
        SpecialInvoiceService.reject(draft_ssi, user=role_users["staff"], note="x")


# ---------------------------------------------------------------------- edit


def test_ssi_update_draft(draft_ssi, segment, fuel_sales_account, accounts, user):
    SpecialInvoiceService.update_draft(
        invoice=draft_ssi,
        delivery_receipt_no="DR-002",
        notes="corrected",
        lines=_lines(segment, amount="9000.00"),
        user=user,
    )
    draft_ssi.refresh_from_db()
    assert draft_ssi.total == Decimal("9000.00")
    assert draft_ssi.delivery_receipt_no == "DR-002"
    assert draft_ssi.notes == "corrected"
    assert draft_ssi.lines.count() == 2


def test_ssi_update_draft_blocked_after_submit(draft_ssi, segment, user):
    SpecialInvoiceService.submit(draft_ssi, user=user)
    with pytest.raises(ValidationError, match="Only draft"):
        SpecialInvoiceService.update_draft(
            invoice=draft_ssi, lines=_lines(segment), user=user
        )


def test_ssi_line_model_roundtrip(draft_ssi):
    assert SpecialSalesInvoiceLine.objects.filter(invoice=draft_ssi).count() == 2
    assert str(draft_ssi.lines.get(line_no=1)).startswith(draft_ssi.invoice_no)


def test_ssi_audit_trail_uses_own_doc_type(draft_ssi, user, role_users):
    """SSI actions log under doc_type 'ssi' — never mixed into RFP trails."""
    from apps.ap.models import ActionLog

    SpecialInvoiceService.submit(draft_ssi, user=user)
    SpecialInvoiceService.approve(draft_ssi, user=role_users["head"])
    # Own namespace: created/submitted/approved land under 'ssi' …
    actions = set(
        ActionLog.objects.filter(
            doc_type=ActionLog.DocType.SSI, doc_id=draft_ssi.id
        ).values_list("action", flat=True)
    )
    assert {"created", "submitted", "approved"} <= actions
    # … and never under the legacy fallbacks ('rfp' fall-through, 'ar').
    # (A 'je' row may share the numeric doc_id — the JE log uses its own
    # entry id; doc_type keeps the histories apart by design.)
    stray = set(
        ActionLog.objects.filter(doc_id=draft_ssi.id)
        .exclude(doc_type__in=(ActionLog.DocType.SSI, ActionLog.DocType.JE))
        .values_list("doc_type", flat=True)
    )
    assert not stray, f"SSI actions leaked into {stray}"


# ---------------------------------------------------------------------- API


def _api_lines(segment):
    return [
        {
            "account": "12030",
            "segment": segment.id,
            "debit": "15000.00",
            "credit": "0",
            "description": "AR - fuel delivery",
            "cost_center": "GEN-FUEL",
        },
        {
            "account": "40000",
            "segment": segment.id,
            "debit": "0",
            "credit": "15000.00",
            "description": "Fuel sales",
        },
    ]


def _api_clients(role_users):
    from rest_framework.test import APIClient

    out = {}
    for role in ("staff", "head"):
        client = APIClient()
        client.force_authenticate(user=role_users[role])
        out[role] = client
    return out


def test_ssi_api_lifecycle(customer, segment, fuel_sales_account, accounts, role_users):
    api = _api_clients(role_users)
    resp = api["staff"].post(
        "/api/v1/ar/special-invoices/",
        {
            "customer": customer.id,
            "transaction_date": "2026-02-10",
            "segment": segment.id,
            "delivery_receipt_no": "DR-API-1",
            "notes": "api",
            "lines": _api_lines(segment),
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    ssi = SpecialSalesInvoice.objects.get()
    assert ssi.status == "draft"
    assert ssi.invoice_no.startswith("SSI-2026-")
    assert resp.data["lines"][0]["account_code"] == "12030"
    assert resp.data["lines"][1]["account_name"] == "Sales - Fuel"

    # Staff cannot approve; head can submit->approve through the API.
    assert api["staff"].post(f"/api/v1/ar/special-invoices/{ssi.id}/approve/").status_code == 400
    assert api["staff"].post(f"/api/v1/ar/special-invoices/{ssi.id}/submit/").status_code == 200
    assert (
        api["head"].post(f"/api/v1/ar/special-invoices/{ssi.id}/approve/").status_code
        == 200
    )
    ssi.refresh_from_db()
    assert ssi.status == "posted"
    assert ssi.journal_entry is not None

    # Posted invoices are immutable via the API.
    resp = api["staff"].patch(
        f"/api/v1/ar/special-invoices/{ssi.id}/",
        {"notes": "late edit"},
        format="json",
    )
    assert resp.status_code == 403


def test_ssi_api_reject_roundtrip(customer, segment, fuel_sales_account, accounts, role_users):
    api = _api_clients(role_users)
    resp = api["staff"].post(
        "/api/v1/ar/special-invoices/",
        {
            "customer": customer.id,
            "transaction_date": "2026-02-10",
            "segment": segment.id,
            "delivery_receipt_no": "DR-API-2",
            "lines": _api_lines(segment),
        },
        format="json",
    )
    assert resp.status_code == 201
    ssi = SpecialSalesInvoice.objects.get()
    api["staff"].post(f"/api/v1/ar/special-invoices/{ssi.id}/submit/")
    resp = api["head"].post(
        f"/api/v1/ar/special-invoices/{ssi.id}/reject/", {"note": ""}, format="json"
    )
    assert resp.status_code == 400
    resp = api["head"].post(
        f"/api/v1/ar/special-invoices/{ssi.id}/reject/",
        {"note": "fix the DR no"},
        format="json",
    )
    assert resp.status_code == 200
    ssi.refresh_from_db()
    assert ssi.status == "draft"
    assert ssi.rejection_note == "fix the DR no"


def test_ssi_api_validation_errors_are_400(
    customer, segment, fuel_sales_account, accounts, role_users
):
    api = _api_clients(role_users)
    base = {
        "customer": customer.id,
        "transaction_date": "2026-02-10",
        "segment": segment.id,
        "lines": _api_lines(segment),
    }
    bad_lines = _api_lines(segment)
    bad_lines[1]["credit"] = "1.00"  # out of balance
    assert (
        api["staff"].post("/api/v1/ar/special-invoices/", {**base, "lines": bad_lines}, format="json").status_code
        == 400
    )
    unknown = _api_lines(segment)
    unknown[0]["account"] = "99999"
    assert (
        api["staff"].post("/api/v1/ar/special-invoices/", {**base, "lines": unknown}, format="json").status_code
        == 400
    )
    assert (
        api["staff"].post("/api/v1/ar/special-invoices/", {**base, "segment": 99999}, format="json").status_code
        == 400
    )


def test_ssi_flush_demo_clears_ssi(customer, segment, fuel_sales_account, accounts, user, role_users):
    from django.core.management import call_command

    from apps.ar.models import SpecialSalesInvoiceLine
    from apps.posting.models import JournalEntry

    ssi = SpecialInvoiceService.create_ssi(
        customer=customer,
        transaction_date=date(2026, 2, 10),
        segment=segment,
        delivery_receipt_no='DR-FLUSH',
        lines=[
            {'account': '12030', 'segment': segment, 'debit': '100.00'},
            {'account': '40000', 'segment': segment, 'credit': '100.00'},
        ],
        created_by=user,
    )
    SpecialInvoiceService.submit(ssi, user=user)
    SpecialInvoiceService.approve(ssi, user=role_users['head'])
    je_id = SpecialSalesInvoice.objects.get(pk=ssi.pk).journal_entry_id

    call_command('flush_demo', assume_yes=True)

    assert SpecialSalesInvoice.objects.count() == 0
    assert SpecialSalesInvoiceLine.objects.count() == 0
    assert not JournalEntry.objects.filter(pk=je_id).exists()
    # Foundation is preserved (customers are flushed by design).
    from apps.foundation.models import Account, Company, Segment

    assert Company.objects.count() == 1
    assert Segment.objects.filter(pk=segment.pk).exists()
    assert Account.objects.filter(code="12030").exists()

