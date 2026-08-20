"""AP contract tests (BUILD-PLAN Phase 3).

- RFP JE is built exactly from the Dr/Cr distribution lines as entered;
  Dr total must equal Cr total, amount = total of debit lines
- P2,500 threshold on the debit total
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
    return [
        {"side": "dr", "segment": segment, "account_code": "61100", "amount": "85000.00", "description": "Fuel delivery"},
        {"side": "cr", "segment": segment, "account_code": "20000", "amount": "85000.00", "description": "AP - Shandong Fuel Depot"},
    ]


@pytest.fixture
def alywin(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="alywin", password="x")


class TestRFPCreation:
    def test_manual_sides_drive_amount_and_particulars(self, company, segment, supplier, rfp_lines, alywin):
        rfp = RFPService.create_rfp(
            ap_number="A0001", rfp_date=date(2026, 1, 15), payee=supplier,
            segment=segment, lines=rfp_lines, user=alywin,
        )
        assert rfp.amount == Decimal("85000.00")  # total of the debit lines
        assert rfp.particulars == "Fuel delivery"  # mirrors the first line's description
        assert supplier.last_ap == "A0001"
        sides = {l.side for l in rfp.lines.all()}
        assert sides == {"dr", "cr"}

    def test_below_threshold_rejected(self, company, segment, supplier, alywin, accounts):
        with pytest.raises(ValidationError, match="petty cash"):
            RFPService.create_rfp(
                ap_number="A0002", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
                lines=[
                    {"side": "dr", "segment": segment, "account_code": "61100", "amount": "2400.00"},
                    {"side": "cr", "segment": segment, "account_code": "20000", "amount": "2400.00"},
                ],
                user=alywin,
            )

    def test_unbalanced_lines_rejected(self, company, segment, supplier, alywin, accounts):
        with pytest.raises(ValidationError, match="do not balance"):
            RFPService.create_rfp(
                ap_number="A0003", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
                lines=[
                    {"side": "dr", "segment": segment, "account_code": "61100", "amount": "10000.00"},
                    {"side": "cr", "segment": segment, "account_code": "20000", "amount": "5000.00"},
                ],
                user=alywin,
            )

    def test_invalid_side_rejected(self, company, segment, supplier, alywin, accounts):
        with pytest.raises(ValidationError, match="must be Dr or Cr"):
            RFPService.create_rfp(
                ap_number="A0004", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
                lines=[
                    {"side": "xx", "segment": segment, "account_code": "61100", "amount": "85000.00"},
                    {"side": "cr", "segment": segment, "account_code": "20000", "amount": "85000.00"},
                ],
                user=alywin,
            )

    def test_zero_amount_line_rejected(self, company, segment, supplier, alywin, accounts):
        with pytest.raises(ValidationError, match="greater than zero"):
            RFPService.create_rfp(
                ap_number="A0005", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
                lines=[
                    {"side": "dr", "segment": segment, "account_code": "61100", "amount": "0"},
                    {"side": "cr", "segment": segment, "account_code": "20000", "amount": "85000.00"},
                ],
                user=alywin,
            )

    def test_empty_amount_raises_friendly_validation_error(self, company, segment, supplier, alywin, accounts):
        """Regression: a blank line amount must not 500 with decimal.InvalidOperation."""
        with pytest.raises(ValidationError, match="Amount cannot be empty"):
            RFPService.create_rfp(
                ap_number="A0006", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
                lines=[
                    {"side": "dr", "segment": segment, "account_code": "61100", "amount": ""},
                    {"side": "cr", "segment": segment, "account_code": "20000", "amount": "85000.00"},
                ],
                user=alywin,
            )

    def test_malformed_amount_raises_friendly_validation_error(self, company, segment, supplier, alywin, accounts):
        with pytest.raises(ValidationError, match="Invalid amount"):
            RFPService.create_rfp(
                ap_number="A0007", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
                lines=[
                    {"side": "dr", "segment": segment, "account_code": "61100", "amount": "85000.abc"},
                    {"side": "cr", "segment": segment, "account_code": "20000", "amount": "85000.00"},
                ],
                user=alywin,
            )

    def test_thousands_separators_are_stripped(self, company, segment, supplier, alywin, accounts):
        """Users may paste '85,000.00'; money() normalizes it."""
        rfp = RFPService.create_rfp(
            ap_number="A0008", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "85,000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "85000.00"},
            ],
            user=alywin,
        )
        assert rfp.amount == Decimal("85000.00")

    def test_credit_account_lines_are_allowed(self, company, segment, supplier, alywin, accounts):
        """'Payables to officers' style credit lines are valid (Dr/Cr per line)."""
        rfp = RFPService.create_rfp(
            ap_number="A0009", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "85000.00", "description": "Machinery parts"},
                {"side": "cr", "segment": segment, "account_code": "21010", "amount": "85000.00", "description": "Payables to officers"},
            ],
            user=alywin,
        )
        assert rfp.amount == Decimal("85000.00")
        cr_line = rfp.lines.get(side="cr")
        assert cr_line.account.code == "21010"


class TestRFPApproval:
    def test_chain_with_head_holding_all_steps(self, company, segment, supplier,
                                               rfp_lines, alywin):
        """ADR-036: the Accounting & Finance Head (Alywin) checks then
        approves acctg + fin on the same RFP; the COO is a fresh hand."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        head = User.objects.create_user(username="head", password="x")
        coo = User.objects.create_user(username="coo", password="x")

        rfp = RFPService.create_rfp(
            ap_number="A0010", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "50000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "50000.00"},
            ],
            user=alywin,
        )
        assert rfp.status == "prepared"

        for role in ("checked", "acctg_approved", "fin_approved"):
            rfp = RFPService.advance_step(rfp, role=role, user=head)
        assert rfp.status == "fin_approved"
        assert rfp.checked_by == head and rfp.approved_by_acctg == head
        assert rfp.approved_by_fin == head

        # The preparer cannot approve their own disbursement.
        rfp2 = RFPService.create_rfp(
            ap_number="A0011", rfp_date=date(2026, 1, 16), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "5000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "5000.00"},
            ],
            user=alywin,
        )
        with pytest.raises(ValidationError, match="cannot approve it again"):
            RFPService.advance_step(rfp2, role="checked", user=alywin)

        # Re-recording a step is an explicit error, never silent.
        with pytest.raises(ValidationError, match="already recorded"):
            RFPService.advance_step(rfp, role="fin_approved", user=head)

        # The COO must be a fresh hand: someone who handled an earlier step
        # cannot sign as CNR.
        rfp3 = RFPService.create_rfp(
            ap_number="A0012", rfp_date=date(2026, 1, 17), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "150000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "150000.00"},
            ],
            user=alywin,
        )
        for role in ("checked", "acctg_approved", "fin_approved"):
            rfp3 = RFPService.advance_step(rfp3, role=role, user=head)
        with pytest.raises(ValidationError, match="did not"):
            RFPService.approve_cnr(rfp3, user=head)
        rfp3 = RFPService.approve_cnr(rfp3, user=coo)
        assert rfp3.approved_by_cnr == coo

    def test_cnr_escalation(self, company, segment, supplier, rfp_lines, alywin):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        head = User.objects.create_user(username="head", password="x")
        cnr = User.objects.create_user(username="cnr", password="x")

        rfp = RFPService.create_rfp(
            ap_number="A0020", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "150000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "150000.00"},
            ],
            user=alywin,
        )
        for role in ("checked", "acctg_approved", "fin_approved"):
            rfp = RFPService.advance_step(rfp, role=role, user=head)
        rfp = RFPService.approve_cnr(rfp, user=cnr)
        assert rfp.approved_by_cnr == cnr


class TestCONSOPosting:
    def test_batch_posts_all_rfps(self, company, segment, supplier, rfp_lines, alywin, accounts):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        head = User.objects.create_user(username="head", password="x")

        rfp1, rfp2 = [], []
        for i, amt in enumerate(("30000.00", "40000.00"), start=1):
            r = RFPService.create_rfp(
                ap_number=f"A888{i}0", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
                lines=[
                    {"side": "dr", "segment": segment, "account_code": "61100", "amount": amt},
                    {"side": "cr", "segment": segment, "account_code": "20000", "amount": amt},
                ],
                user=alywin,
            )
            for role in ("checked", "acctg_approved", "fin_approved"):
                r = RFPService.advance_step(r, role=role, user=head)
            rfp1.append(r)

        batch = CONSOBatch.objects.create(batch_no="CONSO-2026-01", conso_date=date(2026, 1, 20))
        for r in rfp1:
            r.conso = batch
            r.save(update_fields=["conso", "updated_at"])

        CONSOService.post_batch(batch, user=head)

        batch.refresh_from_db()
        assert batch.status == "posted"
        for r in rfp1:
            r.refresh_from_db()
            assert r.status == "posted"
            assert r.journal_entry is not None
            je = r.journal_entry
            assert je.is_balanced
            lines = {l.line_no: l for l in je.lines.all()}
            # lines are posted exactly as entered: Dr expense, Cr AP.
            assert lines[1].debit == r.amount
            assert lines[2].credit == r.amount
            assert lines[2].account.code == "20000"  # AP DHPP

    def test_batch_requires_finance_approval(self, company, segment, supplier, rfp_lines, alywin, accounts):
        rfp = RFPService.create_rfp(
            ap_number="A88809", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "5000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "5000.00"},
            ],
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
