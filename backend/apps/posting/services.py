"""PostingService: validate, balance-check, post, and publish.

Invariants enforced here are the heart of the system (ADR-002/004/005):

1. Drafts can be edited; POSTED entries are frozen — a posted entry cannot be
   modified or deleted, only reversed with a matching reversing entry.
2. Debits == credits is REQUIRED. No force-balancing: UnbalancedEntryError
   carries the difference for human reconciliation.
3. Money is always Decimal(2dp) via apps.core.money.money().
4. Posting is atomic: the entry + lines + GL projection commit or fail
   together, inside one transaction.
5. Approval gate: entries above the JE_APPROVAL_THRESHOLD need a second
   approval before POSTED (ADR-033 workflow).
"""

from decimal import Decimal

from django.db import transaction

from apps.core.exceptions import PostingError, UnbalancedEntryError
from apps.core.money import approve_threshold, money

from .models import (
    GeneralLedger,
    JournalEntry,
    JournalEntryLine,
    PostingRule,
    PostingRuleLine,
    PostingStatus,
)


class PostingService:
    """Stateless engine; all state lives on the models or in the caller."""

    # ------------------------------------------------------------------ crea

    @classmethod
    def create_rule_entry(
        cls,
        *,
        rule_code: str,
        company,
        segment,
        transaction_date,
        description,
        amount: Decimal,
        source_doc_type: str = "",
        source_doc_no: str = "",
        entry_no: str = "",
        fiscal_period=None,
        user=None,
    ) -> JournalEntry:
        """Build a draft JE from a PostingRule + amount (ADR-004, ADR-018).

        Line amount resolution, in order of precedence:
        1. fixed_amount (absolute value, e.g. the 20,000 advances leg);
        2. share * total (distribution legs, e.g. payroll by event);
        3. use_balance — takes the remainder so the entry balances by
           construction. At most one balance line per side: the Dr balance
           line makes debits sum to `total`: the Cr balance line makes
           credits sum to `total` minus its fixed/share legs (the canonical
           RFP formula Dr TOTAL | Cr advances | Cr AP remainder).
        """
        try:
            rule = PostingRule.objects.get(code=rule_code, is_active=True)
        except PostingRule.DoesNotExist as exc:
            raise PostingError(f"Posting rule '{rule_code}' not found.") from exc

        total = money(amount)
        rule_lines = list(rule.lines.order_by("line_no"))

        with transaction.atomic():
            je = JournalEntry(
                entry_no=entry_no or "(unassigned)",
                company=company,
                segment=segment,
                transaction_date=transaction_date,
                description=description,
                source_doc_type=source_doc_type,
                source_doc_no=source_doc_no,
                fiscal_period=fiscal_period,
                created_by=user,
            )
            je.save()

            # Two passes: fixed/share legs first so balance legs can absorb
            # the remainder per side. Precedence: fixed > balance > share.
            per_side = {"debit": Decimal("0.00"), "credit": Decimal("0.00")}
            amounts = {}
            for i, rl in enumerate(rule_lines, start=1):
                if rl.fixed_amount > 0:
                    amounts[i] = money(rl.fixed_amount)
                elif rl.use_balance:
                    continue  # balance leg; resolved in pass 2
                elif rl.share > 0:
                    amounts[i] = money(total * rl.share)
                else:
                    raise PostingError(f"Rule line {rl.line_no} on {rule.code} has no amount source.")
                per_side[rl.side] += amounts[i]
            for i, rl in enumerate(rule_lines, start=1):
                if i in amounts:
                    continue
                if not rl.use_balance:
                    continue
                amounts[i] = money(total - per_side[rl.side])
                if amounts[i] < 0:
                    raise PostingError(
                        f"Rule line {rl.line_no} on {rule.code} went negative "
                        f"({amounts[i]}); fixed/share legs exceed the amount."
                    )

            for i, rl in enumerate(rule_lines, start=1):
                kwargs = {rl.side: amounts[i]}
                JournalEntryLine.objects.create(
                    entry=je,
                    line_no=i,
                    account=_resolve_account(rl.account_code),
                    description=rl.description or description,
                    **kwargs,
                )
            je.recalc_totals()
        return je

    # ------------------------------------------------------------------ pos

    @classmethod
    def post(cls, entry: JournalEntry, *, approver=None, user=None) -> JournalEntry:
        """Validate + post an entry atomically (immutability gate included)."""
        if entry.is_posted:
            raise PostingError(f"Entry {entry.entry_no} is already posted.")

        # Rule 2: no force-balance.
        debit_total = sum(money(l.debit) for l in entry.lines.all())
        credit_total = sum(money(l.credit) for l in entry.lines.all())
        if debit_total != credit_total:
            diff = debit_total - credit_total
            raise UnbalancedEntryError(
                f"Entry {entry.entry_no} is out of balance by {money(diff)} "
                f"(Dr {debit_total} vs Cr {credit_total}). No auto-adjust is performed."
            )

        # Rule 5: approval gate (ADR-033).
        threshold = approve_threshold()
        if debit_total > threshold and entry.status != PostingStatus.APPROVED:
            raise PostingError(
                f"Entry {entry.entry_no} exceeds the approval threshold "
                f"({threshold}); it must be APPROVED before posting."
            )

        with transaction.atomic():
            entry.status = PostingStatus.POSTED
            entry.total_debit = debit_total
            entry.total_credit = credit_total
            entry.updated_by = user
            entry.save(update_fields=["status", "total_debit", "total_credit", "updated_by", "updated_at"])

            # Rule 4: build GL projection inside the same transaction.
            _lines = list(entry.lines.all().select_related("account"))
            gl_rows = [
                GeneralLedger(
                    entry=entry,
                    line=line,
                    account=line.account,
                    company=entry.company,
                    segment=entry.segment,
                    fiscal_period=entry.fiscal_period,
                    transaction_date=entry.transaction_date,
                    debit=line.debit,
                    credit=line.credit,
                )
                for line in _lines
            ]
            GeneralLedger.objects.bulk_create(gl_rows)

        return entry

    # ------------------------------------------------------------------ rev

    @classmethod
    def reverse(cls, entry: JournalEntry, *, reason: str, user=None) -> JournalEntry:
        """Create the reversing entry: exact mirror, ALLOCATED to the next
        cycle, linked by reversal_token (ADR-002/004 correction semantics)."""
        if not entry.is_posted:
            raise PostingError("Only posted entries can be reversed.")

        from apps.foundation.calendar import cycle_range_for
        from datetime import timedelta

        start, end = cycle_range_for(entry.transaction_date, company=entry.company)
        reversal_date = end + timedelta(days=1)

        with transaction.atomic():
            token = f"REV:{entry.entry_no}:{entry.id}"
            rev = JournalEntry.objects.create(
                entry_no=f"REV-{entry.entry_no}",
                company=entry.company,
                segment=entry.segment,
                fiscal_period=entry.fiscal_period,
                transaction_date=reversal_date,
                status=PostingStatus.POSTED,
                description=f"Reversal of {entry.entry_no}: {reason}",
                source_doc_type=entry.source_doc_type,
                source_doc_no=entry.source_doc_no,
                reversal_token=token,
                created_by=user,
            )
            for line in entry.lines.all():
                JournalEntryLine.objects.create(
                    entry=rev,
                    line_no=line.line_no,
                    account=line.account,
                    description=f"REV of {entry.entry_no}: {line.description}",
                    debit=line.credit,
                    credit=line.debit,
                )
            rev.recalc_totals()
            entry.reversal_token = token
            entry.status = PostingStatus.REVERSED
            entry.updated_by = user
            entry.save(update_fields=["reversal_token", "status", "updated_by", "updated_at"])

            # GL projection for the reversing entry:
            _lines = list(rev.lines.all().select_related("account"))
            GeneralLedger.objects.bulk_create([
                GeneralLedger(
                    entry=rev, line=line, account=line.account, company=rev.company,
                    segment=rev.segment, fiscal_period=rev.fiscal_period,
                    transaction_date=rev.transaction_date, debit=line.debit, credit=line.credit,
                )
                for line in _lines
            ])
        return rev


def _resolve_account(code: str):
    from apps.foundation.models import Account

    try:
        return Account.objects.get(code=code, is_postable=True)
    except Account.DoesNotExist as exc:
        raise PostingError(f"Account {code} missing or not postable.") from exc