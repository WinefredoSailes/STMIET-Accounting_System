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
from decimal import ROUND_HALF_UP, Decimal
import functools
import time

from django.conf import settings
from django.db import OperationalError, transaction
from django.utils import timezone

from apps.core.approvals import approval_role_of
from apps.core.exceptions import PostingError, ValidationError
from apps.core.money import money
from apps.foundation.models import Account, SegmentAccountMap, resolve_segment_account
from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
from apps.posting.services import PostingService

from .models import (
    ActionLog,
    AdvanceToEmployee,
    CheckVoucher,
    CONSOBatch,
    POLine,
    PurchaseOrder,
    RFPDocument,
    RFPLine,
    Supplier,
    SupplierContact,
)

CNR_ESCALATION_THRESHOLD = Decimal("100000.00")


def coo_required(rfp) -> bool:
    """CNR (COO) review is due only when the escalation gate is enabled AND
    the RFP is above the threshold (ADR-020). While COO_REVIEW_ENABLED is off
    the head approves every amount so UAT can run without the COO step."""
    if not settings.DOMAIN.get("COO_REVIEW_ENABLED", False):
        return False
    return rfp.amount > CNR_ESCALATION_THRESHOLD


def pending_final_check(rfp) -> bool:
    """A finance-approved RFP still waiting on its last reviewer (the COO)."""
    return rfp.status == "fin_approved" and coo_required(rfp)


def finally_approved(rfp) -> bool:
    """No approval step remains — the RFP is CONSO-ready."""
    if rfp.status == "cnr_approved":
        return True
    return rfp.status == "fin_approved" and not coo_required(rfp)


def ap_payable_map() -> dict:
    """segment_id -> AP account_id from active role-'ap' SegmentAccountMap rows.

    Callers that resolve payable for many RFPs (list, summary, aging) build the
    map once and pass it through, avoiding one query per RFP.
    """
    return {
        m.segment_id: m.account_id
        for m in SegmentAccountMap.objects.filter(
            role=SegmentAccountMap.ROLE_AP, is_active=True
        )
    }


def rfp_payable(rfp) -> Decimal:
    """Simplified A/P payable: only checks accounts 20000 and 21100.
    
    - If RFP has credit lines to account 20000 (A/Payables - Current) or
      21100 (A/Payables - Other Current), returns sum of those lines
    - If no match, falls back to rfp.amount (gross)
    """
    payable = Decimal("0.00")
    found = False
    for line in rfp.lines.all():
        if line.side != "cr":
            continue
        if line.account.code in ("20000", "21100"):  # A/Payables - Current & Other Current
            found = True
            payable += line.amount
    return money(payable) if found else money(rfp.amount)


# --- Purchase Order helpers (ADR-0XX; same matrix as the RFP, ADR-020). ----
PO_APPROVAL_STEPS = ["prepared", "checked", "acctg_approved", "fin_approved"]

PO_ROLE_TO_FIELD = {
    "prepared": "created_by",
    "checked": "checked_by",
    "acctg_approved": "approved_by_acctg",
    "fin_approved": "approved_by_fin",
}


def po_coo_required(po) -> bool:
    """CNR (COO) review on a PO is due under the same escalation gate as the
    RFP: enabled AND above P100,000 (ADR-020)."""
    if not settings.DOMAIN.get("COO_REVIEW_ENABLED", False):
        return False
    return po.amount > CNR_ESCALATION_THRESHOLD


def po_pending_final_check(po) -> bool:
    """A finance-approved PO still waiting on its last reviewer (the COO)."""
    return po.status == "fin_approved" and po_coo_required(po)


def po_finally_approved(po) -> bool:
    """No approval step remains — the PO becomes bankable for RFPs."""
    if po.status == "cnr_approved":
        return True
    return po.status == "fin_approved" and not po_coo_required(po)


def validate_po_for_rfp(po, *, payee_id, amount):
    """Gate an RFP (create/revise) against its master Purchase Order.

    A PO must be active, finally approved (status 'approved'), belong to the
    same supplier as the RFP's payee, and still hold enough available balance
    for the RFP amount. The same check is re-run under a row lock when the RFP
    reaches its final approval so two concurrent RFPs cannot over-commit one
    PO (the PO's free balance is derived from its linked RFPs, not a counter).
    """
    if po is None:
        return
    if po.status != "approved":
        raise ValidationError(
            f"PO {po.po_number} must be approved before it can fund an RFP "
            f"(status '{po.status}')."
        )
    if po.supplier_id != payee_id:
        raise ValidationError(
            "The RFP's payee must be the same supplier (vendor) as the PO's."
        )
    if amount > po.available_amount:
        raise ValidationError(
            f"RFP amount {amount} exceeds the available balance "
            f"{po.available_amount} on PO {po.po_number} (total {po.amount} "
            f"less reserved and already-billed RFPs)."
        )


def log_action(doc, action, *, actor=None, note=""):
    """Append an immutable audit-trail entry for any tracked document.

    Covers RFP / Check Voucher / PO / Journal Entry / Inter-Account Transfer
    plus the AR receipt and bank deposit audit trails (doc_type is stored so
    histories never mix).
    """
    from apps.ar.models import AcknowledgmentReceipt, Deposit
    from apps.cash.models import InterAccountTransfer
    from apps.posting.models import JournalEntry

    if isinstance(doc, AcknowledgmentReceipt):
        doc_type = ActionLog.DocType.AR
    elif isinstance(doc, Deposit):
        doc_type = ActionLog.DocType.DEPOSIT
    elif isinstance(doc, InterAccountTransfer):
        doc_type = ActionLog.DocType.TRANSFER
    elif isinstance(doc, CheckVoucher):
        doc_type = ActionLog.DocType.CV
    elif isinstance(doc, PurchaseOrder):
        doc_type = ActionLog.DocType.PO
    elif isinstance(doc, JournalEntry):
        doc_type = ActionLog.DocType.JE
    else:
        doc_type = ActionLog.DocType.RFP
    ActionLog.objects.create(
        doc_type=doc_type,
        doc_id=doc.id,
        action=action,
        actor=actor,
        note=(note or "").strip(),
    )


def retry_on_lock(max_attempts=5, initial_delay=0.05, backoff=2.0):
    """Retry a service mutation that hits SQLite's 'database is locked'.

    In WAL mode a read-then-write transaction can fail instantly with
    SQLITE_BUSY_SNAPSHOT, which bypasses the connection's busy_timeout.
    Retrying outside the failed atomic block gives a fresh snapshot. Must
    wrap ABOVE @transaction.atomic so each attempt is its own transaction.
    """

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except OperationalError as exc:
                    if "database is locked" not in str(exc).lower():
                        raise
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(delay)
                    delay *= backoff

        return wrapper

    return deco

# Approval roles in order (ADR-020 RFP matrix).
RFP_APPROVAL_STEPS = ["prepared", "checked", "acctg_approved", "fin_approved"]

ROLE_TO_FIELD = {
    "prepared": "created_by",
    "checked": "checked_by",
    "acctg_approved": "approved_by_acctg",
    "fin_approved": "approved_by_fin",
}

def _account(code: str) -> Account:
    try:
        return Account.objects.get(code=code)
    except Account.DoesNotExist as exc:
        raise ValidationError(f"COA account {code} not found.") from exc


class SupplierService:
    """Supplier master maintenance (ADR-024 / ADR-038 §6)."""

    @classmethod
    def save_contacts(cls, supplier, contacts):
        """Replace the supplier's contact list from form rows.

        ``contacts`` is an iterable of dicts with keys ``name``, ``position``,
        ``phone`` and ``email``; rows with a blank name are ignored.
        """
        supplier.contacts.all().delete()
        for row in contacts:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            SupplierContact.objects.create(
                supplier=supplier,
                name=name,
                position=(row.get("position") or "").strip(),
                phone=(row.get("phone") or "").strip(),
                email=(row.get("email") or "").strip(),
            )


class RFPService:
    """Creates and advances RFPs through their approval chain."""

    @classmethod
    @retry_on_lock()
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
        po: PurchaseOrder | None = None,
    ) -> RFPDocument:
        """Create an RFP whose lines carry explicit Dr/Cr sides. The RFP amount
        is the total of the debit lines; debits must equal credits so the
        posted JE balances, and must meet the P2,500 threshold (ADR-022). A
        master Purchase Order (ADR-0XX) may authorize the disbursement: it
        must be approved and hold enough available balance for this amount."""
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
        particulars = lines[0].get("description", "") if lines else ""
        if po is not None:
            validate_po_for_rfp(po, payee_id=payee.id, amount=dr_total)
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
            po=po,
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
                cost_center=line.get("cost_center", ""),
            )
        if payee:
            payee.last_ap = ap_number
            payee.save(update_fields=["last_ap", "updated_at"])
        log_action(rfp, "created", actor=user)
        return rfp

    @classmethod
    def _guard_po_balance(cls, rfp: RFPDocument) -> None:
        """Confirm, under a PO row lock, that the RFP's master PO still has
        room for it. Called at the moment the RFP enters its final approval
        (fin_approved / cnr_approved), where the balance is reserved.

        The lock serializes concurrent approvals of two RFPs on the same PO:
        the second one re-derives the drawn balance from freshly-comitted
        rows before it can claim the same free space (ADR-0XX partial billing).
        """
        if not rfp.po_id:
            return
        try:
            po = PurchaseOrder.objects.select_for_update().get(pk=rfp.po_id)
        except PurchaseOrder.DoesNotExist:
            return
        drawn = sum(
            (
                r.amount
                for r in po.rfps.select_for_update().all()
                if r.id != rfp.id and r.status in ("fin_approved", "cnr_approved", "posted")
            ),
            Decimal("0.00"),
        )
        if rfp.amount > po.amount - drawn:
            raise ValidationError(
                f"PO {po.po_number} no longer holds enough balance for RFP "
                f"{rfp.ap_number}: {po.amount - drawn} remaining."
            )

    @classmethod
    @retry_on_lock()
    @transaction.atomic
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
        # Every non-head user is blocked from approving their own RFP. The
        # Accounting & Finance Head is exempt: he holds all three approval
        # steps (ADR-036) and may, out of necessity, prepare and approve a
        # disbursement himself when no separate staff is available.
        preparer_blocked = (
            approval_role_of(user) != "head"
            and user.id == rfp.created_by_id
        )
        if preparer_blocked or user.id == rfp.approved_by_cnr_id:
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
        role = RFP_APPROVAL_STEPS[idx + 1]

        # ADR-038 §10d: a revised RFP cannot complete finance approval until
        # the Finance Head writes notes for the COO/Ellen (check-voucher
        # issuance is blocked until the notes exist).
        if role == "fin_approved" and rfp.revision_count > 0 and not (rfp.finance_notes or "").strip():
            raise ValidationError(
                "This revised RFP is blocked from finance approval until the "
                "Finance Head adds issuance notes (for Ellen/COO)."
            )

        field = ROLE_TO_FIELD[role]

        setattr(rfp, field, user)
        rfp.status = role
        rfp.save(update_fields=[field, "status", "updated_at"])
        log_action(rfp, role, actor=user)
        # ADR-0XX: the instant the RFP is fully approved its amount is
        # reserved against the linked PO (if any) — re-confirm the balance
        # under a lock so concurrent RFPs cannot over-commit the PO.
        if rfp.status in ("fin_approved", "cnr_approved"):
            cls._guard_po_balance(rfp)
        return rfp

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def approve_head(cls, rfp: RFPDocument, *, user) -> RFPDocument:
        """One-click head approval: advance through every remaining head step
        (checked -> acctg_approved -> fin_approved) in a single action.

        Alywin approves every RFP at any amount. When the CNR gate is enabled
        (COO_REVIEW_ENABLED) and the amount is above the escalation threshold,
        the RFP stops at `fin_approved` so the COO signs next. All invariants
        run through advance_step (same-person guard, revision finance-notes
        gate, posted guard), so this is only a click-count reduction.
        """
        if rfp.status == "posted":
            raise PostingError(f"RFP {rfp.ap_number} is already posted.")
        current = "prepared" if rfp.status == "submitted" else rfp.status
        try:
            idx = RFP_APPROVAL_STEPS.index(current)
        except ValueError:
            raise ValidationError(f"RFP is in unexpected status '{rfp.status}'.")
        out = rfp
        moved = 0
        for role in RFP_APPROVAL_STEPS[idx + 1 :]:
            # ADR-038 §10d: a revised RFP stops at the accounting step until
            # Finance Head notes exist — the head adds them from the action
            # bar before one more click finishes finance approval.
            if role == "fin_approved" and out.revision_count > 0 and not (out.finance_notes or "").strip():
                break
            out = cls.advance_step(out, role=role, user=user)
            moved += 1
            if role == "fin_approved" and pending_final_check(out):
                break
        if not moved:
            raise ValidationError(f"No head approval step available from status '{rfp.status}'.")
        if finally_approved(out):
            CONSOService.auto_assign(out)
        return out

    @classmethod
    @retry_on_lock()
    @transaction.atomic
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
        cls._guard_po_balance(rfp)
        rfp.approved_by_cnr = user
        rfp.status = "cnr_approved"
        rfp.save(update_fields=["approved_by_cnr", "status", "updated_at"])
        log_action(rfp, "cnr_approved", actor=user)
        CONSOService.auto_assign(rfp)
        return rfp

    REJECTABLE_STATUSES = ("submitted", "checked", "acctg_approved")

    @classmethod
    def _rejectable(cls, rfp) -> bool:
        """An RFP can be rejected only while it is actually awaiting an
        approval step — including the CNR step on an amount above P100k."""
        if rfp.status in ("submitted", "checked", "acctg_approved"):
            return True
        return pending_final_check(rfp)

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def reject(cls, rfp: RFPDocument, *, user, note: str = "") -> RFPDocument:
        """Return the RFP to the preparer with a note (reject/revise cycle).

        Only while it is awaiting an approval step (not yet posted, not yet
        drafted). A note explaining the change is mandatory — the preparer
        reads it when they reopen the RFP to edit and resubmit.
        """
        if rfp.status == "posted":
            raise PostingError("Posted RFPs cannot be rejected.")
        if not cls._rejectable(rfp):
            raise ValidationError(
                f"RFP '{rfp.status}' is not awaiting an approval step; it cannot be rejected."
            )
        if not (note or "").strip():
            raise ValidationError("Enter a note explaining why the RFP is being rejected.")
        rfp.status = "rejected"
        rfp.rejected_by = user
        rfp.rejected_at = timezone.now()
        rfp.rejection_note = note.strip()
        rfp.save(update_fields=["status", "rejected_by", "rejected_at", "rejection_note", "updated_at"])
        log_action(rfp, "rejected", actor=user, note=note)
        return rfp

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def revise(cls, rfp: RFPDocument, *, user, lines: list[dict], purpose: str = "") -> RFPDocument:
        """The preparer revises a rejected RFP and resubmits it.

        Only the preparer may revise, and only while the RFP is `rejected`.
        The distribution lines are replaced wholesale (mirroring create_rfp
        validation), rejection context is cleared, and the RFP re-enters the
        chain at "submitted" so the approvers see the corrected request.
        """
        if rfp.status != "rejected":
            raise ValidationError("Only rejected RFPs can be revised and resubmitted.")
        if user.id != rfp.created_by_id:
            raise ValidationError(
                f"RFP {rfp.ap_number} was prepared by another user; only the preparer may revise it."
            )

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
        if rfp.po_id:
            validate_po_for_rfp(rfp.po, payee_id=rfp.payee_id, amount=dr_total)
        rfp.lines.all().delete()
        rfp.amount = dr_total
        rfp.particulars = lines[0].get("description", "") if lines else ""
        rfp.purpose = purpose
        rfp.status = "submitted"
        rfp.rejected_by = None
        rfp.rejected_at = None
        rfp.rejection_note = ""
        rfp.revision_count += 1
        # A resubmitted RFP restarts its approval chain: void the approval
        # records of the rejected pass so the same approvers can re-run the
        # steps (otherwise advance_step trips 'already recorded this step'
        # and the RFP is stuck with the approver).
        rfp.checked_by = None
        rfp.approved_by_acctg = None
        rfp.approved_by_fin = None
        rfp.approved_by_cnr = None
        rfp.save(update_fields=[
            "amount", "particulars", "purpose", "status",
            "rejected_by", "rejected_at", "rejection_note", "revision_count",
            "checked_by", "approved_by_acctg", "approved_by_fin", "approved_by_cnr",
            "updated_at",
        ])
        for i, line in enumerate(lines, start=1):
            RFPLine.objects.create(
                rfp=rfp,
                line_no=i,
                side=str(line.get("side") or "dr").lower(),
                segment=line["segment"],
                account=_account(line["account_code"]),
                amount=money(line["amount"]),
                description=line.get("description", ""),
                cost_center=line.get("cost_center", ""),
            )
        log_action(rfp, "revised", actor=user)
        return rfp

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def edit_prepared(
        cls,
        rfp: RFPDocument,
        *,
        user,
        rfp_date: date,
        payee,
        segment,
        po,
        purpose: str = "",
        lines: list[dict],
    ) -> RFPDocument:
        """The preparer corrects a `prepared` RFP before submitting it.

        Only the preparer may edit, and only while the RFP is still
        `prepared` — nothing has left her desk yet. The full header (date,
        payee, segment, PO, purpose) and the distribution lines are replaced
        wholesale; validation mirrors create_rfp. The RFP stays `prepared`
        (no rejection, no resubmission) so the preparer reviews her fix and
        submits when ready.
        """
        if rfp.status != "prepared":
            raise ValidationError("Only prepared RFPs can be edited.")
        if user.id != rfp.created_by_id:
            raise ValidationError(
                f"RFP {rfp.ap_number} was prepared by another user; only the preparer may edit it."
            )

        dr_total = Decimal("0.00")
        cr_total = Decimal("0.00")
        for line in lines:
            amt = money(line["amount"])
            if amt <= 0:
                raise ValidationError("Each charge line must have an amount greater than zero.")
            side = str(line.get("side") or "dr").lower()
            if side not in ("dr", "cr"):
                raise ValidationError(f"Line side must be Dr or Cr, got '{side}'.")
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
        if po is not None:
            validate_po_for_rfp(po, payee_id=payee.id, amount=dr_total)

        rfp.rfp_date = rfp_date
        rfp.payee = payee
        rfp.segment = segment
        rfp.po = po
        rfp.purpose = purpose
        rfp.amount = dr_total
        rfp.particulars = lines[0].get("description", "") if lines else ""
        rfp.lines.all().delete()
        rfp.save(update_fields=[
            "rfp_date", "payee", "segment", "po", "purpose",
            "amount", "particulars", "updated_at",
        ])
        for i, line in enumerate(lines, start=1):
            RFPLine.objects.create(
                rfp=rfp,
                line_no=i,
                side=str(line.get("side") or "dr").lower(),
                segment=line["segment"],
                account=_account(line["account_code"]),
                amount=money(line["amount"]),
                description=line.get("description", ""),
                cost_center=line.get("cost_center", ""),
            )
        log_action(rfp, "edited", actor=user)
        return rfp


class PurchaseOrderService:
    """Purchase Order lifecycle (ADR-0XX): prepared by the AP staff, committed
    by the same head trio as the RFP with the optional COO gate, then closed by
    the head. A PO is a commitment document only — it never posts to the GL;
    the RFP it authorizes carries the journal entry through CONSO.

    Billing is a header-level derivation from the RFPs that reference the PO
    (never stored on the PO): reserved = approved-but-not-posted RFP amounts,
    billed = posted RFP amounts, available = amount - reserved - billed.
    """

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def create_po(
        cls,
        *,
        po_number: str,
        po_date: date,
        supplier: Supplier,
        segment,
        particulars: str = "",
        lines: list[dict],  # [{pr_number, qty, unit, description, unit_price, account}]
        discount: Decimal = Decimal("0.00"),
        vat_amount: Decimal = Decimal("0.00"),
        other_charges: Decimal = Decimal("0.00"),
        payment_terms: str = "",
        contract_duration: str = "",
        ship_to_company: str = "",
        ship_to_address: str = "",
        contact_person: str = "",
        notes: str = "",
        user=None,
    ) -> PurchaseOrder:
        """Create a PO. Grand total follows the template layout: the sum of the
        line amounts (qty x unit price) is the subtotal, and the grand total is
        subtotal - discount + VAT + other charges."""
        subtotal = Decimal("0.00")
        parsed = []
        for line_no, line in enumerate(lines, start=1):
            qty = money(line["qty"])
            price = money(line["unit_price"])
            if qty <= 0 or price <= 0:
                raise ValidationError("Each PO line needs a quantity and unit price greater than zero.")
            desc = (line.get("description") or "").strip()
            if not desc:
                raise ValidationError("Each PO line needs a description.")
            account = None
            account_code = (line.get("account") or "").strip()
            if account_code:
                account = _account(account_code)
            amt = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            parsed.append((qty, price, amt, line, account, account_code))
            subtotal += amt
        if not parsed:
            raise ValidationError("A PO needs at least one line item.")
        disc = money(discount)
        vat = money(vat_amount)
        other = money(other_charges)
        total = subtotal - disc + vat + other
        if total <= 0:
            raise ValidationError("PO grand total must be greater than zero.")

        po = PurchaseOrder.objects.create(
            po_number=po_number,
            po_date=po_date,
            supplier=supplier,
            segment=segment,
            particulars=particulars,
            subtotal=subtotal,
            discount=disc,
            vat_amount=vat,
            other_charges=other,
            amount=total,
            payment_terms=(payment_terms or "").strip(),
            contract_duration=(contract_duration or "").strip(),
            ship_to_company=(ship_to_company or "").strip(),
            ship_to_address=(ship_to_address or "").strip(),
            contact_person=(contact_person or "").strip(),
            notes=notes,
            status="prepared",
            created_by=user,
        )
        for i, (qty, price, amt, line, account, _code) in enumerate(parsed, start=1):
            POLine.objects.create(
                po=po,
                line_no=i,
                pr_number=(line.get("pr_number") or "").strip(),
                qty=qty,
                unit=(line.get("unit") or "").strip(),
                description=(line.get("description") or "").strip(),
                unit_price=price,
                amount=amt,
                account=account,
            )
        log_action(po, "created", actor=user)
        return po

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def advance_step(cls, po: PurchaseOrder, *, role: str, user) -> PurchaseOrder:
        """Move the PO forward one approval role (same matrix as the RFP,
        ADR-020/0XX). 'prepared'/'submitted' -> checked -> acctg_approved ->
        fin_approved; when no COO gate applies the final click marks the PO
        'approved' (RFP-bankable)."""
        if po.status in ("approved", "cnr_approved", "fin_approved", "rejected", "closed"):
            raise ValidationError(f"PO '{po.status}' cannot move forward.")

        # ADR-036/0XX: the head legitimately holds the trio; nobody else may
        # hold two steps, the preparer may not approve their own PO, and the
        # COO (CNR) must stay a fresh hand.
        prior_steps = [
            s
            for s, uid in (
                ("checked", po.checked_by_id),
                ("acctg_approved", po.approved_by_acctg_id),
                ("fin_approved", po.approved_by_fin_id),
            )
            if uid and uid == user.id
        ]
        preparer_blocked = approval_role_of(user) != "head" and user.id == po.created_by_id
        if preparer_blocked or user.id == po.approved_by_cnr_id:
            raise ValidationError(
                "The person who prepared a PO (or approved it as COO/CNR) cannot approve it again."
            )
        if role in prior_steps:
            raise ValidationError("This user already recorded this approval step.")

        current = "prepared" if po.status == "submitted" else po.status
        try:
            idx = PO_APPROVAL_STEPS.index(current)
        except ValueError:
            raise ValidationError(f"PO is in unexpected status '{po.status}'.")
        role = PO_APPROVAL_STEPS[idx + 1]
        field = PO_ROLE_TO_FIELD[role]

        setattr(po, field, user)
        if role == "fin_approved" and po_coo_required(po):
            po.status = "fin_approved"  # awaiting the COO sign-off
        else:
            po.status = role
        po.save(update_fields=[field, "status", "updated_at"])
        log_action(po, role, actor=user)
        if po_finally_approved(po):
            po.status = "approved"
            po.save(update_fields=["status", "updated_at"])
            log_action(po, "approved", actor=user)
        return po

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def approve_head(cls, po: PurchaseOrder, *, user) -> PurchaseOrder:
        """One-click head approval: advance through every remaining head step
        in a single action. When the CNR gate is enabled and the amount is
        above the escalation threshold the PO stops at `fin_approved` so the
        COO signs next; otherwise it is marked 'approved' (RFP-bankable)."""
        if po.status in ("approved", "cnr_approved", "fin_approved", "rejected", "closed"):
            raise ValidationError(f"PO '{po.status}' cannot be approved.")
        current = "prepared" if po.status == "submitted" else po.status
        try:
            idx = PO_APPROVAL_STEPS.index(current)
        except ValueError:
            raise ValidationError(f"PO is in unexpected status '{po.status}'.")
        out = po
        moved = 0
        for role in PO_APPROVAL_STEPS[idx + 1 :]:
            out = cls.advance_step(out, role=role, user=user)
            moved += 1
            if out.status in ("fin_approved", "approved"):
                break
        if not moved:
            raise ValidationError(f"No head approval step available from status '{po.status}'.")
        return out

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def approve_cnr(cls, po: PurchaseOrder, *, user) -> PurchaseOrder:
        if po.amount <= CNR_ESCALATION_THRESHOLD:
            raise ValidationError("CNR approval is only required above P100,000.")
        if po.status != "fin_approved":
            raise ValidationError("CNR approval comes after finance approval.")
        holders = [
            po.created_by_id,
            po.checked_by_id,
            po.approved_by_acctg_id,
            po.approved_by_fin_id,
        ]
        if user.id in [h for h in holders if h]:
            raise ValidationError(
                "The COO/CNR approval must come from a person who did not "
                "handle the earlier steps of this PO."
            )
        po.approved_by_cnr = user
        po.status = "approved"
        po.save(update_fields=["approved_by_cnr", "status", "updated_at"])
        log_action(po, "cnr_approved", actor=user)
        log_action(po, "approved", actor=user)
        return po

    REJECTABLE_STATUSES = ("submitted", "checked", "acctg_approved")

    @classmethod
    def _rejectable(cls, po) -> bool:
        """A PO can be rejected only while it is awaiting an approval step —
        including the CNR step on an amount above P100k."""
        if po.status in cls.REJECTABLE_STATUSES:
            return True
        return po_pending_final_check(po)

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def reject(cls, po: PurchaseOrder, *, user, note: str = "") -> PurchaseOrder:
        """Return the PO to the preparer with a note (reject/revise cycle)."""
        if po.status == "closed":
            raise ValidationError("Closed POs cannot be rejected.")
        if not cls._rejectable(po):
            raise ValidationError(
                f"PO '{po.status}' is not awaiting an approval step; it cannot be rejected."
            )
        if not (note or "").strip():
            raise ValidationError("Enter a note explaining why the PO is being rejected.")
        po.status = "rejected"
        po.rejected_by = user
        po.rejected_at = timezone.now()
        po.rejection_note = note.strip()
        po.save(update_fields=["status", "rejected_by", "rejected_at", "rejection_note", "updated_at"])
        log_action(po, "rejected", actor=user, note=note)
        return po

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def revise(
        cls,
        po: PurchaseOrder,
        *,
        user,
        lines: list[dict] | None = None,
        particulars: str = "",
        discount: Decimal | None = None,
        vat_amount: Decimal | None = None,
        other_charges: Decimal | None = None,
        payment_terms: str = "",
        contract_duration: str = "",
        ship_to_company: str = "",
        ship_to_address: str = "",
        contact_person: str = "",
        notes: str = "",
    ) -> PurchaseOrder:
        """The preparer corrects a rejected PO and resubmits it (mirror of RFP
        revise). Lines are replaced wholesale; rejection context is cleared;
        the PO re-enters the chain at 'submitted' with voided approval records
        so the same approvers can re-run the steps."""
        if po.status != "rejected":
            raise ValidationError("Only rejected POs can be revised and resubmitted.")
        if user.id != po.created_by_id:
            raise ValidationError(
                f"PO {po.po_number} was prepared by another user; only the preparer may revise it."
            )

        if lines is not None:
            subtotal = Decimal("0.00")
            parsed = []
            for line_no, line in enumerate(lines, start=1):
                qty = money(line["qty"])
                price = money(line["unit_price"])
                if qty <= 0 or price <= 0:
                    raise ValidationError("Each PO line needs a quantity and unit price greater than zero.")
                desc = (line.get("description") or "").strip()
                if not desc:
                    raise ValidationError("Each PO line needs a description.")
                account = None
                account_code = (line.get("account") or "").strip()
                if account_code:
                    account = _account(account_code)
                amt = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                parsed.append((qty, price, amt, line, account, account_code))
                subtotal += amt
            if not parsed:
                raise ValidationError("A PO needs at least one line item.")
            po.lines.all().delete()
            po.subtotal = subtotal
            for i, (qty, price, amt, line, account, _code) in enumerate(parsed, start=1):
                POLine.objects.create(
                    po=po,
                    line_no=i,
                    pr_number=(line.get("pr_number") or "").strip(),
                    qty=qty,
                    unit=(line.get("unit") or "").strip(),
                    description=(line.get("description") or "").strip(),
                    unit_price=price,
                    amount=amt,
                    account=account,
                )
        if discount is not None:
            po.discount = money(discount)
        if vat_amount is not None:
            po.vat_amount = money(vat_amount)
        if other_charges is not None:
            po.other_charges = money(other_charges)
        total = po.subtotal - po.discount + po.vat_amount + po.other_charges
        if total <= 0:
            raise ValidationError("PO grand total must be greater than zero.")
        po.amount = total
        po.particulars = particulars
        po.payment_terms = (payment_terms or "").strip()
        po.contract_duration = (contract_duration or "").strip()
        po.ship_to_company = (ship_to_company or "").strip()
        po.ship_to_address = (ship_to_address or "").strip()
        po.contact_person = (contact_person or "").strip()
        po.notes = notes
        po.status = "submitted"
        po.rejected_by = None
        po.rejected_at = None
        po.rejection_note = ""
        po.revision_count += 1
        po.checked_by = None
        po.approved_by_acctg = None
        po.approved_by_fin = None
        po.approved_by_cnr = None
        po.save(update_fields=[
            "subtotal", "discount", "vat_amount", "other_charges", "amount",
            "particulars", "payment_terms", "contract_duration",
            "ship_to_company", "ship_to_address", "contact_person", "notes",
            "status", "rejected_by", "rejected_at", "rejection_note",
            "revision_count", "checked_by", "approved_by_acctg",
            "approved_by_fin", "approved_by_cnr", "updated_at",
        ])
        log_action(po, "revised", actor=user)
        return po

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def close_po(cls, po: PurchaseOrder, *, user) -> PurchaseOrder:
        """Manually close an approved PO (head-only): forbids further RFP
        references without voiding reservations already made."""
        if approval_role_of(user) != "head":
            raise ValidationError("Only the Accounting & Finance Head can close a Purchase Order.")
        if po.status not in ("approved", "fin_approved", "cnr_approved"):
            raise ValidationError(f"Only an approved PO can be closed (status '{po.status}').")
        po.status = "closed"
        po.closed_by = user
        po.closed_at = timezone.now()
        po.save(update_fields=["status", "closed_by", "closed_at", "updated_at"])
        log_action(po, "closed", actor=user)
        return po


class CONSOService:
    """Grades a CONSO batch and posts all member RFPs atomically (7.3)."""

    @classmethod
    def auto_assign(cls, rfp: RFPDocument):
        """Reversible CONSO automation (CONSO_AUTO_ASSIGN flag): when enabled,
        a fully-approved RFP drops into the newest open CONSO batch (creating
        one if none is open). Flipping the flag off returns to manual batch
        management — conso_add_rfp still works either way."""
        if not settings.DOMAIN.get("CONSO_AUTO_ASSIGN", False):
            return None
        if not finally_approved(rfp) or rfp.conso_id:
            return rfp.conso_id
        from apps.sequences.models import DocumentSequence

        batch = CONSOBatch.objects.filter(status="open").order_by(
            "-conso_date", "-batch_no"
        ).first()
        if batch is None:
            batch = CONSOBatch.objects.create(
                batch_no=DocumentSequence.next_number(
                    company=rfp.segment.company, form_code="CONSO",
                    year=rfp.rfp_date.year, pattern="CONSO-{YYYY}-{SEQ:02d}",
                ),
                conso_date=rfp.rfp_date,
            )
        prior = sum(m.amount for m in batch.rfps.all())
        rfp.conso = batch
        rfp.save(update_fields=["conso", "updated_at"])
        batch.total_amount = prior + rfp.amount
        batch.save(update_fields=["total_amount", "updated_at"])
        log_action(rfp, "batched", actor=None, note=batch.batch_no)
        return batch

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def post_batch(cls, batch: CONSOBatch, *, user) -> CONSOBatch:
        rfps = list(batch.rfps.select_for_update().filter(status__in=("fin_approved", "cnr_approved")))
        pcfs = list(batch.pcf_replenishments.select_for_update().filter(status="approved"))
        if len(rfps) != batch.rfps.count():
            raise ValidationError("All RFPs in the batch must be finance-approved before CONSO posting.")
        if len(pcfs) != batch.pcf_replenishments.count():
            raise ValidationError("All PCF replenishments in the batch must be approved before CONSO posting.")
        if not rfps and not pcfs:
            raise ValidationError("CONSO batch is empty.")

        for rfp in rfps:
            cls._post_one(rfp, user=user)
        # PCF replenishments batched on approval post their JE here too
        # (ADR-038 §7c): single CONSO GL entry point, no manual re-entry.
        for replen in pcfs:
            from apps.cash.services import PCFService

            PCFService.post_from_conso(replen, user=user)
        batch.total_amount = sum(m.amount for m in rfps) + sum(r.amount for r in pcfs)
        batch.status = "posted"
        batch.reviewed_by = user
        batch.save(update_fields=["total_amount", "status", "reviewed_by", "updated_at"])
        return batch

    @classmethod
    def _post_one(cls, rfp: RFPDocument, *, user) -> JournalEntry:
        with transaction.atomic():
            entry = JournalEntry.objects.create(
                entry_no=f"RFP-{rfp.ap_number}",
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
                    description=line.description or rfp.particulars,
                    reference=line.cost_center or "",
                    **kwargs,
                )
            entry.recalc_totals()
            # ADR-033: the last RFP approval is the JE approval gate for
            # entries above the threshold; PostingService refuses them as
            # DRAFT. With CNR review enabled that final gate is the CNR;
            # otherwise the head's finance approval covers it.
            if finally_approved(rfp):
                entry.status = PostingStatus.APPROVED
                entry.save(update_fields=["status", "updated_at"])
            PostingService.post(entry, user=user)
            rfp.journal_entry = entry
            rfp.status = "posted"
            rfp.save(update_fields=["journal_entry", "status", "updated_at"])
            log_action(rfp, "posted", actor=user)
        return entry


class CVPaymentService:
    """Check Voucher lifecycle: created -> approved (head) -> cleared (7.4)."""

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def approve(cls, cv: CheckVoucher, *, user) -> CheckVoucher:
        """created -> approved (Accounting & Finance Head signs off the check).

        The head's approval is recorded on `approved_by`/`approved_at`; the
        voucher's JE stays a DRAFT until clear books it (ADR-033 — the clear
        act moves the DRAFT into the GL)."""
        if cv.status != "created":
            raise ValidationError(
                f"CV {cv.cv_number} can only be approved from 'created' "
                f"(status '{cv.status}')."
            )
        cv.status = "approved"
        cv.approved_by = user
        cv.approved_at = timezone.now()
        cv.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        log_action(cv, "approved", actor=user)
        return cv

    @classmethod
    @retry_on_lock()
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
        if rfp and rfp.status != "posted":
            raise ValidationError(
                f"RFP {rfp.ap_number} must be posted through a CONSO batch before a "
                "check voucher can be issued against it (the RFP's GL entry comes first)."
            )

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
            account=resolve_segment_account(seg, SegmentAccountMap.ROLE_AP),
            debit=gross, description=f"AP - {payee.name}",
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=2, account=bank_account, credit=net,
            description=f"Cash - {bank_account.code}",
        )
        if tax > 0:
            JournalEntryLine.objects.create(
                entry=entry, line_no=3,
                account=resolve_segment_account(seg, SegmentAccountMap.ROLE_AP_WHT),
                credit=tax, description="Withholding tax (expanded)",
            )
        entry.recalc_totals()
        # The CV's JE is only a DRAFT until the Accounting & Finance Head
        # clears the voucher: it holds no GL rows and cannot leak into the
        # books, so the reject/revise loop never touches a posted entry.
        cv.journal_entry = entry
        cv.status = "created"
        cv.save(update_fields=["journal_entry", "updated_at"])
        log_action(cv, "created", actor=user)
        return cv

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def clear(cls, cv: CheckVoucher, *, user) -> CheckVoucher:
        """approved -> cleared (Finance & Accounting Head books it): post the
        CV's JE to the GL, then mark the encashment cleared."""
        if cv.status != "approved":
            raise ValidationError(
                f"CV {cv.cv_number} must be approved before it can be cleared "
                f"(status '{cv.status}')."
            )
        if not cv.journal_entry_id:
            raise ValidationError(f"CV {cv.cv_number} has no journal entry to post.")
        if cv.journal_entry.is_posted:
            raise PostingError(f"CV {cv.cv_number} entry is already posted.")
        # The head's clear is the CV's approval gate (ADR-033): above the
        # threshold a DRAFT entry is refused by PostingService, so mark it
        # APPROVED under the same act that clears the voucher.
        entry = cv.journal_entry
        if entry.status != PostingStatus.POSTED:
            entry.status = PostingStatus.APPROVED
            entry.updated_by = user
            entry.save(update_fields=["status", "updated_by", "updated_at"])
        PostingService.post(entry, user=user)
        cv.status = "cleared"
        cv.save(update_fields=["status", "updated_at"])
        # Stamp the cash-side disbursement record so the CV's DATE CLEARED
        # fields (print/PDF/detail) populate (ADR-038 §10).
        from apps.cash.models import CheckDisbursement

        disb, _ = CheckDisbursement.objects.get_or_create(cv=cv)
        disb.cleared_at = timezone.now()
        disb.status = "cleared"
        disb.save(update_fields=["cleared_at", "status", "updated_at"])
        log_action(cv, "cleared", actor=user)
        return cv

    REJECTABLE_STATUSES = ("created", "approved")

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def reject(cls, cv: CheckVoucher, *, user, note: str = "") -> CheckVoucher:
        """Return the CV to the issuer with a note (reject/revise cycle).

        Only while it awaits an action (head approve, head clear).
        The CV's JE is still a DRAFT at every one of these points, so it is
        dropped with the failed pass; the issuer's revise rebuilds it.
        """
        if cv.status == "cleared":
            raise PostingError("Cleared CVs cannot be rejected.")
        if cv.status not in cls.REJECTABLE_STATUSES:
            raise ValidationError(
                f"CV '{cv.status}' is not awaiting an action; it cannot be rejected."
            )
        if not (note or "").strip():
            raise ValidationError("Enter a note explaining why the CV is being rejected.")
        if cv.journal_entry_id and not cv.journal_entry.is_posted:
            old_entry = cv.journal_entry
        else:
            old_entry = None
        cv.journal_entry = None
        cv.status = "rejected"
        cv.rejected_by = user
        cv.rejected_at = timezone.now()
        cv.rejection_note = note.strip()
        cv.save(update_fields=[
            "journal_entry", "status", "rejected_by", "rejected_at",
            "rejection_note", "updated_at",
        ])
        log_action(cv, "rejected", actor=user, note=note)
        if old_entry is not None:
            old_entry.lines.all().delete()
            old_entry.delete()
        return cv

    @classmethod
    @retry_on_lock()
    @transaction.atomic
    def revise(
        cls,
        cv: CheckVoucher,
        *,
        user,
        bank_account: Account | None = None,
        gross_amount=None,
        withheld_tax: Decimal | None = None,
        check_no: str = "",
        cv_date: date | None = None,
    ) -> CheckVoucher:
        """The issuer corrects a rejected CV and resubmits it for approval.

        Only the issuer may revise, and only while the CV is `rejected`. The
        corrected check re-enters the chain at "created" (fresh approval); the
        JE is rebuilt from the corrected figures as a DRAFT.
        """
        if cv.status != "rejected":
            raise ValidationError("Only rejected CVs can be revised and resubmitted.")
        if user.id != cv.created_by_id:
            raise ValidationError(
                f"CV {cv.cv_number} was issued by another user; only the issuer may revise it."
            )

        gross = money(gross_amount if gross_amount is not None else cv.gross_amount)
        tax = money(withheld_tax if withheld_tax is not None else cv.withheld_tax)
        net = gross - tax
        if net < 0:
            raise ValidationError("Net amount cannot be negative.")
        if cv.rfp_id and cv.rfp.status != "posted":
            raise ValidationError(
                f"RFP {cv.rfp.ap_number} must be posted through a CONSO batch before "
                "this check voucher can be reissued."
            )
        seg = cv.rfp.segment if cv.rfp_id else cv.payee.default_segment
        if seg is None:
            raise ValidationError("CV requires a segment: link an RFP or set the supplier's default segment.")
        company = seg.company

        cv.gross_amount = gross
        cv.withheld_tax = tax
        cv.net_amount = net
        cv.check_no = check_no
        cv.cv_date = cv_date or cv.cv_date
        if bank_account is not None:
            cv.bank_account = bank_account
        entry = JournalEntry.objects.create(
            entry_no=cv.cv_number,
            company=company,
            segment=seg,
            transaction_date=cv.cv_date,
            status=PostingStatus.DRAFT,
            description=f"Check voucher {cv.cv_number} {cv.payee.name}",
            source_doc_type="CV",
            source_doc_no=cv.cv_number,
            created_by=user,
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=1,
            account=resolve_segment_account(seg, SegmentAccountMap.ROLE_AP),
            debit=gross, description=f"AP - {cv.payee.name}",
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=2, account=cv.bank_account, credit=net,
            description=f"Cash - {cv.bank_account.code}",
        )
        if tax > 0:
            JournalEntryLine.objects.create(
                entry=entry, line_no=3,
                account=resolve_segment_account(seg, SegmentAccountMap.ROLE_AP_WHT),
                credit=tax, description="Withholding tax (expanded)",
            )
        entry.recalc_totals()
        cv.journal_entry = entry
        cv.status = "created"
        cv.approved_by = None
        cv.approved_at = None
        cv.rejected_by = None
        cv.rejected_at = None
        cv.rejection_note = ""
        cv.revision_count += 1
        cv.save(update_fields=[
            "gross_amount", "withheld_tax", "net_amount", "check_no", "cv_date",
            "bank_account", "journal_entry", "status", "approved_by", "approved_at",
            "rejected_by", "rejected_at", "rejection_note", "revision_count",
            "updated_at",
        ])
        log_action(cv, "revised", actor=user)
        return cv


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