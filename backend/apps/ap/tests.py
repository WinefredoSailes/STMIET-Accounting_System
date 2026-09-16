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

from apps.ap.models import ActionLog, AdvanceToEmployee, CheckVoucher, CONSOBatch, RFPDocument, Supplier
from apps.ap.services import (
    AdvanceService,
    CONSOService,
    CVPaymentService,
    RFPService,
)
from apps.core.exceptions import PostingError, ValidationError
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus

from django.core.management import call_command
from io import StringIO


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

    @pytest.mark.skip(reason="P2,000 RFP minimum temporarily removed (0217b7f) "
                             "for new-system setup; un-skip when the threshold is restored.")
    def test_below_threshold_rejected(self, company, segment, supplier, alywin, accounts):
        with pytest.raises(ValidationError, match="petty cash"):
            RFPService.create_rfp(
                ap_number="A0002", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
                lines=[
                    {"side": "dr", "segment": segment, "account_code": "61100", "amount": "1500.00"},
                    {"side": "cr", "segment": segment, "account_code": "20000", "amount": "1500.00"},
                ],
                user=alywin,
            )

    def test_threshold_is_2000_not_2500(self, company, segment, supplier, alywin, accounts):
        """ADR-038 §9c: RFP minimum is ₱2,000, so ₱2,200 must be accepted."""
        rfp = RFPService.create_rfp(
            ap_number="A0002B", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "2200.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "2200.00"},
            ],
            user=alywin,
        )
        assert rfp.amount == Decimal("2200.00")

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
                                               rfp_lines, role_users):
        """ADR-036: the Accounting & Finance Head (Alywin) checks then
        approves acctg + fin on the same RFP; the COO is a fresh hand.

        The head may also prepare his own RFP and approve it, since no
        separate staff exists; non-head preparers are still blocked."""
        head = role_users["head"]
        coo = role_users["coo"]
        staff = role_users["staff"]

        # The head prepares AND approves his own RFP end-to-end.
        rfp = RFPService.create_rfp(
            ap_number="A0010", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "50000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "50000.00"},
            ],
            user=head,
        )
        assert rfp.status == "prepared"
        assert rfp.created_by == head

        for role in ("checked", "acctg_approved", "fin_approved"):
            rfp = RFPService.advance_step(rfp, role=role, user=head)
        assert rfp.status == "fin_approved"
        assert rfp.checked_by == head and rfp.approved_by_acctg == head
        assert rfp.approved_by_fin == head

        # A staff preparer still cannot approve their own disbursement.
        rfp2 = RFPService.create_rfp(
            ap_number="A0011", rfp_date=date(2026, 1, 16), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "5000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "5000.00"},
            ],
            user=staff,
        )
        with pytest.raises(ValidationError, match="cannot approve it again"):
            RFPService.advance_step(rfp2, role="checked", user=staff)

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
            user=staff,
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

    def test_rejected_then_revised_chain_restarts_cleanly(
        self, company, segment, supplier, alywin, accounts
    ):
        """A head who already recorded a step, then rejected the RFP, can
        re-run the whole chain after the preparer revises. The stale step
        records (checked_by etc.) must not trip the 'already recorded this
        step' guard and leave the RFP stuck with the approver."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        head = User.objects.create_user(username="head", password="x")

        lines = [
            {"side": "dr", "segment": segment, "account_code": "61100", "amount": "50000.00",
             "description": "Fuel delivery"},
            {"side": "cr", "segment": segment, "account_code": "20000", "amount": "50000.00",
             "description": "AP - Fuel Depot"},
        ]
        rfp = RFPService.create_rfp(
            ap_number="A0013", rfp_date=date(2026, 1, 18), payee=supplier, segment=segment,
            lines=lines, user=alywin,
        )
        rfp.status = "submitted"
        rfp.save(update_fields=["status", "updated_at"])

        # Head checks the first pass, then rejects at the checked step.
        rfp = RFPService.advance_step(rfp, role="checked", user=head)
        assert rfp.status == "checked" and rfp.checked_by_id == head.id
        rfp = RFPService.reject(rfp, user=head, note="Reclassify the fuel charge.")

        # Preparer revises; the old chain records must be reset.
        rfp = RFPService.revise(rfp, user=alywin, purpose=rfp.purpose, lines=lines)
        assert rfp.status == "submitted"
        assert rfp.checked_by_id is None
        assert rfp.approved_by_acctg_id is None
        assert rfp.approved_by_fin_id is None
        assert rfp.revision_count == 1

        # The same head re-runs the full chain to fin_approved (no stuck state).
        for role in ("checked", "acctg_approved"):
            rfp = RFPService.advance_step(rfp, role=role, user=head)
        rfp.finance_notes = "Verify delivery before CV issuance."
        rfp.save(update_fields=["finance_notes", "updated_at"])
        rfp = RFPService.advance_step(rfp, role="fin_approved", user=head)
        assert rfp.status == "fin_approved"
        assert rfp.approved_by_fin == head

    def test_approve_after_reject_without_step_record(self, company, segment, supplier, alywin, accounts):
        """Even when the rejection happened before any step was recorded, the
        re-approval works and the RFP keeps moving (happy reject/revise path)."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        head = User.objects.create_user(username="head", password="x")

        lines = [
            {"side": "dr", "segment": segment, "account_code": "61100", "amount": "20000.00",
             "description": "Office supplies"},
            {"side": "cr", "segment": segment, "account_code": "20000", "amount": "20000.00",
             "description": "AP"},
        ]
        rfp = RFPService.create_rfp(
            ap_number="A0014", rfp_date=date(2026, 1, 19), payee=supplier, segment=segment,
            lines=lines, user=alywin,
        )
        rfp.status = "submitted"
        rfp.save(update_fields=["status", "updated_at"])
        rfp = RFPService.reject(rfp, user=head, note="Add supporting docs.")
        rfp = RFPService.revise(rfp, user=alywin, purpose=rfp.purpose, lines=lines)

        for role in ("checked", "acctg_approved"):
            rfp = RFPService.advance_step(rfp, role=role, user=head)
        rfp.finance_notes = "Notes attached."
        rfp.save(update_fields=["finance_notes", "updated_at"])
        rfp = RFPService.advance_step(rfp, role="fin_approved", user=head)
        assert rfp.status == "fin_approved"

    def test_audit_trail_survives_reject_revise_reapprove(self, company, segment, supplier, alywin, accounts):
        """The durable ActionLog keeps every lifecycle action even though the
        mutable checked_by/approved_by_* fields are reset on revision — so a
        re-approved RFP still shows its full history (ADR-008)."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        head = User.objects.create_user(username="head", password="x")

        lines = [
            {"side": "dr", "segment": segment, "account_code": "61100", "amount": "30000.00",
             "description": "Parts"},
            {"side": "cr", "segment": segment, "account_code": "20000", "amount": "30000.00",
             "description": "AP"},
        ]
        rfp = RFPService.create_rfp(
            ap_number="A0015", rfp_date=date(2026, 1, 20), payee=supplier, segment=segment,
            lines=lines, user=alywin,
        )
        actions = lambda: list(ActionLog.objects.filter(
            doc_type=ActionLog.DocType.RFP, doc_id=rfp.id
        ).order_by("id").values_list("action", flat=True))
        assert actions() == ["created"]

        rfp.status = "submitted"
        rfp.save(update_fields=["status", "updated_at"])
        rfp = RFPService.advance_step(rfp, role="checked", user=head)
        rfp = RFPService.reject(rfp, user=head, note="Reclassify.")
        assert actions() == ["created", "checked", "rejected"]

        rfp = RFPService.revise(rfp, user=alywin, purpose=rfp.purpose, lines=lines)
        for role in ("checked", "acctg_approved"):
            rfp = RFPService.advance_step(rfp, role=role, user=head)
        rfp.finance_notes = "Verify before CV."
        rfp.save(update_fields=["finance_notes", "updated_at"])
        rfp = RFPService.advance_step(rfp, role="fin_approved", user=head)

        assert actions() == [
            "created", "checked", "rejected", "revised",
            "checked", "acctg_approved", "fin_approved",
        ]


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

    def test_posting_uses_prefixed_je_number_even_when_number_is_taken(
        self, company, segment, supplier, alywin, accounts
    ):
        """Regression for the production 500: RFP/AR/manual JEs all allocated
        the bare 'YYYY-SEQ' namespace, so an RFP whose ap_number equalled an
        existing JE entry_no (manual or AR) blew the unique constraint on post.
        RFP-derived JEs now carry an 'RFP-' prefix and always post cleanly."""
        from django.contrib.auth import get_user_model

        head = get_user_model().objects.create_user(username="headRFP", password="x")
        rfp = RFPService.create_rfp(
            ap_number="2026-00005", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "50000.00"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "50000.00"},
            ],
            user=alywin,
        )
        for role in ("checked", "acctg_approved", "fin_approved"):
            rfp = RFPService.advance_step(rfp, role=role, user=head)
        batch = CONSOBatch.objects.create(batch_no="CONSO-2026-06", conso_date=date(2026, 1, 20))
        rfp.conso = batch
        rfp.save(update_fields=["conso", "updated_at"])

        # Simulate the pre-existing JE that owned the bare number (manual JE
        # or AR receipt) which previously blocked the RFP post with a 500.
        JournalEntry.objects.create(
            entry_no="2026-00005", company=company, segment=segment,
            transaction_date=date(2026, 1, 10), status=PostingStatus.DRAFT,
            description="Some earlier entry",
        )

        CONSOService.post_batch(batch, user=head)

        rfp.refresh_from_db()
        assert rfp.status == "posted"
        assert rfp.journal_entry.entry_no == "RFP-2026-00005"
        assert rfp.journal_entry.is_posted
        # The pre-existing bare-number entry is untouched.
        assert JournalEntry.objects.filter(entry_no="2026-00005").exists()

    def test_line_cost_center_survives_posting(self, company, segment, supplier, alywin, accounts):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        head = User.objects.create_user(username="headCC", password="x")
        rfp = RFPService.create_rfp(
            ap_number="A88831", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "5000.00",
                 "description": "Fuel purchase", "cost_center": "OS — offsite"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "5000.00",
                 "description": "AP", "cost_center": "GEN-FUEL"},
            ],
            user=alywin,
        )
        for role in ("checked", "acctg_approved", "fin_approved"):
            rfp = RFPService.advance_step(rfp, role=role, user=head)
        batch = CONSOBatch.objects.create(batch_no="CONSO-2026-CC", conso_date=date(2026, 1, 20))
        rfp.conso = batch
        rfp.save(update_fields=["conso", "updated_at"])
        CONSOService.post_batch(batch, user=head)

        rfp.refresh_from_db()
        je = rfp.journal_entry
        assert je is not None
        assert {l.reference for l in je.lines.all()} == {"OS — offsite", "GEN-FUEL"}

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

    def _square_rfp(self, segment, supplier, alywin, ap_number, amount="30000.00"):
        return RFPService.create_rfp(
            ap_number=ap_number, rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": amount},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": amount},
            ],
            user=alywin,
        )

    def test_auto_assign_off_by_default(self, company, segment, supplier, alywin, accounts):
        """Manual batching stays the default: approval does not touch a batch."""
        from django.contrib.auth import get_user_model

        head = get_user_model().objects.create_user(username="headA0", password="x")
        rfp = self._square_rfp(segment, supplier, alywin, "A777AA")
        rfp.status = "submitted"
        rfp.save(update_fields=["status", "updated_at"])
        rfp = RFPService.approve_head(rfp, user=head)
        assert rfp.status == "fin_approved"
        assert rfp.conso_id is None
        assert CONSOBatch.objects.count() == 0

    def test_auto_assign_batches_on_final_approval(self, company, segment, supplier, alywin, accounts):
        """CONSO_AUTO_ASSIGN on: the head's one-click approval drops the RFP
        into a numbered CONSO batch and updates its total (ADR-018, reversible)."""
        from django.conf import settings as dj_settings
        from django.contrib.auth import get_user_model
        from django.test import override_settings

        head = get_user_model().objects.create_user(username="headA1", password="x")
        rfp = self._square_rfp(segment, supplier, alywin, "A777AB", amount="40000.00")
        rfp.status = "submitted"
        rfp.save(update_fields=["status", "updated_at"])
        with override_settings(DOMAIN=dict(dj_settings.DOMAIN, CONSO_AUTO_ASSIGN=True)):
            rfp = RFPService.approve_head(rfp, user=head)
        assert rfp.status == "fin_approved"
        assert rfp.conso_id
        batch = CONSOBatch.objects.get(pk=rfp.conso_id)
        assert batch.batch_no.startswith("CONSO-")
        assert batch.rfps.count() == 1
        batch.refresh_from_db()
        assert batch.total_amount == rfp.amount

    def test_auto_assign_reuses_newest_open_batch(self, company, segment, supplier, alywin, accounts):
        """Multiple approvals share the current open batch and sum correctly."""
        from django.conf import settings as dj_settings
        from django.contrib.auth import get_user_model
        from django.test import override_settings

        head = get_user_model().objects.create_user(username="headA2", password="x")
        batch = CONSOBatch.objects.create(batch_no="CONSO-2026-77", conso_date=date(2026, 1, 20))
        rfp1 = self._square_rfp(segment, supplier, alywin, "A777AC", amount="20000.00")
        rfp2 = self._square_rfp(segment, supplier, alywin, "A777AD", amount="25000.00")
        for r in (rfp1, rfp2):
            r.status = "submitted"
            r.save(update_fields=["status", "updated_at"])
        with override_settings(DOMAIN=dict(dj_settings.DOMAIN, CONSO_AUTO_ASSIGN=True)):
            rfp1 = RFPService.approve_head(rfp1, user=head)
            rfp2 = RFPService.approve_head(rfp2, user=head)
        assert rfp1.conso_id == batch.id == rfp2.conso_id
        batch.refresh_from_db()
        assert batch.total_amount == Decimal("45000.00")
        assert batch.rfps.count() == 2

    def test_auto_assign_restores_manual_when_flag_flipped(self, company, segment, supplier, alywin, accounts):
        """Flipping CONSO_AUTO_ASSIGN off returns to manual batches: a later
        approval does not join the open batch and conso_add_rfp still works."""
        from django.conf import settings as dj_settings
        from django.contrib.auth import get_user_model
        from django.test import override_settings

        head = get_user_model().objects.create_user(username="headA3", password="x")
        batch = CONSOBatch.objects.create(batch_no="CONSO-2026-78", conso_date=date(2026, 1, 21))
        rfp = self._square_rfp(segment, supplier, alywin, "A777AE")
        rfp.status = "submitted"
        rfp.save(update_fields=["status", "updated_at"])
        with override_settings(DOMAIN=dict(dj_settings.DOMAIN, CONSO_AUTO_ASSIGN=False)):
            rfp = RFPService.approve_head(rfp, user=head)
        assert rfp.status == "fin_approved"
        assert rfp.conso_id is None
        rfp.conso = batch
        rfp.save(update_fields=["conso", "updated_at"])
        assert list(batch.rfps.all()) == [rfp]


class TestRPFFinanceNotesGate:
    def test_revised_rfp_needs_finance_notes_for_fin_approval(
        self, company, segment, supplier, alywin, accounts
    ):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        head = User.objects.create_user(username="head", password="x")

        rfp = RFPService.create_rfp(
            ap_number="A0030", rfp_date=date(2026, 1, 15), payee=supplier, segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "50000.00",
                 "description": "Fuel delivery"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "50000.00",
                 "description": "AP - Shandong Fuel Depot"},
            ],
            user=alywin,
        )
        rfp.status = "submitted"  # mirrors ui:rfp_submit
        rfp.save(update_fields=["status", "updated_at"])

        # Rejection → revise bumps revision_count.
        rfp = RFPService.reject(rfp, user=head, note="Split the fuel charge.")
        rfp = RFPService.revise(
            rfp, user=alywin, purpose=rfp.purpose,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": "50000.00",
                 "description": "Fuel delivery (revised)"},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": "50000.00",
                 "description": "AP - Shandong Fuel Depot"},
            ],
        )
        assert rfp.revision_count == 1
        assert rfp.status == "submitted"

        for role in ("checked", "acctg_approved"):
            rfp = RFPService.advance_step(rfp, role=role, user=head)

        # No finance notes yet → finance approval is blocked (ADR-038 §10d).
        with pytest.raises(ValidationError, match="finance approval"):
            RFPService.advance_step(rfp, role="fin_approved", user=head)
        assert rfp.status == "acctg_approved"

        # Adding notes unblocks the gate.
        rfp.finance_notes = "Verify stock delivery before CV issuance."
        rfp.save(update_fields=["finance_notes", "updated_at"])
        rfp = RFPService.advance_step(rfp, role="fin_approved", user=head)
        assert rfp.status == "fin_approved"
        assert rfp.approved_by_fin == head


class TestCVPayment:
    def test_wht_split_clears_ap(self, company, segment, supplier, accounts, alywin, segment_account_map):
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

    def test_no_wht_when_zero(self, company, segment, supplier, accounts, alywin, segment_account_map):
        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0002", cv_date=date(2026, 1, 26),
            payee=supplier, bank_account=accounts["10010"],
            gross_amount="5000.00", withheld_tax="0.00",
        )
        assert cv.net_amount == Decimal("5000.00")
        assert cv.journal_entry.lines.count() == 2

    def test_requires_posted_rfp(self, company, segment, accounts, alywin, segment_account_map):
        from apps.ap.models import Supplier, RFPLine

        payee = Supplier.objects.create(
            code="S002", name="TBA Depot", supplier_type="depot", default_segment=segment
        )
        rfp = RFPDocument.objects.create(
            ap_number="A0040", last_ap="A0039", rfp_date=date(2026, 1, 27),
            payee=payee, particulars="restock", segment=segment,
            amount=Decimal("8000.00"), status="fin_approved", created_by=alywin,
        )
        RFPLine.objects.create(rfp=rfp, line_no=1, side="dr", segment=segment,
                               account=accounts["61100"], amount=Decimal("8000.00"))
        RFPLine.objects.create(rfp=rfp, line_no=2, side="cr", segment=segment,
                               account=accounts["20000"], amount=Decimal("8000.00"))
        with pytest.raises(ValidationError):
            CVPaymentService.create_cv(
                cv_number="CV-2026-0100", cv_date=date(2026, 1, 28),
                payee=payee, bank_account=accounts["10010"],
                gross_amount="8000.00", rfp=rfp, user=alywin,
            )

    def test_clear_requires_approved_and_posts(self, company, segment, supplier, accounts, alywin, segment_account_map):
        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0003", cv_date=date(2026, 1, 27),
            payee=supplier, bank_account=accounts["10010"],
            gross_amount="10000.00", withheld_tax="200.00",
        )
        assert cv.status == "created"
        assert not cv.journal_entry.is_posted  # DRAFT at issuance
        with pytest.raises(ValidationError):
            CVPaymentService.clear(cv, user=alywin)
        CVPaymentService.approve(cv, user=alywin)
        CVPaymentService.clear(cv, user=alywin)
        cv.refresh_from_db()
        assert cv.status == "cleared"
        assert cv.journal_entry.is_posted
        # The clear act also stamps the cash-side CheckDisbursement.cleared_at so
        # the CV's DATE CLEARED fields (print/PDF/detail) populate.
        from apps.cash.models import CheckDisbursement

        disb = CheckDisbursement.objects.get(cv=cv)
        assert disb.status == "cleared"
        assert disb.cleared_at is not None

    def test_reject_then_revise_restarts_chain(self, company, segment, supplier, accounts, alywin, segment_account_map):
        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0004", cv_date=date(2026, 1, 27),
            payee=supplier, bank_account=accounts["10010"],
            gross_amount="10000.00", check_no="CHK-1", user=alywin,
        )
        assert not cv.journal_entry.is_posted
        # rejection needs a note and an awaiting status
        with pytest.raises(ValidationError):
            CVPaymentService.reject(cv, user=alywin, note="")
        cv = CVPaymentService.reject(cv, user=alywin, note="Wrong check number")
        assert cv.status == "rejected"
        assert cv.journal_entry_id is None  # the DRAFT was dropped, not posted
        # only the issuer can revise (alywin is the issuer here)
        cv = CVPaymentService.revise(
            cv, user=alywin, bank_account=accounts["10010"],
            gross_amount="10000.00", withheld_tax="100.00", check_no="CHK-2",
        )
        assert cv.status == "created"
        assert cv.revision_count == 1
        assert cv.net_amount == Decimal("9900.00")
        assert cv.approved_by_id is None
        assert cv.journal_entry_id and not cv.journal_entry.is_posted
        # cleared CVs are final
        cv = CVPaymentService.approve(cv, user=alywin)
        CVPaymentService.clear(cv, user=alywin)
        with pytest.raises(PostingError):
            CVPaymentService.reject(cv, user=alywin, note="late")

    def test_audit_trail_survives_cv_reject_revise(self, company, segment, supplier, accounts, alywin, segment_account_map):
        """CV lifecycle actions are recorded append-only; the reject pass and
        its note survive revision and the second created pass (ADR-008)."""
        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0005", cv_date=date(2026, 1, 28),
            payee=supplier, bank_account=accounts["10010"],
            gross_amount="12000.00", check_no="CHK-9", user=alywin,
        )
        actions = lambda: list(ActionLog.objects.filter(
            doc_type=ActionLog.DocType.CV, doc_id=cv.id
        ).order_by("id").values_list("action", flat=True))
        assert actions() == ["created"]

        cv = CVPaymentService.reject(cv, user=alywin, note="Wrong check number")
        assert actions() == ["created", "rejected"]
        rejection = ActionLog.objects.filter(
            doc_type=ActionLog.DocType.CV, doc_id=cv.id, action="rejected"
        ).first()
        assert rejection.note == "Wrong check number"
        assert rejection.actor == alywin

        cv = CVPaymentService.revise(
            cv, user=alywin, bank_account=accounts["10010"],
            gross_amount="12000.00", withheld_tax="0.00", check_no="CHK-10",
        )
        assert actions() == ["created", "rejected", "revised"]
        cv = CVPaymentService.approve(cv, user=alywin)
        assert actions()[-1] == "approved"
        CVPaymentService.clear(cv, user=alywin)
        assert actions()[-1] == "cleared"


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


class TestRetryOnLock:
    """The SQLite dev DB can raise 'database is locked' mid-request
    (SQLITE_BUSY_SNAPSHOT bypasses busy_timeout); retry_on_lock must retry
    only that error, in a fresh transaction."""

    def test_retries_locked_then_succeeds(self):
        from apps.ap.services import retry_on_lock
        from django.db import OperationalError

        calls = {"n": 0}

        @retry_on_lock(max_attempts=5, initial_delay=0.001)
        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise OperationalError("database is locked")
            return "ok"

        assert flaky() == "ok"
        assert calls["n"] == 3

    def test_non_lock_error_not_retried(self):
        from apps.ap.services import retry_on_lock
        from django.db import OperationalError

        calls = {"n": 0}

        @retry_on_lock(max_attempts=5, initial_delay=0.001)
        def boom():
            calls["n"] += 1
            raise OperationalError("disk I/O error")

        with pytest.raises(OperationalError):
            boom()
        assert calls["n"] == 1

    def test_exhausts_attempts(self):
        from apps.ap.services import retry_on_lock
        from django.db import OperationalError

        calls = {"n": 0}

        @retry_on_lock(max_attempts=2, initial_delay=0.001)
        def stuck():
            calls["n"] += 1
            raise OperationalError("database is locked")

        with pytest.raises(OperationalError):
            stuck()
        assert calls["n"] == 2


class TestPurchaseOrder:
    """Master Purchase Order lifecycle (ADR-0XX): auto-numbered, RFP-mirror
    approval chain, manual head close, and derived billing balances."""

    @staticmethod
    def _make(*, supplier, alywin, segment, lines=None, po_number="P0001"):
        from apps.ap.services import PurchaseOrderService

        return PurchaseOrderService.create_po(
            po_number=po_number,
            po_date=date(2026, 1, 5),
            supplier=supplier,
            segment=segment,
            particulars="Engine oil for diesel fleet",
            lines=lines
            or [
                {"qty": "2", "unit": "DRUM", "description": "ENGINE OIL 15W40", "unit_price": "25000.00"},
            ],
            payment_terms="30 days",
            user=alywin,
        )

    @pytest.fixture
    def head(self, db):
        from django.contrib.auth import get_user_model
        from apps.foundation.models import UserProfile

        u = get_user_model().objects.create_user(username="pohead", password="x")
        UserProfile.objects.create(user=u, approval_role="head")
        return u

    def _approved(self, po, head):
        po.status = "submitted"
        po.save(update_fields=["status"])
        from apps.ap.services import PurchaseOrderService

        PurchaseOrderService.approve_head(po, user=head)
        po.refresh_from_db()
        return po

    def test_create_po_totals_and_lines(self, company, segment, supplier, alywin):
        po = self._make(
            supplier=supplier, alywin=alywin, segment=segment,
            lines=[
                {"qty": "2", "unit": "DRUM", "description": "ENGINE OIL 15W40", "unit_price": "25000.00"},
                {"qty": "3", "unit": "PC", "description": "OIL FILTER", "unit_price": "1000.00"},
            ],
        )
        assert po.po_number == "P0001"
        assert po.subtotal == Decimal("53000.00")
        assert po.amount == Decimal("53000.00")  # no discount/vat/other yet
        assert po.available_amount == Decimal("53000.00")
        assert po.status == "prepared"
        assert [l.amount for l in po.lines.all()] == [Decimal("50000.00"), Decimal("3000.00")]

    def test_create_po_requires_valid_lines(self, company, segment, supplier, alywin):
        with pytest.raises(ValidationError, match="quantity and unit price"):
            self._make(supplier=supplier, alywin=alywin, segment=segment,
                       lines=[{"qty": "0", "unit": "PC", "description": "Bad", "unit_price": "100.00"}])
        with pytest.raises(ValidationError, match="description"):
            self._make(supplier=supplier, alywin=alywin, segment=segment,
                       lines=[{"qty": "1", "unit": "PC", "description": "", "unit_price": "100.00"}])
        with pytest.raises(ValidationError, match="greater than zero"):
            self._make(supplier=supplier, alywin=alywin, segment=segment,
                       lines=[{"qty": "-1", "unit": "PC", "description": "Bad", "unit_price": "100.00"}])

    def test_create_po_captures_optional_line_account(self, company, segment, supplier, alywin, accounts):
        po = self._make(
            supplier=supplier, alywin=alywin, segment=segment,
            lines=[
                {"qty": "2", "unit": "DRUM", "description": "ENGINE OIL 15W40", "unit_price": "25000.00", "account": "61100"},
                {"qty": "1", "unit": "PC", "description": "OIL FILTER", "unit_price": "1000.00"},
            ],
        )
        po_lines = list(po.lines.all())
        assert po_lines[0].account == accounts["61100"]
        assert po_lines[0].amount == Decimal("50000.00")
        assert po_lines[1].account is None

    def test_create_po_unknown_line_account_rejected(self, company, segment, supplier, alywin, accounts):
        with pytest.raises(ValidationError, match="not found"):
            self._make(
                supplier=supplier, alywin=alywin, segment=segment,
                lines=[{"qty": "1", "unit": "PC", "description": "Lubricant", "unit_price": "100.00", "account": "99999"}],
            )

    def test_revise_po_replaces_lines_with_accounts(self, company, segment, supplier, alywin, accounts):
        from apps.ap.services import PurchaseOrderService

        po = self._make(supplier=supplier, alywin=alywin, segment=segment)
        po.status = "submitted"
        po.save(update_fields=["status"])
        PurchaseOrderService.reject(po, user=alywin, note="Wrong quantity.")
        revised = PurchaseOrderService.revise(
            po,
            user=alywin,
            lines=[
                {"qty": "2", "unit": "DRUM", "description": "ENGINE OIL 15W40", "unit_price": "25000.00", "account": "61100"},
                {"qty": "1", "unit": "L", "description": "COOLANT", "unit_price": "800.00", "account": "20000"},
            ],
        )
        revised_lines = list(revised.lines.all())
        assert revised_lines[0].account == accounts["61100"]
        assert revised_lines[1].account == accounts["20000"]
        assert revised.status == "submitted"
        assert revised.subtotal == Decimal("50800.00")

    def test_po_head_approval_rolls_straight_to_approved(self, company, segment, supplier, alywin, head):
        po = self._make(supplier=supplier, alywin=alywin, segment=segment)
        out = self._approved(po, head)
        assert out.status == "approved"
        assert out.approved_by_fin == head
        assert out.approved_by_cnr is None
        assert out.available_amount == out.amount

    def test_po_close_blocks_and_head_only(self, company, segment, supplier, alywin, head):
        from apps.ap.services import PurchaseOrderService

        po = self._approved(self._make(supplier=supplier, alywin=alywin, segment=segment), head)
        # only the head can close
        from django.contrib.auth import get_user_model

        staff = get_user_model().objects.create_user(username="postaff", password="x")
        with pytest.raises(ValidationError, match="Head"):
            PurchaseOrderService.close_po(po, user=staff)
        PurchaseOrderService.close_po(po, user=head)
        po.refresh_from_db()
        assert po.status == "closed"


class TestRFPPurchaseOrderLink:
    """An RFP references a master PO from the same vendor; the PO's available
    balance falls as the RFP is approved (reserved) and posted (billed)."""

    @pytest.fixture
    def po(self, db, company, segment, supplier, alywin):
        from apps.ap.services import PurchaseOrderService

        return PurchaseOrderService.create_po(
            po_number="P0001",
            po_date=date(2026, 1, 5),
            supplier=supplier,
            segment=segment,
            particulars="Diesel supply",
            lines=[{"qty": "1", "unit": "UNIT", "description": "DIESEL", "unit_price": "100000.00"}],
            user=alywin,
        )

    @pytest.fixture
    def head(self, db):
        from django.contrib.auth import get_user_model
        from apps.foundation.models import UserProfile

        u = get_user_model().objects.create_user(username="rfppohead", password="x")
        UserProfile.objects.create(user=u, approval_role="head")
        return u

    def _approved_po(self, po, head):
        po.status = "submitted"
        po.save(update_fields=["status"])
        from apps.ap.services import PurchaseOrderService

        PurchaseOrderService.approve_head(po, user=head)
        po.refresh_from_db()
        return po

    def _rfp(self, *, supplier, segment, amount, alywin, po, tag="1"):
        return RFPService.create_rfp(
            ap_number=f"A{po.id}r{tag}",
            rfp_date=date(2026, 1, 15),
            payee=supplier,
            segment=segment,
            lines=[
                {"side": "dr", "segment": segment, "account_code": "61100", "amount": amount},
                {"side": "cr", "segment": segment, "account_code": "20000", "amount": amount},
            ],
            user=alywin,
            po=po,
        )

    def test_rfp_requires_an_approved_po(self, company, segment, supplier, alywin, po):
        with pytest.raises(ValidationError, match="must be approved"):
            self._rfp(supplier=supplier, segment=segment, amount="20000.00", alywin=alywin, po=po)

    def test_rfp_po_must_match_the_vendor(self, company, segment, supplier, alywin, po, head):
        approved = self._approved_po(po, head)
        other = Supplier.objects.create(code="S002", name="Other Vendor", default_segment=segment)
        with pytest.raises(ValidationError, match="same supplier"):
            self._rfp(supplier=other, segment=segment, amount="20000.00", alywin=alywin, po=approved)

    def test_approved_po_links_and_reserves_on_approval(self, company, segment, supplier, alywin, po,
                                                        head, accounts):
        approved = self._approved_po(po, head)
        rfp = self._rfp(supplier=supplier, segment=segment, amount="80000.00", alywin=alywin, po=approved)
        assert rfp.po_id == approved.id
        assert approved.available_amount == Decimal("100000.00")  # not reserved until approved
        for role in ("checked", "acctg_approved", "fin_approved"):
            rfp = RFPService.advance_step(rfp, role=role, user=head)
        rfp.refresh_from_db()
        approved.refresh_from_db()
        assert rfp.status == "fin_approved"
        assert approved.reserved_amount == Decimal("80000.00")
        assert approved.available_amount == Decimal("20000.00")

    def test_created_amount_cannot_exceed_po_balance(self, company, segment, supplier, alywin, po, head):
        approved = self._approved_po(po, head)
        with pytest.raises(ValidationError, match="exceeds the available balance"):
            self._rfp(supplier=supplier, segment=segment, amount="150000.00", alywin=alywin, po=approved)

    def test_final_approval_guard_blocks_over_commit(self, company, segment, supplier, alywin, po, head,
                                                     accounts):
        from apps.ap.services import PurchaseOrderService

        approved = self._approved_po(po, head)
        rfp1 = self._rfp(supplier=supplier, segment=segment, amount="80000.00", alywin=alywin, po=approved)
        rfp2 = self._rfp(supplier=supplier, segment=segment, amount="30000.00", alywin=alywin, po=approved,
                         tag="2")
        for role in ("checked", "acctg_approved", "fin_approved"):
            rfp1 = RFPService.advance_step(rfp1, role=role, user=head)
        # rfp2 fits at creation (0 reserved) but not once rfp1 is approved:
        # the guard re-derives the drawn balance at rfp2's final (fin_approved)
        # step.
        rfp2 = RFPService.advance_step(rfp2, role="checked", user=head)
        rfp2 = RFPService.advance_step(rfp2, role="acctg_approved", user=head)
        with pytest.raises(ValidationError, match="no longer holds enough balance"):
            RFPService.advance_step(rfp2, role="fin_approved", user=head)

    def test_posted_rfp_counts_as_billed(self, company, segment, supplier, alywin, po, head, accounts):
        approved = self._approved_po(po, head)
        rfp = self._rfp(supplier=supplier, segment=segment, amount="60000.00", alywin=alywin, po=approved)
        for role in ("checked", "acctg_approved", "fin_approved"):
            rfp = RFPService.advance_step(rfp, role=role, user=head)
        batch = CONSOBatch.objects.create(batch_no="CONSO-2026-PO1", conso_date=date(2026, 1, 20))
        rfp.conso = batch
        rfp.save(update_fields=["conso", "updated_at"])
        CONSOService.post_batch(batch, user=head)
        rfp.refresh_from_db()
        approved.refresh_from_db()
        assert rfp.status == "posted"
        assert approved.billed_amount == Decimal("60000.00")
        assert approved.available_amount == Decimal("40000.00")


class TestImportSuppliers:
    def test_creates_and_is_idempotent(self, tmp_path, company, segment):
        from apps.ap.models import SupplierType
        from apps.foundation.models import Segment as SegmentModel

        SegmentModel.objects.create(code="DMIE", name="DMIE", company=company)

        path = tmp_path / "suppliers.csv"
        import csv
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["CODE", "NAME", "TYPE", "DEFAULT SEGMENT", "TIN"])
            writer.writerow(["V001", "Depot One", "depot", "DHPP", "111"])
            writer.writerow(["V002", "Equip Two", "equipment", "DMIE", "222"])
        call_command("import_suppliers", file=str(path), stdout=StringIO())

        s1 = Supplier.objects.get(code="V001")
        assert s1.default_segment.code == "DHPP"
        assert s1.supplier_type == SupplierType.DEPOT
        assert s1.tin == "111"
        assert Supplier.objects.get(code="V002").default_segment.code == "DMIE"

        call_command("import_suppliers", file=str(path), stdout=StringIO())
        assert Supplier.objects.filter(code="V001").count() == 1
