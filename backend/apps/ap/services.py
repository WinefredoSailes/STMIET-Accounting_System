"""AP services: RFP lifecycle, CONSO batch posting, CV payment clearing.

Rules enforced (ADR-018/019/020/022 + POSTING_RULES 7.2-7.4):
  - P2,500 threshold: below -> petty cash path (rejected here); >= -> RFP.
  - 4-level approval before CONSO; same person cannot hold two roles.
  - Amounts > P100,000 also require CNR approval (ADR-020 escalation).
  - RFP JE is built exactly from the Dr/Cr distribution lines as entered;
    Dr total must equal Cr total (credit accounts such as AP, payables to
    officers, and advances clearing are entered as lines).
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
        segment,
        purpose: str = "",
        lines: list[dict],  # [{side, segment, account_code, amount, description}]
        last_ap: str = "",
        user=None,
    ) -> RFPDocument:
        """Create an RFP whose lines carry explicit Dr/Cr sides. The RFP amount
        is the total of the debit lines; debits must equal credits so the
        posted JE balances, and must meet the P2,500 threshold (ADR-022)."""
        dr_total = Decimal("0.00")
        cr_total = Decimal("0.00")
        parsed = []
        for line in lines:
            amt = money(line["amount"])
            if amt <= 0:
                raise ValidationError("Each charge line must have an amount greater than zero.")
            side = str(line.get("side") or "dr").lower()
            if side not in ("dr", "cr"):
                raise ValidationError(f"Line side must be Dr or Cr, got '{side}'.")
            parsed.append((side, amt))
            if side == "dr":
                dr_total += amt
            else:
                cr_total += amt
        if dr_total <= 0:
            raise ValidationError("An RFP needs at least one debit (Dr) line.")
        if dr_total != cr_total:
            raise ValidationError(
                f"Charge lines do not balance: Dr {dr_total} vs Cr {cr_total} — the posted entry must balance."
            )
        if dr_total < RFP_MIN_AMOUNT:
            raise ValidationError(
                f"Amount {dr_total} is below the RFP threshold {RFP_MIN_AMOUNT}; use the petty cash voucher."
            )

        particulars = lines[0].get("description", "") if lines else ""
        rfp = RFPDocument.objects.create(
            ap_number=ap_number,
            last_ap=last_ap or (payee.last_ap if payee else ""),
            rfp_date=rfp_date,
            payee=payee,
            particulars=particulars,
            purpose=purpose,
            segment=segment,
            amount=dr_total,
            status="prepared",
            created_by=user,
        )
        for i, line in enumerate(lines, start=1):
            RFPLine.objects.create(
                rfp=rfp,
                line_no=i,
                side=str(line.get("side") or "dr").lower(),
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

        # ADR-036: the Accounting & Finance Head legitimately holds the
        # checked / acctg_approved / fin_approved trio on the same RFP —
        # but nobody else may hold two steps, the preparer may not approve
        # their own disbursement, and the COO (CNR) must stay a fresh hand.
        prior_steps = [
            s
            for s, uid in (
                ("checked", rfp.checked_by_id),
                ("acctg_approved", rfp.approved_by_acctg_id),
                ("fin_approved", rfp.approved_by_fin_id),
            )
            if uid and uid == user.id
        ]
        if user.id in (rfp.created_by_id, rfp.approved_by_cnr_id):
            raise ValidationError(
                "The person who prepared an RFP (or approved it as COO/CNR) "
                "cannot approve it again."
            )
        if role in prior_steps:
            raise ValidationError("This user already recorded this approval step.")

        # "submitted" (the API submit action) continues the chain at "checked".
        current = "prepared" if rfp.status == "submitted" else rfp.status
        try:
            idx = RFP_APPROVAL_STEPS.index(current)
        except ValueError:
            raise ValidationError(f"RFP is in unexpected status '{rfp.status}'.")
        next_role = RFP_APPROVAL_STEPS[idx + 1]
        if role != next_role:
            raise ValidationError(f"Expected approval role '{next_role}' but got '{role}'.")

        field = ROLE_TO_FIELD[role]

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
        # ADR-036: the COO who signs as CNR must be a fresh hand.
        holders = [
            rfp.created_by_id,
            rfp.checked_by_id,
            rfp.approved_by_acctg_id,
            rfp.approved_by_fin_id,
        ]
        if user.id in [h for h in holders if h]:
            raise ValidationError(
                "The COO/CNR approval must come from a person who did not "
                "handle the earlier steps of this RFP."
            )
        rfp.approved_by_cnr = user
        rfp.status = "cnr_approved"
        rfp.save(update_fields=["approved_by_cnr", "status", "updated_at"])
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
            # JE = the Dr/Cr distribution lines exactly as entered (must
            # balance at create: Dr total == Cr total).
            for i, line in enumerate(rfp.lines.order_by("line_no"), start=1):
                kwargs = (
                    {"debit": line.amount}
                    if line.side == RFPLine.Side.DEBIT
                    else {"credit": line.amount}
                )
                JournalEntryLine.objects.create(
                    entry=entry, line_no=i, account=line.account,
                    description=line.description or rfp.particulars, **kwargs,
                )
            entry.recalc_totals()
            # ADR-033: CNR approval (the last RFP gate) is the JE approval gate
            # for entries above the threshold; PostingService refuses them as DRAFT.
            if rfp.status == "cnr_approved":
                entry.status = PostingStatus.APPROVED
                entry.save(update_fields=["status", "updated_at"])
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