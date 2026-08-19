"""AP contract tests (BUILD-PLAN Phase 3).

- RFP canonical JE: Dr lines | Cr Advances 20k | Cr AP balance (RESOLUTION #5)
- P2,500 threshold; advance < total; line sums must equal amount
- 4-level approval, same-person rule, CNR escalation >P100k (ADR-020)
- CONSO batch posts all RFPs atomically (POSTING_RULES 7.3)
- CV clears AP with WHT split (7.4)
- Advance lifecycle grant -> liquidate (ADR-021)
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.ap.models import AdvanceToEmployee, CheckVoucher, CONSOBatch, RFPDocument, Supplier
from apps.ap.services import (
    AdvanceService,
    CONSOService,
    CVPaymentService,
    RFPService,
)
from apps.core.exceptions import ValidationError
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus


@pytest.fixture
def supplier(db, segment):
    return Supplier.objects.create(code="S001", name="Shandong Fuel Depot", default_segment=segment)


@pytest.fixture
def rfp_lines(db, segment, accounts):
    return [{"segment": segment, "account_code": "61100", "amount": "85000.00"}]


@pytest.fixture
def alywin(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="alywin", password="x")


class TestRFPCreation:
    def test_canonical_je_balances(self, company, segment, supplier, rfp_lines, alywin):
        rfp = RFPService.create_rfp(
            ap_number="A0001", rfp_date=date(2026, 1, 15), payee=supplier,
            particulars="Fuel delivery", amount="85000.00", segment=segment,
            lines=rfp_lines, user=alywin,
        )
        assert rfp.advance_amount == Decimal("20000.00")
        assert rfp.ap_balance == Decimal("65000.00")
        assert supplier.last_ap == "A0001"

    def test_below_threshold_rejected(self, company, segment, supplier, alywin):
        with pytest.raises(ValidationError, match="petty cash"):
            RFPService.create_rfp(
                ap_number="A0002", rfp_date=date(2026, 1, 15), payee=supplier,
                particulars="Small", amount="2400.00", segment=segment,
                lines=[{"segment": segment, "account_code": "61100", "amount": "2400.00"}],
                user=alywin,
            )

    def test_line_sums_must_match_amount(self, company, segment, supplier, alywin):
        with pytest.raises(ValidationError, match="Charge lines total"):
            RFPService.create_rfp(
                ap_number="A0003", rfp_date=date(2026, 1, 15), payee=supplier,
                particulars="Mismatch", amount="10000.00", segment=segment,
                advance_amount="5000.00",
                lines=[{"segment": segment, "account_code": "61100", "amount": "9999.00"}],
                user=alywin,
            )

    def test_advance_must_be_less_than_total(self, company, segment, supplier, alywin):
        with pytest.raises(ValidationError, match="Advance credit"):
            RFPService.create_rfp(
                ap_number="A0004", rfp_date=date(2026, 1, 15), payee=supplier,
                particulars="No-op", amount="20000.00", segment=segment,
                advance_amount="20000.00",
                lines=[{"segment": segment, "account_code": "61100", "amount": "20000.00"}],
                user=alywin,
            )

    def test_empty_amount_raises_friendly_validation_error(self, company, segment, supplier, alywin, accounts):
        """Regression: a blank form field must not 500 with decimal.InvalidOperation."""
        with pytest.raises(ValidationError, match="Amount cannot be empty"):
            RFPService.create_rfp(
                ap_number="A0005", rfp_date=date(2026, 1, 15), payee=supplier,
                particulars="Blank amount", amount="", segment=segment,
                lines=[{"segment": segment, "account_code": "61100", "amount": "85000.00"}],
                user=alywin,
            )

    def test_empty_advance_raises_friendly_validation_error(self, company, segment, supplier, alywin, accounts):
        with pytest.raises(ValidationError, match="Amount cannot be empty"):
            RFPService.create_rfp(
                ap_number="A0006", rfp_date=date(2026, 1, 15), payee=supplier,
                particulars="Blank advance", amount="85000.00", segment=segment,
                advance_amount="",
                lines=[{"segment": segment, "account_code": "61100", "amount": "85000.00"}],
                user=alywin,
            )

    def test_malformed_amount_raises_friendly_validation_error(self, company, segment, supplier, alywin, accounts):
        with pytest.raises(ValidationError, match="Invalid amount"):
            RFPService.create_rfp(
                ap_number="A0007", rfp_date=date(2026, 1, 15), payee=supplier,
                particulars="Text in amount", amount="85000.abc", segment=segment,
                lines=[{"segment": segment, "account_code": "61100", "amount": "85000.00"}],
                user=alywin,
            )

    def test_thousands_separators_are_stripped(self, company, segment, supplier, alywin, accounts):
        """Users may paste '85,000.00'; money() normalizes it."""
        rfp = RFPService.create_rfp(
            ap_number="A0008", rfp_date=date(2026, 1, 15), payee=supplier,
            particulars="Comma amount", amount="85,000.00", segment=segment,
            lines=[{"segment": segment, "account_code": "61100", "amount": "85000.00"}],
            user=alywin,
        )
        assert rfp.amount == Decimal("85000.00")


class TestRFPApproval:
    def test_four_level_chain(self, company, segment, supplier, rfp_lines, alywin):
        check = type("U", (), {})()
        # Real users for each role.
        from django.contrib.auth import get_user_model

        User = get_user_model()
        checker = User.objects.create_user(username="checker", password="x")
        acctg = User.objects.create_user(username="acctg", password="x")
        fin = User.objects.create_user(username="fin", password="x")

        rfp = RFPService.create_rfp(
            ap_number="A0010", rfp_date=date(2026, 1, 15), payee=supplier,
            particulars="Chain", amount="50000.00", segment=segment,
            lines=[{"segment": segment, "account_code": "61100", "amount": "50000.00"}],
            user=alywin,
        )
        assert rfp.status == "prepared"

        rfp = RFPService.advance_step(rfp, role="checked", user=checker)
        assert rfp.status == "checked"
        rfp = RFPService.advance_step(rfp, role="acctg_approved", user=acctg)
        rfp = RFPService.advance_step(rfp, role="fin_approved", user=fin)
        assert rfp.status == "fin_approved"
        assert rfp.approved_by_fin == fin

        # Same person cannot hold two roles (checked then acctg_approved).
        rfp2 = RFPService.create_rfp(
            ap_number="A0011", rfp_date=date(2026, 1, 16), payee=supplier,
            particulars="Same person", amount="5000.00", segment=segment,
            advance_amount="4000.00",
            lines=[{"segment": segment, "account_code": "61100", "amount": "5000.00"}],
            user=alywin,
        )
        rfp2 = RFPService.advance_step(rfp2, role="checked", user=checker)
        with pytest.raises(ValidationError, match="same user"):
            RFPService.advance_step(rfp2, role="acctg_approved", user=checker)

    def test_cnr_escalation(self, company, segment, supplier, rfp_lines, alywin):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        checker = User.objects.create_user(username="checker2", password="x")
        acctg = User.objects.create_user(username="acctg2", password="x")
        fin = User.objects.create_user(username="fin2", password="x")
        cnr = User.objects.create_user(username="cnr", password="x")

        rfp = RFPService.create_rfp(
            ap_number="A0020", rfp_date=date(2026, 1, 15), payee=supplier,
            particulars="Big", amount="150000.00", segment=segment,
            lines=[{"segment": segment, "account_code": "61100", "amount": "150000.00"}],
            user=alywin,
        )
        for role, u in (("checked", checker), ("acctg_approved", acctg), ("fin_approved", fin)):
            rfp = RFPService.advance_step(rfp, role=role, user=u)
        rfp = RFPService.approve_cnr(rfp, user=cnr)
        assert rfp.approved_by_cnr == cnr


class TestCONSOPosting:
    def test_batch_posts_all_rfps(self, company, segment, supplier, rfp_lines, alywin, accounts):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        checker = User.objects.create_user(username="checker3", password="x")
        acctg = User.objects.create_user(username="acctg3", password="x")
        fin = User.objects.create_user(username="fin3", password="x")

        rfp1, rfp2 = [], []
        for i, amt in enumerate(("30000.00", "40000.00"), start=1):
            r = RFPService.create_rfp(
                ap_number=f"A888{i}0", rfp_date=date(2026, 1, 15), payee=supplier,
                particulars=f"Batch {i}", amount=amt, segment=segment,
                lines=[{"segment": segment, "account_code": "61100", "amount": amt}],
                user=alywin,
            )
            for role, u in (("checked", checker), ("acctg_approved", acctg), ("fin_approved", fin)):
                r = RFPService.advance_step(r, role=role, user=u)
            rfp1.append(r)

        batch = CONSOBatch.objects.create(batch_no="CONSO-2026-01", conso_date=date(2026, 1, 20))
        for r in rfp1:
            r.conso = batch
            r.save(update_fields=["conso", "updated_at"])

        CONSOService.post_batch(batch, user=acctg)

        batch.refresh_from_db()
        assert batch.status == "posted"
        for r in rfp1:
            r.refresh_from_db()
            assert r.status == "posted"
            assert r.journal_entry is not None
            je = r.journal_entry
            assert je.is_balanced
            lines = {l.line_no: l for l in je.lines.all()}
            # line 1 debit = amount; last line credit = AP balance.
            assert lines[1].debit == r.amount
            assert lines[3].credit == r.ap_balance
            assert lines[2].account.code == "12070"  # advances DHPP

    def test_batch_requires_finance_approval(self, company, segment, supplier, rfp_lines, alywin, accounts):
        rfp = RFPService.create_rfp(
            ap_number="A88809", rfp_date=date(2026, 1, 15), payee=supplier,
            particulars="Unapproved", amount="5000.00", segment=segment,
            advance_amount="4000.00",
            lines=[{"segment": segment, "account_code": "61100", "amount": "5000.00"}],
            user=alywin,
        )
        batch = CONSOBatch.objects.create(batch_no="CONSO-2026-02", conso_date=date(2026, 1, 20))
        rfp.conso = batch
        rfp.save(update_fields=["conso", "updated_at"])
        with pytest.raises(ValidationError, match="finance-approved"):
            CONSOService.post_batch(batch, user=alywin)


class TestCVPayment:
    def test_wht_split_clears_ap(self, company, segment, supplier, accounts, alywin):
        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0001", cv_date=date(2026, 1, 25),
            payee=supplier, bank_account=accounts["10010"],
            gross_amount="10000.00", withheld_tax="200.00",
        )
        cv.refresh_from_db()
        assert cv.net_amount == Decimal("9800.00")
        je = cv.journal_entry
        assert je.is_balanced
        lines = {l.line_no: l for l in je.lines.all()}
        assert lines[1].debit == Decimal("10000.00")  # Dr AP
        assert lines[2].credit == Decimal("9800.00")  # Cr Cash
        assert lines[3].credit == Decimal("200.00")  # Cr WHT
        assert lines[3].account.code == "64110"

    def test_no_wht_when_zero(self, company, segment, supplier, accounts, alywin):
        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0002", cv_date=date(2026, 1, 26),
            payee=supplier, bank_account=accounts["10010"],
            gross_amount="5000.00", withheld_tax="0.00",
        )
        assert cv.net_amount == Decimal("5000.00")
        assert cv.journal_entry.lines.count() == 2


class TestAdvanceLifecycle:
    def test_grant_liquidate_close(self, db, segment, accounts, supplier, alywin):
        adv = AdvanceService.start(
            employee_name="Quibs Malicdem", kind=AdvanceToEmployee.REIMBURSEMENT,
            segment=segment, granted_date=date(2026, 1, 10), amount="20000.00",
        )
        assert adv.outstanding == Decimal("20000.00")
        adv = AdvanceService.liquidate(adv, amount="12000.00", liquidate_date=date(2026, 1, 20))
        assert adv.status == "partially_liquidated"
        assert adv.outstanding == Decimal("8000.00")
        adv = AdvanceService.liquidate(adv, amount="8000.00", liquidate_date=date(2026, 1, 25))
        assert adv.status == "liquidated"

    def test_over_liquidation_rejected(self, db, segment, supplier, alywin):
        adv = AdvanceService.start(
            employee_name="Leaslyn", kind=AdvanceToEmployee.OFFICER,
            segment=segment, granted_date=date(2026, 1, 10), amount="5000.00",
        )
        with pytest.raises(ValidationError):
            AdvanceService.liquidate(adv, amount="6000.00", liquidate_date=date(2026, 1, 20))
