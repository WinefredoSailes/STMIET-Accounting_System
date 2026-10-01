"""Computed-answer handler tests against a seeded mini set of books.

Fixtures post real journal entries through PostingService so the GL
projection, RFP/CV payables and AR balances behave exactly like production.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils.timezone import make_aware

from apps.ap.models import AdvanceToEmployee, CheckVoucher, POLine, PurchaseOrder, RFPDocument, RFPLine, Supplier
from apps.ar.models import AcknowledgmentReceipt, ARInvoice, Customer
from apps.assistant.answers.context import Entities, QContext
from apps.cash.models import BankAccount, CheckDisbursement
from apps.foundation.models import Account, Segment
from apps.posting.models import GeneralLedger, JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService

User = get_user_model()


def _post(company, segment, date_, lines, entry_no, desc, *, approved_by=None):
    """Post a balanced JE from (account_code, amount) with sign Dr(+)/Cr(-)."""
    je = JournalEntry.objects.create(
        entry_no=entry_no,
        company=company,
        segment=segment,
        transaction_date=date_,
        status=PostingStatus.DRAFT,
        description=desc,
        source_doc_type="TEST",
        source_doc_no=entry_no,
    )
    line_no = 1
    for code, raw in lines:
        amount = Decimal(raw)
        JournalEntryLine.objects.create(
            entry=je,
            line_no=line_no,
            account=Account.objects.get(code=code),
            debit=amount if amount >= 0 else Decimal("0.00"),
            credit=-amount if amount < 0 else Decimal("0.00"),
        )
        line_no += 1
    je.recalc_totals()
    je.save(update_fields=["total_debit", "total_credit", "updated_at"])
    if approved_by:
        je.approved_by = approved_by
    return PostingService.post(je, user=None)


@pytest.fixture
def books(company, segment, accounts, user, role_users):
    """A realistic mini-book: supplier+AP, customer+AR, bank, advances."""
    head = role_users["head"]
    today = date(2026, 9, 15)
    now = date.today()

    # -- supplier + posted RFP (open payable) ----------------------------
    limdon = Supplier.objects.create(
        code="S001", name="Limdon Sales Corporation", default_segment=segment, approval_status="approved"
    )
    rfp_je = _post(company, segment, today, [("61100", "100000.00"), ("20000", "-100000.00")], "JE-2026-0201", "RFP payment - Limdon", approved_by=head)
    rfp_je.source_doc_type = "RFP"
    rfp_je.source_doc_no = "A2026-0001"
    rfp_je.save(update_fields=["source_doc_type", "source_doc_no", "updated_at"])
    rfp = RFPDocument.objects.create(
        ap_number="A2026-0001", rfp_date=today, payee=limdon, segment=segment,
        particulars="Fuel purchase", amount=Decimal("100000.00"), status="posted",
        journal_entry=rfp_je, created_by=user, approved_by_fin=head,
    )
    RFPLine.objects.create(rfp=rfp, line_no=1, side="dr", segment=segment, account=Account.objects.get(code="61100"), amount=Decimal("100000.00"))
    RFPLine.objects.create(rfp=rfp, line_no=2, side="cr", segment=segment, account=Account.objects.get(code="20000"), amount=Decimal("100000.00"))

    # -- cleared CV payment on that RFP (reduces payable) -----------------
    bank_acc = accounts["10110"]
    cv_je = _post(company, segment, today + timedelta(days=5), [("20000", "60000.00"), ("10110", "-60000.00")], "JE-2026-0206", "CV clearing - Limdon")
    cv = CheckVoucher.objects.create(
        cv_number="CV-2026-0001", cv_date=today + timedelta(days=5), rfp=rfp, payee=limdon,
        bank_account=bank_acc, gross_amount=Decimal("60000.00"), withheld_tax=Decimal("0.00"),
        net_amount=Decimal("60000.00"), check_no="888001", status="cleared",
        journal_entry=cv_je, approved_by=head,
    )
    CheckDisbursement.objects.create(
        cv=cv, cleared_at=make_aware(datetime.combine(cv_je.transaction_date, datetime.min.time())),
        status="cleared",
    )

    # -- PO + lines with PR numbers (B16/B17) -----------------------------
    po = PurchaseOrder.objects.create(
        po_number="PO-2026-0001", po_date=today, supplier=limdon, segment=segment,
        amount=Decimal("100000.00"), status="approved",
    )
    POLine.objects.create(po=po, line_no=1, pr_number="2026-189", qty=Decimal("10"), unit="LTR", description="Diesel", unit_price=Decimal("8000.00"), amount=Decimal("80000.00"))
    POLine.objects.create(po=po, line_no=2, pr_number="2026-190", qty=Decimal("1"), unit="PC", description="Oil filter", unit_price=Decimal("20000.00"), amount=Decimal("20000.00"))
    rfp.po = po
    rfp.save(update_fields=["po", "updated_at"])

    # -- customer + open invoice + posted receipt --------------------------
    c1 = Customer.objects.create(code="C001", name="Maple Fuel Corp", approval_status="approved")
    inv_je = _post(company, segment, today - timedelta(days=45), [("12030", "50000.00"), ("41010", "-50000.00")], "JE-2026-0140", "SI 1002 - Maple")
    inv = ARInvoice.objects.create(
        invoice_no="SI-2026-1002", customer=c1, transaction_date=today - timedelta(days=45),
        segment=segment, total=Decimal("50000.00"), status="open", journal_entry=inv_je,
    )
    rec_je = _post(company, segment, today - timedelta(days=10), [("10010", "20000.00"), ("12030", "-20000.00")], "JE-2026-0177", "AR receipt - Maple")
    AcknowledgmentReceipt.objects.create(
        receipt_no="AR-2026-0001", customer=c1, transaction_date=today - timedelta(days=10),
        amount=Decimal("20000.00"), cash_account=Account.objects.get(code="10010"),
        segment=segment, journal_entry=rec_je, status="posted",
        applied_to=inv, collected_by=user,
    )

    # -- bank account -------------------------------------
    bank = BankAccount.objects.create(
        code="BDO-CHK", name="BDO Checking", bank_name="BDO", account_type="checking",
        gl_account=bank_acc, company=company, is_active=True,
    )

    # -- advances ----------------------------------------------------------
    a1 = AdvanceToEmployee.objects.create(
        employee_name="Anna Cruz", kind="employee", segment=segment,
        granted_date=today - timedelta(days=120), amount=Decimal("30000.00"),
        liquidated_amount=Decimal("10000.00"), status="granted",
    )
    AdvanceToEmployee.objects.create(
        employee_name="Ben Dy", kind="officer", segment=segment,
        granted_date=today - timedelta(days=60), amount=Decimal("20000.00"),
        liquidated_amount=Decimal("0.00"), status="granted",
    )

    return {
        "limdon": limdon, "rfp": rfp, "cv": cv, "po": po,
        "customer": c1, "invoice": inv, "receipt": AcknowledgmentReceipt.objects.get(receipt_no="AR-2026-0001"),
        "bank": bank, "bank_account": bank_acc, "advance": a1,
        "je_rfp": rfp_je, "cv_je": cv_je,
        "head": head, "user": user,
    }


def _ctx(books, entities, lower="", user=None):
    return QContext(
        user=user or books["user"], raw=lower or "test", lower=lower or "test",
        terms=[], companies=[books["rfp"].segment.company], entities=entities,
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    # guards: handlers must never touch the network
    import socket

    def deny(*a, **k):
        raise AssertionError("network call attempted")

    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "gethostbyname", deny)


class TestAPHandlers:
    def test_supplier_balance(self, books):
        from apps.assistant.answers.handlers.ap import supplier_balance

        e = Entities(supplier=books["limdon"])
        ans = supplier_balance(_ctx(books, e, "how much do we owe limdon"), e)
        assert ans.kind == "answer"
        assert ans.qid == "C25"
        assert Decimal(books["cv"].gross_amount) == Decimal("60000.00")
        # billed 100k, paid 60k -> outstanding 40k
        assert "40,000.00" in ans.summary

    def test_open_payables(self, books):
        from apps.assistant.answers.handlers.ap import open_payables

        e = Entities()
        ans = open_payables(_ctx(books, e, "open payables"), e)
        assert ans.rows and ans.rows[0]["RFP"] == "A2026-0001"
        assert "40,000.00" in ans.summary

    def test_supplier_payments(self, books):
        from apps.assistant.answers.handlers.ap import supplier_payments

        e = Entities(supplier=books["limdon"])
        ans = supplier_payments(_ctx(books, e, "payments made to limdon"), e)
        assert ans.qid == "C28"
        assert ans.rows and ans.rows[0]["Check"] == "888001"

    def test_payment_date_a5(self, books):
        from apps.assistant.answers.handlers.ap import supplier_payments

        e = Entities(supplier=books["limdon"])
        ans = supplier_payments(_ctx(books, e, "when did we pay limdon"), e)
        assert ans.qid == "A5"
        assert "2026-09-20" in ans.summary

    def test_supplier_aging(self, books):
        from apps.assistant.answers.handlers.ap import supplier_aging

        e = Entities(supplier=books["limdon"])
        ans = supplier_aging(_ctx(books, e, "supplier aging"), e)
        assert ans.qid == "C30"
        assert ans.metrics and ans.metrics[0]["value"].startswith("₱")


class TestARHandlers:
    def test_customer_balance(self, books):
        from apps.assistant.answers.handlers.ar import customer_balance

        e = Entities(customer=books["customer"])
        ans = customer_balance(_ctx(books, e, "customer balance"), e)
        assert ans.qid == "D31"
        assert "30,000.00" in ans.summary  # 50k open - 20k paid

    def test_unpaid_invoices(self, books):
        from apps.assistant.answers.handlers.ar import unpaid_invoices

        e = Entities()
        ans = unpaid_invoices(_ctx(books, e, "unpaid invoices"), e)
        assert ans.qid == "D32"
        assert ans.rows[0]["Invoice"] == "SI-2026-1002"

    def test_last_payment(self, books):
        from apps.assistant.answers.handlers.ar import last_payment

        e = Entities(customer=books["customer"])
        ans = last_payment(_ctx(books, e, "last payment"), e)
        assert ans.qid == "D33"
        assert "AR-2026-0001" in ans.summary

    def test_overdue(self, books):
        from apps.assistant.answers.handlers.ar import overdue

        e = Entities()
        ans = overdue(_ctx(books, e, "receivables overdue"), e)
        assert ans.qid == "D35"
        assert ans.rows  # 45-day-old invoice is overdue

    def test_customer_ledger(self, books):
        from apps.assistant.answers.handlers.ar import customer_ledger

        e = Entities(customer=books["customer"])
        ans = customer_ledger(_ctx(books, e, "customer ledger"), e)
        assert ans.qid == "D37"
        assert ans.rows


class TestLedgerHandlers:
    def test_balance(self, books):
        from apps.assistant.answers.handlers.ledger import balance

        acc = Account.objects.get(code="10110")
        e = Entities(account=acc)
        ans = balance(_ctx(books, e, "balance of this account"), e)
        assert ans.qid == "E38"
        assert "60,000.00" in ans.summary

    def test_balance_as_of(self, books):
        from apps.assistant.answers.handlers.ledger import balance_as_of

        acc = Account.objects.get(code="10110")
        e = Entities(account=acc, as_of=date(2026, 9, 18))
        ans = balance_as_of(_ctx(books, e, "balance as of"), e)
        # CV cleared on 9/20 -> zero balance before it
        assert "0.00" in ans.summary

    def test_balance_as_of_after(self, books):
        from apps.assistant.answers.handlers.ledger import balance_as_of

        acc = Account.objects.get(code="10110")
        e = Entities(account=acc, as_of=date(2026, 9, 30))
        ans = balance_as_of(_ctx(books, e), e)
        assert "60,000.00" in ans.summary

    def test_movement_reason(self, books):
        from apps.assistant.answers.handlers.ledger import movement_reason

        acc = Account.objects.get(code="10110")
        e = Entities(account=acc, period=__import__("apps.assistant.answers.base", fromlist=["ResolvedPeriod"]).ResolvedPeriod(date(2026, 9, 1), date(2026, 9, 30)))
        ans = movement_reason(_ctx(books, e), e)
        assert ans.qid == "E40"
        assert ans.rows


class TestCashHandlers:
    def test_bank_balance(self, books):
        from apps.assistant.answers.handlers.cash import bank_balance

        e = Entities(bank=books["bank"])
        ans = bank_balance(_ctx(books, e), e)
        assert ans.qid == "F46"
        assert "60,000.00" in ans.summary

    def test_total_cash(self, books):
        from apps.assistant.answers.handlers.cash import total_cash

        e = Entities()
        ans = total_cash(_ctx(books, e), e)
        assert ans.qid == "F47"
        assert "60,000.00" in ans.summary

    def test_outstanding_checks(self, books):
        from apps.assistant.answers.handlers.cash import outstanding_checks

        e = Entities()
        ans = outstanding_checks(_ctx(books, e), e)
        assert not ans.rows  # the one disbursement is cleared

    def test_transfers(self, books):
        from apps.assistant.answers.handlers.cash import transfers

        e = Entities()
        ans = transfers(_ctx(books, e), e)
        assert ans.qid == "F54"


class TestJournalHandlers:
    def test_lookup_via_rfp(self, books):
        from apps.assistant.answers.handlers.journal import lookup

        e = Entities(rfp=books["rfp"])
        ans = lookup(_ctx(books, e, "je for this rfp"), e)
        assert ans.qid == "H65"
        assert ans.metrics[0]["value"] == "JE-2026-0201"

    def test_debits(self, books):
        from apps.assistant.answers.handlers.journal import debits

        e = Entities(je=books["je_rfp"])
        ans = debits(_ctx(books, e), e)
        assert ans.qid == "H66"
        assert ans.rows and "61100" in ans.rows[0]["Account"]

    def test_credits(self, books):
        from apps.assistant.answers.handlers.journal import credits

        e = Entities(je=books["je_rfp"])
        ans = credits(_ctx(books, e), e)
        assert ans.rows and "20000" in ans.rows[0]["Account"]

    def test_reference(self, books):
        from apps.assistant.answers.handlers.journal import reference

        e = Entities(je=books["je_rfp"])
        ans = reference(_ctx(books, e), e)
        assert ans.qid == "H68"


class TestPaymentHandlers:
    def test_requested_by(self, books):
        from apps.assistant.answers.handlers.payment import requested_by

        e = Entities(rfp=books["rfp"])
        ans = requested_by(_ctx(books, e), e)
        assert ans.qid == "G55"
        assert "tester" in ans.summary

    def test_approved_by(self, books):
        from apps.assistant.answers.handlers.payment import approved_by

        e = Entities(rfp=books["rfp"])
        ans = approved_by(_ctx(books, e), e)
        assert ans.qid == "G56"
        assert "head" in ans.summary

    def test_check_status(self, books):
        from apps.assistant.answers.handlers.payment import check_status

        e = Entities(cv=books["cv"])
        ans = check_status(_ctx(books, e, "cleared"), e)
        assert ans.qid == "G60"
        assert "cleared" in ans.summary


class TestPurchaseHandlers:
    def test_pr_numbers(self, books):
        from apps.assistant.answers.handlers.purchase import pr_numbers

        e = Entities(po=books["po"])
        ans = pr_numbers(_ctx(books, e), e)
        assert ans.qid == "B16"
        assert "2026-189" in ans.summary

    def test_po_of(self, books):
        from apps.assistant.answers.handlers.purchase import po_of

        e = Entities(rfp=books["rfp"])
        ans = po_of(_ctx(books, e), e)
        assert ans.qid == "B17"
        assert "PO-2026-0001" in ans.summary

    def test_cv_of(self, books):
        from apps.assistant.answers.handlers.purchase import cv_of

        e = Entities(po=books["po"])
        ans = cv_of(_ctx(books, e), e)
        assert ans.qid == "B21"
        assert ans.rows[0]["CV"] == "CV-2026-0001"

    def test_check_of(self, books):
        from apps.assistant.answers.handlers.purchase import check_of

        e = Entities(po=books["po"])
        ans = check_of(_ctx(books, e), e)
        assert ans.qid == "B22"
        assert "888001" in ans.summary


class TestAdvancesHandlers:
    def test_total(self, books):
        from apps.assistant.answers.handlers.advances import total

        e = Entities()
        ans = total(_ctx(books, e), e)
        assert ans.qid == "I73"
        assert "40,000.00" in ans.summary  # Anna 20k outstanding + Ben 20k

    def test_employee_list(self, books):
        from apps.assistant.answers.handlers.advances import employee_list

        e = Entities()
        ans = employee_list(_ctx(books, e), e)
        assert ans.qid == "I78"
        assert any("Anna Cruz" in r["Name"] for r in ans.rows)

    def test_history(self, books):
        from apps.assistant.answers.handlers.advances import history

        e = Entities(party_text="Anna")
        ans = history(_ctx(books, e), e)
        assert ans.qid == "I80"
        assert "Anna Cruz" in ans.rows[0]["Name"]


class TestReportHandlers:
    @pytest.fixture
    def templates(self, db):
        from apps.reporting.services import StatementTemplateService

        StatementTemplateService.seed_defaults()
        StatementTemplateService.seed_defaults()  # idempotent
        return True

    def test_net_income(self, books, templates):
        from datetime import date

        from apps.assistant.answers.base import ResolvedPeriod
        from apps.assistant.answers.handlers.reports import net_income

        e = Entities(period=ResolvedPeriod(date(2026, 9, 1), date(2026, 9, 30)))
        ans = net_income(_ctx(books, e), e)
        assert ans.qid == "K90"
        assert ans.metrics[0]["value"].replace("-", "", 1).startswith("₱")
        assert "100,000.00" in ans.metrics[0]["value"]  # September = net loss (only expenses)

    def test_trial_balance(self, books, templates):
        from datetime import date

        from apps.assistant.answers.base import ResolvedPeriod
        from apps.assistant.answers.handlers.reports import trial_balance

        e = Entities(period=ResolvedPeriod(date(2026, 9, 1), date(2026, 9, 30)))
        ans = trial_balance(_ctx(books, e), e)
        assert ans.qid == "K96"
        assert any(r["Code"] == "10110" for r in ans.rows)

    def test_total_payable(self, books, templates):
        from apps.assistant.answers.handlers.reports import total_payable

        e = Entities()
        ans = total_payable(_ctx(books, e), e)
        assert ans.qid == "K94"
        assert "40,000.00" in ans.summary

    def test_total_receivable(self, books, templates):
        from apps.assistant.answers.handlers.reports import total_receivable

        e = Entities()
        ans = total_receivable(_ctx(books, e), e)
        assert ans.qid == "K93"
        assert "30,000.00" in ans.summary

    def test_compare_periods(self, books, templates):
        from datetime import date

        from apps.assistant.answers.base import ResolvedPeriod
        from apps.assistant.answers.handlers.reports import compare_periods

        e = Entities(period=ResolvedPeriod(date(2026, 9, 1), date(2026, 9, 30)))
        ans = compare_periods(_ctx(books, e), e)
        assert ans.qid == "K100"
        assert len(ans.rows) == 3

    def test_cash_flow(self, books, templates):
        from datetime import date

        from apps.assistant.answers.base import ResolvedPeriod
        from apps.assistant.answers.handlers.reports import cash_flow

        e = Entities(period=ResolvedPeriod(date(2026, 9, 1), date(2026, 9, 30)))
        ans = cash_flow(_ctx(books, e), e)
        assert ans.qid == "K99"


class TestStubNotices:
    def test_not_tracked(self, books):
        from apps.assistant.answers.handlers.stubs import not_tracked
        from apps.assistant.catalog import CATALOG_BY_ID

        entry = CATALOG_BY_ID["B24"]
        e = Entities(po=books["po"])
        ctx = _ctx(books, e, "supporting documents")
        ctx.entry = entry
        ans = not_tracked(ctx, e)
        assert ans.qid == "B24"
        assert "not captured" in ans.summary