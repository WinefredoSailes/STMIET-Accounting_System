"""Bank Reconciliation Statement PDF exports (unified template, req. f/g).

Renders through the shared TableSpec engine (apps.core.exports) so PDF
matches the Excel statement layout: bank side / book side / variance plus
the prepared / pre-approved / approved signature trail.
"""

from decimal import Decimal

from apps.cash.models import BankReconLine
from apps.core.exports import Align, Column, TableSpec, pdf_spec_response

_CATEGORY_LABELS = dict(BankReconLine.Category.choices)

BANK_ADDS = ["deposit_in_transit", "bank_error_add"]
BANK_LESS = ["outstanding_checks", "bank_error_less"]
BOOK_ADDS = ["bank_interest_earned", "book_error_add"]
BOOK_LESS = ["bank_service_charge", "nsf_daif_charges", "book_error_less"]

_COLUMNS = [
    Column("Particulars", width_cm=11),
    Column("Reference", width_cm=6),
    Column("Amount", width_cm=4.5, align=Align.RIGHT, money=True),
]


def _section_rows(recon, grouped, title, unadj_label, unadj_value, adds, less,
                  adjusted_label, adjusted_value) -> list:
    rows = [[title, "", ""]]
    rows.append([unadj_label, "", unadj_value])
    rows.append(["Add:", "", ""])
    for cat in adds:
        lines = grouped.get(cat, [])
        subtotal = sum((l.amount for l in lines), Decimal("0.00"))
        rows.append([f"  {_CATEGORY_LABELS.get(cat, cat)}", "", subtotal])
        for line in lines:
            rows.append([f"    {line.description}".rstrip(), line.reference, line.amount])
    rows.append(["Less:", "", ""])
    for cat in less:
        lines = grouped.get(cat, [])
        subtotal = sum((l.amount for l in lines), Decimal("0.00"))
        rows.append([f"  {_CATEGORY_LABELS.get(cat, cat)}", "", subtotal])
        for line in lines:
            rows.append([f"    {line.description}".rstrip(), line.reference, line.amount])
    rows.append([adjusted_label, "", adjusted_value])
    return rows


def recon_table_spec(recon) -> TableSpec:
    from collections import defaultdict

    grouped: dict = defaultdict(list)
    for line in recon.lines.all():
        grouped[line.category].append(line)

    bank = recon.bank_account
    period_start = recon.period_start or recon.cycle.cycle_start
    period_end = recon.period_end or recon.cycle.cycle_end
    rows = _section_rows(
        recon, grouped, "BANK SIDE",
        "Unadjusted Cash Balance per Bank Statement",
        recon.unadjusted_bank_balance if recon.unadjusted_bank_balance is not None
        else recon.bank_statement_balance,
        BANK_ADDS, BANK_LESS,
        "Equals: ADJUSTED BANK BALANCE", recon.adjusted_bank_balance,
    )
    rows += _section_rows(
        recon, grouped, "BOOK SIDE",
        "Unadjusted Cash Balance per Books",
        recon.unadjusted_book_balance if recon.unadjusted_book_balance is not None
        else recon.book_balance,
        BOOK_ADDS, BOOK_LESS,
        "Equals: ADJUSTED BOOK BALANCE", recon.adjusted_book_balance,
    )
    variance = (recon.adjusted_bank_balance or Decimal("0.00")) - (
        recon.adjusted_book_balance or Decimal("0.00")
    )
    return TableSpec(
        title=(
            f"BANK RECONCILIATION STATEMENT — {bank.bank_name or bank.name} "
            f"({bank.code}) {period_start:%b %d, %Y}–{period_end:%b %d, %Y}"
        ),
        columns=_COLUMNS,
        rows=rows,
        totals_row=["VARIANCE (Adjusted Bank − Adjusted Book)", "", variance],
        notes=[
            f"Status: {recon.status}",
            f"Prepared by: {recon.prepared_by or ''} {recon.prepared_at or ''}",
            f"Pre-approved by: {recon.pre_approved_by or ''} {recon.pre_approved_at or ''}",
            f"Approved by: {recon.approved_by or ''} {recon.approved_at or ''}",
        ],
        page="portrait",
        sheet_title="RECON",
    )


def bank_recon_pdf_response(recon):
    code = recon.bank_account.code
    ps = recon.period_start or recon.cycle.cycle_start
    pe = recon.period_end or recon.cycle.cycle_end
    return pdf_spec_response(
        recon_table_spec(recon), f"BANK-RECON-{code}-{ps:%Y%m%d}-{pe:%Y%m%d}.pdf"
    )


def consolidated_recon_pdf_response(company, period_start, period_end):
    from apps.cash.services import BankReconService

    data = BankReconService.get_consolidated_data(company, period_start, period_end)
    rows = []
    for recon in data["recons"]:
        rows.append([
            recon.bank_account.code,
            recon.adjusted_bank_balance,
            recon.adjusted_book_balance,
            (recon.adjusted_bank_balance or Decimal("0.00"))
            - (recon.adjusted_book_balance or Decimal("0.00")),
            recon.status,
        ])
    spec = TableSpec(
        title=(
            f"CONSOLIDATED BANK RECONCILIATION — {company.name} "
            f"{period_start:%b %d, %Y}–{period_end:%b %d, %Y}"
        ),
        columns=[
            Column("Bank", width_cm=4),
            Column("Adjusted Bank", width_cm=4.5, align=Align.RIGHT, money=True),
            Column("Adjusted Book", width_cm=4.5, align=Align.RIGHT, money=True),
            Column("Variance", width_cm=4.5, align=Align.RIGHT, money=True),
            Column("Status", width_cm=3.5),
        ],
        rows=rows,
        totals_row=[
            "TOTAL", data["total_adjusted_bank"],
            data["total_adjusted_book"], data["total_variance"], "",
        ],
        page="landscape",
        sheet_title="CONSO",
    )
    return pdf_spec_response(
        spec, f"BANK-RECON-CONSO-{period_start:%Y%m%d}-{period_end:%Y%m%d}.pdf"
    )
