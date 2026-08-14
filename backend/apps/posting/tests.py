"""Core posting engine invariants (ADR-002/004/005).

- append-only journal (no delete, no edit after POSTED)
- no force-balance: unbalanced entries raise UnbalancedEntryError
- rule-driven creation balances (ADR-018 RFP canonical)
- GL projection is written atomically on post
- approval threshold gate (ADR-033)
- reversal creates exact mirror and links both entries
"""

from datetime import date

import pytest
from django.db.models import Sum

from apps.core.exceptions import UnbalancedEntryError
from apps.core.money import money
from apps.foundation.models import Account
from apps.posting.models import GeneralLedger, JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService


def _draft(company, segment, fiscal_period=None, date_=date(2026, 1, 15), status=PostingStatus.DRAFT):
    return JournalEntry.objects.create(
        entry_no=f"JE-{JournalEntry.objects.count() + 1:04d}",
        company=company,
        segment=segment,
        fiscal_period=fiscal_period,
        transaction_date=date_,
        status=status,
        description="test",
    )


class TestRuleDrivenCreation:
    def test_rfp_rule_balances(self, company, segment, rfp_rule):
        """ADR-018 canonical: Dr TOTAL | Cr advances 20k | Cr AP balance."""
        je = PostingService.create_rule_entry(
            rule_code="RFP_DISBURSEMENT",
            company=company,
            segment=segment,
            transaction_date=date(2026, 1, 15),
            description="RFP 2026-0001",
            amount="85500.00",
        )
        assert je.is_balanced
        lines = {l.line_no: l for l in je.lines.all()}
        assert lines[1].debit == money("85500.00")
        assert lines[2].credit == money("20000.00")
        assert lines[3].credit == money("65500.00")
        assert je.total_debit == je.total_credit == money("85500.00")

    def test_missing_rule_raises(self, company, segment):
        with pytest.raises(Exception):
            PostingService.create_rule_entry(
                rule_code="NOPE", company=company, segment=segment,
                transaction_date=date(2026, 1, 15), description="x", amount="1",
            )


class TestPostingEngine:
    def test_post_creates_gl_projection(self, company, segment, fiscal_period, accounts):
        je = _draft(company, segment, fiscal_period)
        JournalEntryLine.objects.create(entry=je, line_no=1, account=accounts["10010"], debit="100.00")
        JournalEntryLine.objects.create(entry=je, line_no=2, account=accounts["41010"], credit="100.00")
        je.recalc_totals()

        PostingService.post(je)

        je.refresh_from_db()
        assert je.status == PostingStatus.POSTED
        assert GeneralLedger.objects.filter(entry=je).count() == 2
        gl = GeneralLedger.objects.get(entry=je, line__line_no=1)
        assert gl.account.code == "10010"
        assert gl.debit == money("100.00")
        assert gl.company_id == company.id

    def test_unbalanced_entry_never_auto_adjusts(self, company, segment, accounts):
        """ADR-002: surface the difference, never fix it silently."""
        je = _draft(company, segment)
        JournalEntryLine.objects.create(entry=je, line_no=1, account=accounts["10010"], debit="100.00")
        JournalEntryLine.objects.create(entry=je, line_no=2, account=accounts["41010"], credit="99.99")
        je.recalc_totals()

        with pytest.raises(UnbalancedEntryError) as exc:
            PostingService.post(je)
        assert "0.01" in str(exc.value)
        je.refresh_from_db()
        assert je.status == PostingStatus.DRAFT  # not posted

    def test_approval_threshold_requires_approval(self, company, segment, fiscal_period, accounts):
        """ADR-033: > threshold must be APPROVED before posting."""
        je = _draft(company, segment, fiscal_period)
        JournalEntryLine.objects.create(entry=je, line_no=1, account=accounts["10010"], debit="500000.00")
        JournalEntryLine.objects.create(entry=je, line_no=2, account=accounts["41010"], credit="500000.00")
        je.recalc_totals()

        with pytest.raises(Exception, match="approval threshold"):
            PostingService.post(je)

        je.status = PostingStatus.APPROVED
        je.save(update_fields=["status", "updated_at"])
        PostingService.post(je)
        je.refresh_from_db()
        assert je.status == PostingStatus.POSTED

    def test_posted_entry_is_immutable(self, company, segment, fiscal_period, accounts):
        """ADR-004: no deletes on posted entries."""
        je = _draft(company, segment, fiscal_period)
        JournalEntryLine.objects.create(entry=je, line_no=1, account=accounts["10010"], debit="50.00")
        JournalEntryLine.objects.create(entry=je, line_no=2, account=accounts["41010"], credit="50.00")
        je.recalc_totals()
        PostingService.post(je)

        with pytest.raises(Exception):
            je.delete()
        with pytest.raises(Exception):
            je.lines.first().delete()

    def test_reverse_creates_mirror_and_links(self, company, segment, fiscal_period, accounts):
        je = _draft(company, segment, fiscal_period)
        JournalEntryLine.objects.create(entry=je, line_no=1, account=accounts["10010"], debit="250.00")
        JournalEntryLine.objects.create(entry=je, line_no=2, account=accounts["41010"], credit="250.00")
        je.recalc_totals()
        PostingService.post(je)

        rev = PostingService.reverse(je, reason="wrong account")

        rev.refresh_from_db()
        assert rev.status == PostingStatus.POSTED
        assert rev.reversal_token == je.reversal_token
        assert rev.transaction_date == date(2026, 1, 20)  # next cycle start
        rev_lines = {l.line_no: (l.debit, l.credit) for l in rev.lines.all()}
        assert rev_lines[1] == (money("0.00"), money("250.00"))
        assert rev_lines[2] == (money("250.00"), money("0.00"))
        # GL has mirror rows for the reversing entry too.
        assert GeneralLedger.objects.filter(entry=rev).count() == 2


class TestLedgerDerivation:
    def test_account_balance_derived_from_gl(self, company, segment, fiscal_period, accounts):
        for amt in ("100.00", "50.00"):
            je = _draft(company, segment, fiscal_period)
            JournalEntryLine.objects.create(entry=je, line_no=1, account=accounts["10010"], debit=amt)
            JournalEntryLine.objects.create(entry=je, line_no=2, account=accounts["41010"], credit=amt)
            je.recalc_totals()
            PostingService.post(je)

        total = GeneralLedger.objects.filter(account=accounts["10010"]).aggregate(s=Sum("debit"))["s"]
        assert total == money("150.00")