"""Tax & Compliance services (BUILD-PLAN Phase 9).

Thin derivations + provisions over the posting engine. Figures come from the
posted GL (SI invoices in AR, CV withholding in AP, payroll feed), so nothing
here is a source of truth — it makes compliance one query, not a manual tally.
"""

from datetime import date
from decimal import Decimal

from apps.core.exceptions import ValidationError
from apps.core.money import money
from apps.foundation.models import SegmentAccountMap, resolve_segment_account


class VATService:
    """SI-level VAT-inclusive output VAT extraction (Phase 9).

    PH VAT: when a price is VAT-inclusive, output VAT = gross * rate/(1+rate).
    Net sales = gross - output VAT. No GL VAT accounts unless Alywin approves
    (Q1) — the figure is recorded for the VAT return / 2550Q prep.
    """

    VAT_RATE = Decimal("0.1200")

    @classmethod
    def extract_from_invoice(cls, invoice) -> "VATComputation":
        from .models import VATComputation

        gross = money(invoice.total)
        rate = cls.VAT_RATE
        output_vat = money(gross * rate / (Decimal("1.00") + rate))
        net = money(gross - output_vat)
        obj, _ = VATComputation.objects.update_or_create(
            invoice=invoice,
            defaults={
                "segment": invoice.segment,
                "vat_rate": rate,
                "gross_amount": gross,
                "net_amount": net,
                "output_vat": output_vat,
            },
        )
        return obj

    @classmethod
    def extract_for_period(cls, company, period_start: date, period_end: date) -> list:
        """Extract VAT for every VAT-able invoice booked in the window and
        return the computations (deterministic order by date then number)."""
        from apps.ar.models import ARInvoice

        invoices = (
            ARInvoice.objects.filter(
                segment__company=company,
                transaction_date__gte=period_start,
                transaction_date__lte=period_end,
                journal_entry__isnull=False,
            )
            .select_related("segment")
            .order_by("transaction_date", "invoice_no")
        )
        return [cls.extract_from_invoice(inv) for inv in invoices]

    @classmethod
    def period_summary(cls, computations) -> dict:
        """Aggregate a set of VATComputation rows."""
        total_gross = sum(c.gross_amount for c in computations)
        total_net = sum(c.net_amount for c in computations)
        total_vat = sum(c.output_vat for c in computations)
        return {
            "count": len(computations),
            "gross": money(total_gross),
            "net": money(total_net),
            "output_vat": money(total_vat),
        }


class WithholdingService:
    """BIR 2307/2306 prep from the AP/CV module's posted withholding (Phase 9).

    Every CV that carried a WHT split is a creditable (2307) or final (2306)
    certificate row. We derive these rows from posted CVs; compensation (2316)
    data comes from the payroll feed separately.
    """

    @classmethod
    def build_certificates(cls, *, cert_type: str = "2307",
                           period_start: date | None = None,
                           period_end: date | None = None) -> list:
        from apps.ap.models import CheckVoucher

        cvs = CheckVoucher.objects.filter(
            withheld_tax__gt=0, journal_entry__isnull=False, status__in=["signed", "released", "cleared"]
        )
        if period_start:
            cvs = cvs.filter(cv_date__gte=period_start)
        if period_end:
            cvs = cvs.filter(cv_date__lte=period_end)
        cvs = cvs.select_related("payee", "rfp__segment").order_by("cv_date", "cv_number")

        rows = []
        for cv in cvs:
            seg = cv.rfp.segment if cv.rfp and cv.rfp.segment else cv.payee.default_segment
            if seg is None:
                continue
            rows.append(
                {
                    "cert_type": cert_type,
                    "segment": seg,
                    "payee": cv.payee,
                    "tin": cv.payee.tin,
                    "gross_amount": cv.gross_amount,
                    "tax_amount": cv.withheld_tax,
                    "cv_number": cv.cv_number,
                }
            )
        return rows


class IncomeTaxService:
    """Income tax provision: Dr 64600 tax expense | Cr income tax payable.

    `taxable_income` is passed in (derived upstream — e.g. net profit after
    prior-year adjustments / the §13 closing flow); this service books the
    provision JE through the standard posting engine so every rule (balance,
    approval gate, immutability, reversal) applies.
    """

    DEFAULT_RATE = Decimal("0.2000")  # placeholder; Alywin confirms actual CIT rate

    @classmethod
    def provision(cls, *, company, segment, taxable_income, filing_period,
                  rate=None, entry_no="", user=None) -> "IncomeTaxProvision":
        from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
        from apps.posting.services import PostingService
        from .models import IncomeTaxProvision

        taxable = money(taxable_income)
        if taxable < 0:
            taxable = Decimal("0.00")
        rate = Decimal(str(rate)) if rate else cls.DEFAULT_RATE
        tax = money(taxable * rate)
        if tax < 0:
            raise ValidationError("Income tax provision cannot be negative.")

        expense_account = _income_tax_expense_account(segment)
        payable = resolve_segment_account(segment, SegmentAccountMap.ROLE_INCOME_TAX)

        entry = JournalEntry.objects.create(
            entry_no=entry_no or f"ITX-{filing_period}-{segment.code}",
            company=company,
            segment=segment,
            transaction_date=date.today(),
            status=PostingStatus.DRAFT,
            description=f"Income tax provision {filing_period} ({segment.code})",
            source_doc_type="ITX",
            source_doc_no=filing_period,
            created_by=user,
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=1, account=expense_account, debit=tax,
            description=f"Income tax expense ({rate:.4%})",
        )
        JournalEntryLine.objects.create(
            entry=entry, line_no=2, account=payable, credit=tax,
            description="Income tax payable",
        )
        entry.recalc_totals()
        PostingService.post(entry, user=user)

        return IncomeTaxProvision.objects.create(
            segment=segment,
            filing_period=filing_period,
            taxable_income=taxable,
            tax_rate=rate,
            tax_amount=tax,
            journal_entry=entry,
        )


class TaxCalendarService:
    """Filing tracking: enumerate obligations and mark filed/paid.

    Keeps a company's BIR deadlines visible so nothing slips ("bana-bana"
    elimination). Filing periods are described as text; due dates are set by
    the caller for the actual BIR schedule.
    """

    @classmethod
    def upsert(cls, *, company, form, filing_period, due_date,
               status="not_due", amount_due=Decimal("0.00"), user=None) -> "TaxCalendar":
        from .models import TaxCalendar

        obj, _ = TaxCalendar.objects.update_or_create(
            form=form,
            company=company,
            filing_period=filing_period,
            defaults={
                "due_date": due_date,
                "status": status,
                "amount_due": money(amount_due),
            },
        )
        return obj

    @classmethod
    def mark(cls, calendar, *, status, filed_date=None, paid_date=None, user=None) -> "TaxCalendar":
        if filed_date:
            calendar.filed_date = filed_date
        if paid_date:
            calendar.paid_date = paid_date
        calendar.status = status
        calendar.save(update_fields=["status", "filed_date", "paid_date", "updated_at"])
        return calendar


def _income_tax_expense_account(segment):
    """Income tax expense COA account (data-driven where possible).

    Uses a fixed 64600 prefix convention (the tax expense account); if a
    segment-specific tax expense account exists in the COA it is preferred.
    """
    from apps.foundation.models import Account

    code = None
    base = "64600"
    digit_map = {"DHPP": "0", "DMIE": "3", "OPS": "6"}
    if segment.code in digit_map:
        candidate = base[:-1] + digit_map[segment.code]
        if Account.objects.filter(code=candidate, is_postable=True).exists():
            code = candidate
    if code is None and not Account.objects.filter(code=base, is_postable=True).exists():
        raise ValidationError(
            f"No income tax expense account (64600 / 6460x) in COA for segment {segment.code}."
        )
    return Account.objects.get(code=code or base, is_postable=True)
