"""AP services: RFP lifecycle, CONSO batch posting, CV payment clearing.

Rules enforced (ADR-018/019/020/022 + POSTING_RULES 7.2-7.4):
  - P2,500 threshold: below -> petty cash path (rejected here); >= -> RFP.
  - 4-level approval before CONSO; same person cannot hold two roles.
  - Amounts > P100,000 also require CNR approval (ADR-020 escalation).
  - Canonical RFP JE: Dr [lines sum {TOTAL}] | Cr Advances {define}
    | Cr AP {TOTAL - advances} (RESOLUTION #5).
  - CONSO approval posts every RFP in the batch atomically.
  - CV clears AP with WHT split.
"""

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from apps.core.exceptions import PostingError, ValidationError
from apps.core.money import money
from apps.foundation.models import Account
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService

from .models import (
    AdvanceToEmployee,
    CheckVoucher,
    CONSOBatch,
    RFPDocument,
    RFPLine,
    Supplier,
)

RFP_MIN_AMOUNT = Decimal("2500.00")
CNR_ESCALATION_THRESHOLD = Decimal("100000.00")

# Approval roles in order (ADR-020 RFP matrix).
RFP_APPROVAL_STEPS = ["prepared", "checked", "acctg_approved", "fin_approved"]

ROLE_TO_FIELD = {
    "prepared": "created_by",
    "checked": "checked_by",
    "acctg_approved": "approved_by_acctg",
    "fin_approved": "approved_by_fin",
}

SEGMENT_ADVANCES = {"DHPP": "12070", "DMIE": "12073", "OPS": "12076"}
SEGMENT_AP = {"DHPP": "20000", "DMIE": "20003", "OPS": "20006"}


def _account(code: str) -> Account:
    try:
        return Account.objects.get(code=code)
    except Account.DoesNotExist as exc:
        raise ValidationError(f"COA account {code} not found.") from exc


def _segment_account(map_: dict, segment) -> Account:
    code = map_.get(segment.code)
    if not code:
        raise ValidationError(f"Segment {segment.code} has no account mapping.")
    return _account(code)


class RFPService:
    """Creates and advances RFPs through their approval chain."""

    @classmethod
    @transaction.atomic
    def create_rfp(
        cls,
        *,
        ap_number: str,
        rfp_date: date,
        payee: Supplier,
        particulars: str,
        amount,
        segment,
        purpose: str = "",
        advance_amount: Decimal = Decimal("20000.00"),
        lines: list[dict],  # [{segment, account_code, amount}]
        last_ap: str = "",
        user=None,
    ) -> RFPDocument:
        amount = money(amount)
        advance = money(advance_amount)
        if amount < RFP_MIN_AMOUNT:
            raise ValidationError(
                f"Amount {amount} is below the RFP threshold {RFP_MIN_AMOUNT}; use the petty cash voucher."
            )
        if advance >= amount:
            raise ValidationError("Advance credit must be less than RFP total.")

        line_total = sum(money(l["amount"]) for l in lines)
        if line_total != amount:
            raise ValidationError(
                f"Charge lines total {line_total} but RFP amount is {amount}."
            )

        rfp = RFPDocument.objects.create(
            ap_number=ap_number,
            last_ap=last_ap or (payee.last_ap if payee else ""),
            rfp_date=rfp_date,
            payee=payee,
            particulars=particulars,
            purpose=purpose,
            segment=segment,
            amount=amount,
            advance_amount=advance,
            status="prepared",
            created_by=user,
        )
        for i, line in enumerate(lines, start=1):
            RFPLine.objects.create(
                rfp=rfp,
                line_no=i,
                segment=line["segment"],
                account=_account(line["account_code"]),
                amount=money(line["amount"]),
                description=line.get("description", ""),
            )
        if payee:
            payee.last_ap = ap_number
            payee.save(update_fields=["last_ap", "updated_at"])
        return rfp

    @classmethod
    def advance_step(cls, rfp: RFPDocument, *, role: str, user, comment: str = "") -> RFPDocument:
        """Move the RFP forward one approval role (ADR-020)."""
        if rfp.status == "posted":
            raise PostingError(f"RFP {rfp.ap_number} is already posted.")
        current = rfp.status
        try:
            idx = RFP_APPROVAL_STEPS.index(current)
        except ValueError:
            raise ValidationError(f"RFP is in unexpected status '{current}'.")
        next_role = RFP_APPROVAL_STEPS[idx + 1]
        if role != next_role:
            raise ValidationError(f"Expected approval role '{next_role}' but got '{role}'.")

        field = ROLE_TO_FIELD[role]

        # Same person cannot hold two roles on the same RFP (ADR-020).
        holders = [rfp.created_by_id, rfp.checked_by_id, rfp.approved_by_acctg_id, rfp.approved_by_fin_id]
        if user.id in [h for h in holders if h]:
            raise ValidationError("The same user cannot approve an RFP at two levels.")

        setattr(rfp, field, user)
        rfp.status = role
        rfp.save(update_fields=[field, "status", "updated_at"])
        return rfp

    @classmethod
    def approve_cnr(cls, rfp: RFPDocument, *, user) -> RFPDocument:
        if rfp.amount <= CNR_ESCALATION_THRESHOLD:
            raise ValidationError("CNR approval is only required above P100,000.")
        if rfp.status != "fin_approved":
            raise ValidationError("CNR approval comes after finance approval.")
        rfp.approved_by_cnr = user
        rfp.save(update_fields=["approved_by_cnr", "updated_at"])
        return rfp

    @classmethod
    def reject(cls, rfp: RFPDocument, *, user) -> RFPDocument:
        if rfp.status == "posted":
            raise PostingError("Posted RFPs cannot be rejected.")
        rfp.status = "rejected"
        rfp.save(update_fields=["status", "updated_at"])
        return rfp


class CONSOService:
    """Grades a CONSO batch and posts all member RFPs atomically (7.3)."""

    @classmethod
    @transaction.atomic
    def post_batch(cls, batch: CONSOBatch, *, user) -> CONSOBatch:
        rfps = list(batch.rfps.select_for_update().filter(status__in=("fin_approved", "cnr_approved")))
        allowed = [r for r in batch.rfps.all()]
        if len(rfps) != len(allowed):
            raise ValidationError("All RFPs in the batch must be finance-approved before CONSO posting.")

        for rfp in rfps:
            cls._post_one(rfp, user=user)
        batch.status = "posted"
        batch.reviewed_by = user
        batch.save(update_fields=["status", "reviewed_by", "updated_at"])
        return batch

    @classmethod
    def _post_one(cls, rfp: RFPDocument, *, user) -> JournalEntry:
        with transaction.atomic():
            entry = JournalEntry.objects.create(
                entry_no=rfp.ap_number,
                company=rfp.segment.company,
                segment=rfp.segment,
                transaction_date=rfp.rfp_date,
                status=PostingStatus.DRAFT,
                description=f"RFP {rfp.ap_number} {rfp.payee.name}",
                source_doc_type="RFP",
                source_doc_no=rfp.ap_number,
                created_by=user,
            )
            # Debits: RFP charge lines (must sum to amount - enforced at create).
            for i, line in enumerate(rfp.lines.order_by("line_no"), start=1):
                JournalEntryLine.objects.create(
                    entry=entry, line_no=i, account=line.account,
                    debit=line.amount, description=line.description or rfp.particulars,
                )
            # Credits: standing advance + AP balance (canonical formula).
            line_no = len(rfp.lines.all()) + 1
            JournalEntryLine.objects.create(
                entry=entry, line_no=line_no,
                account=_segment_account(SEGMENT_ADVANCES, rfp.segment),
                credit=rfp.advance_amount,
                description="Advances to Employees (clearing)",
            )
            JournalEntryLine.objects.create(
                entry=entry, line_no=line_no + 1,
                account=_segment_account(SEGMENT_AP, rfp.segment),
                credit=rfp.ap_balance,
                description=f"AP - {rfp.payee.name}",
            )
            entry.recalc_totals()
            PostingService.post(entry, user=user)
            rfp.journal_entry = entry
            rfp.status = "posted"
            rfp.save(update_fields=["journal_entry", "status", "updated_at"])
        return entry


class CVPaymentService:
    """Check Voucher: clears AP with optional WHT split (7.4)."""

    @classmethod
    @transaction.atomic
    def create_cv(
        cls,
        *,
        cv_number: str,
        cv_date: date,
        payee: Supplier,
        bank_account: Account,
        gross_amount,
        withheld_tax: Decimal = Decimal("0.00"),
        rfp: RFPDocument | None = None,
        check_no: str = "",
        user=None,
    ) -> CheckVoucher:
        gross = money(gross_amount)
        tax = money(withheld_tax)
        net = gross - tax
        if net < 0:
            raise ValidationError("Net amount cannot be negative.")

        cv = CheckVoucher.objects.create(
            cv_number=cv_number,
            cv_date=cv_date,
            rfp=rfp,
            payee=payee,
            bank_account=bank_account,
            gross_amount=gross,
            withheld_tax=tax,
            net_amount=net,
            check_no=check_no,
            status="created",
            created_by=user,
        )

        seg = rfp.segment if rfp else payee.default_segment
        if seg is None:
            raise ValidationError("CV requires a segment: link an RFP or set the supplier's default segment.")
        company = seg.company
        # JE: Dr AP {gross} | Cr Cash {net} + Cr WHT {tax}
        entry = JournalEntry.objects.create(
            entry_no=cv_number,
            company=company,
            segment=seg,
            transaction_date=cv_date,
            status=PostingStatus.DRAFT,
            description=f"Check voucher {cv_number} {payee.name}",
            source_doc_type="CV",
            source_doc_no=cv_number,
            created_by=user,
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=1,
            account=_segment_account(SEGMENT_AP, seg),
            debit=gross, description=f"AP - {payee.name}",
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=2, account=bank_account, credit=net,
            description=f"Cash - {bank_account.code}",
        )
        if tax > 0:
            JournalEntryLine.objects.create(
                entry=entry, line_no=3,
                account=_account(SEGMENT_AP_WHT.get(seg.code, "64110")),
                credit=tax, description="Withholding tax (expanded)",
            )
        entry.recalc_totals()
        PostingService.post(entry, user=user)
        cv.journal_entry = entry
        cv.status = "created"
        cv.save(update_fields=["journal_entry", "updated_at"])
        return cv


SEGMENT_AP_WHT = {"DHPP": "64110", "DMIE": "64113", "OPS": "64116"}


class AdvanceService:
    """Advances to Employees lifecycle (ADR-021): initiate, liquidate, close."""

    @classmethod
    def start(cls, *, employee_name, kind, segment, granted_date, amount, rfp=None, user=None) -> AdvanceToEmployee:
        return AdvanceToEmployee.objects.create(
            employee_name=employee_name, kind=kind, segment=segment,
            granted_date=granted_date, amount=money(amount), rfp=rfp,
            created_by=user,
        )

    @classmethod
    def liquidate(cls, advance: AdvanceToEmployee, *, amount, liquidate_date: date, user=None) -> AdvanceToEmployee:
        amt = money(amount)
        new_total = advance.liquidated_amount + amt
        if new_total > advance.amount:
            raise ValidationError(f"Liquidation {amt} exceeds outstanding {advance.outstanding}.")
        advance.liquidated_amount = new_total
        advance.liquidated_date = liquidate_date
        if new_total == advance.amount:
            advance.status = "liquidated"
        else:
            advance.status = "partially_liquidated"
        advance.save(update_fields=["liquidated_amount", "liquidated_date", "status", "updated_at"])
        return advance