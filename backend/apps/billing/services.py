"""Billing services: prepare, approve and journalize billing transactions.

The posted Journal Entry is built EXACTLY from the Account Distribution grid
as entered (mirrors the RFP/CONSO posting): Dr total must equal Cr total and
the entry is never force-balanced (ADR-002).

RFP tracing (requirements 3 & 4):
  * the JE header's Note/Reference (``ref_number``) captures the originating
    RFP number, and the RFP number is embedded in the JE description;
  * a credit line on an "unbilled" receivable account (15550 / 15560) gets a
    per-line reference of "RFP <number> — billed <amount>" so it traces back
    to the RFP and the amount being billed.
"""

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.ap.services import retry_on_lock
from apps.core.approvals import require_approval_role
from apps.core.exceptions import PostingError, ValidationError
from apps.core.money import money
from apps.foundation.models import Account, FiscalPeriod
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService

from .models import (
    UNBILLED_CREDIT_ACCOUNTS,
    BillingDocument,
    BillingLine,
    BillingStatus,
    BillingType,
)


def _resolve_account(line: dict) -> Account:
    """Resolve a line's COA account from an Account object or a code."""
    account = line.get("account")
    if account is not None:
        return account
    code = line.get("account_code")
    if not code:
        raise ValidationError("Each billing line needs a COA account.")
    account = Account.objects.filter(code=code).first()
    if account is None:
        raise ValidationError(f"COA account {code} not found.")
    return account


class BillingService:
    """Creates and advances billing transactions through their lifecycle."""

    # ---------------------------------------------------------------- create

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def create_billing(
        cls,
        *,
        billing_no: str,
        billing_date: date,
        billing_type: str,
        company,
        segment,
        party_name: str,
        lines: list[dict],
        customer=None,
        supplier=None,
        rfp=None,
        reference: str = "",
        particulars: str = "",
        user=None,
    ) -> BillingDocument:
        """Create a billing whose lines carry explicit Dr/Cr sides.

        Each line is ``{side, segment, account|account_code, amount,
        description, cost_center}``. The billing amount is the total of the
        debit lines; debits must equal credits so the posted JE balances.
        """
        if billing_type not in BillingType.values:
            raise ValidationError(f"Unknown billing type '{billing_type}'.")

        dr_total = Decimal("0.00")
        cr_total = Decimal("0.00")
        for line in lines:
            amt = money(line["amount"])
            if amt <= 0:
                raise ValidationError("Each billing line must have an amount greater than zero.")
            side = str(line.get("side") or "dr").lower()
            if side not in ("dr", "cr"):
                raise ValidationError(f"Line side must be Dr or Cr, got '{side}'.")
            if side == "dr":
                dr_total += amt
            else:
                cr_total += amt
        if dr_total <= 0:
            raise ValidationError("A billing needs at least one debit (Dr) line.")
        if dr_total != cr_total:
            raise ValidationError(
                f"Account distribution does not balance: Dr {dr_total} vs Cr {cr_total} "
                "— the posted entry must balance."
            )

        if not particulars:
            particulars = next(
                (str(line.get("description") or "").strip() for line in lines
                 if str(line.get("description") or "").strip()),
                "",
            )

        billing = BillingDocument.objects.create(
            billing_no=billing_no,
            billing_type=billing_type,
            billing_date=billing_date,
            company=company,
            segment=segment,
            party_name=(party_name or "").strip(),
            customer=customer,
            supplier=supplier,
            rfp=rfp,
            reference=(reference or "").strip(),
            particulars=particulars[:500],
            status=BillingStatus.DRAFT,
            created_by=user,
        )
        cls._write_lines(billing, lines)
        cls._log(billing, "created", actor=user)
        return billing

    @staticmethod
    def _write_lines(billing: BillingDocument, lines: list[dict]) -> None:
        rows = []
        for i, line in enumerate(lines, start=1):
            amt = money(line["amount"])
            side = str(line.get("side") or "dr").lower()
            rows.append(
                BillingLine(
                    billing=billing,
                    line_no=i,
                    side=side,
                    segment=line["segment"],
                    account=_resolve_account(line),
                    cost_center=(str(line.get("cost_center") or ""))[:64],
                    description=(str(line.get("description") or ""))[:500],
                    debit=amt if side == "dr" else Decimal("0.00"),
                    credit=amt if side == "cr" else Decimal("0.00"),
                )
            )
        BillingLine.objects.bulk_create(rows)
        billing.recalc_totals()

    # ------------------------------------------------------------- lifecycle

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def submit(cls, billing: BillingDocument, *, user) -> BillingDocument:
        """draft -> submitted (the preparer sends it for head approval)."""
        if billing.status != BillingStatus.DRAFT:
            raise ValidationError(
                f"Billing {billing.billing_no} can only be submitted from draft "
                f"(status '{billing.status}')."
            )
        if not billing.lines.exists():
            raise ValidationError("The billing has no account distribution lines.")
        billing.status = BillingStatus.SUBMITTED
        billing.rejected_by = None
        billing.rejected_at = None
        billing.rejection_note = ""
        billing.save(update_fields=["status", "rejected_by", "rejected_at", "rejection_note", "updated_at"])
        cls._log(billing, "submitted", actor=user)
        return billing

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def approve(cls, billing: BillingDocument, *, user) -> BillingDocument:
        """submitted -> approved (Accounting & Finance Head sign-off)."""
        require_approval_role(user, "head")
        if billing.status != BillingStatus.SUBMITTED:
            raise ValidationError(
                f"Billing {billing.billing_no} can only be approved from submitted "
                f"(status '{billing.status}')."
            )
        billing.status = BillingStatus.APPROVED
        billing.approved_by = user
        billing.approved_at = timezone.now()
        billing.rejected_by = None
        billing.rejected_at = None
        billing.rejection_note = ""
        billing.save(
            update_fields=[
                "status", "approved_by", "approved_at",
                "rejected_by", "rejected_at", "rejection_note", "updated_at",
            ]
        )
        cls._log(billing, "approved", actor=user)
        return billing

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def reject(cls, billing: BillingDocument, *, user, note: str = "") -> BillingDocument:
        """submitted -> draft with a rejection note (head only)."""
        require_approval_role(user, "head")
        if billing.status != BillingStatus.SUBMITTED:
            raise ValidationError("Only submitted billings can be rejected.")
        note = (note or "").strip()
        if not note:
            raise ValidationError("A rejection note is required.")
        billing.status = BillingStatus.DRAFT
        billing.rejected_by = user
        billing.rejected_at = timezone.now()
        billing.rejection_note = note
        billing.approved_by = None
        billing.approved_at = None
        billing.save(
            update_fields=[
                "status", "rejected_by", "rejected_at", "rejection_note",
                "approved_by", "approved_at", "updated_at",
            ]
        )
        cls._log(billing, "rejected", actor=user, note=note)
        return billing

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def post(cls, billing: BillingDocument, *, user) -> JournalEntry:
        """approved -> posted: build and post the billing's Journal Entry.

        The JE is built from the distribution lines, carries the RFP number in
        its Note/Reference field when the billing was based on an RFP, and
        tags 15550 / 15560 credit lines with the RFP number + billed amount.
        """
        require_approval_role(user, "head")
        if billing.status != BillingStatus.APPROVED:
            raise ValidationError(
                f"Billing {billing.billing_no} must be approved before posting "
                f"(status '{billing.status}')."
            )
        if billing.journal_entry_id:
            raise PostingError(f"Billing {billing.billing_no} is already posted.")

        rfp = billing.rfp
        period = FiscalPeriod.objects.filter(
            start_date__lte=billing.billing_date, end_date__gte=billing.billing_date
        ).first()

        description = f"Billing {billing.billing_no} {billing.party_name}".strip()
        ref_number = billing.reference
        if rfp is not None:
            description = f"{description} — RFP {rfp.ap_number}"
            ref_number = rfp.ap_number

        entry = JournalEntry.objects.create(
            entry_no=f"BI-{billing.billing_no}",
            company=billing.company,
            segment=billing.segment,
            fiscal_period=period,
            transaction_date=billing.billing_date,
            status=PostingStatus.APPROVED,
            description=description[:500],
            source_doc_type="BILL",
            source_doc_no=billing.billing_no,
            supplier_name=billing.party_name,
            ref_number=(ref_number or "")[:128],
            created_by=user,
        )
        for i, line in enumerate(billing.lines.order_by("line_no"), start=1):
            JournalEntryLine.objects.create(
                entry=entry,
                line_no=i,
                account=line.account,
                segment=line.segment,
                description=line.description,
                cost_center=line.cost_center,
                reference=cls._line_reference(billing, line),
                debit=line.debit,
                credit=line.credit,
            )
        entry.recalc_totals()
        PostingService.post(entry, user=user)

        billing.journal_entry = entry
        billing.status = BillingStatus.POSTED
        billing.save(update_fields=["journal_entry", "status", "updated_at"])
        cls._log(billing, "posted", actor=user)
        return entry

    # ----------------------------------------------------------- RFP tracing

    @staticmethod
    def _line_reference(billing: BillingDocument, line: BillingLine) -> str:
        """Note/Reference for a JE line.

        With an RFP basis, every line notes the RFP number; credit lines on the
        unbilled receivable accounts additionally record the amount billed so
        the credit traces to the RFP (requirement 4)."""
        if not billing.rfp_id:
            return ""
        rfp_no = billing.rfp.ap_number
        if line.side == "cr" and line.account.code in UNBILLED_CREDIT_ACCOUNTS:
            amount = line.debit or line.credit
            return f"RFP {rfp_no} — billed {amount:,.2f}"
        return f"RFP {rfp_no}"

    @staticmethod
    def _log(billing: BillingDocument, action: str, *, actor=None, note: str = "") -> None:
        """Audit-trail entry tagged as a Billing document."""
        from apps.ap.models import ActionLog
        from apps.ap.services import log_action

        log_action(billing, action, actor=actor, note=note, doc_type=ActionLog.DocType.BILL)