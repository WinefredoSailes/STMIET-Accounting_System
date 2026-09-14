"""Server-side PDF generation for the General Journal Voucher (ACCTG-FOR-012).

The downloadable "Export PDF" reproduces the print view (je_print.html)
EXACTLY — same document grid, merged cells, section bands, font hierarchy,
table borders and signature block — as a real vector/text PDF (selectable
text, embedded logo). Fixed column widths keep Debit/Credit aligned; the
distribution table repeats its header on every page when lines span multiple
pages.
"""

from decimal import Decimal, InvalidOperation
import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from apps.foundation.calendar import cycle_range_for

COMPANY_FALLBACK = "SEVEN-TRENT MACHINERIES INDUSTRIAL EQUIPMENT TRADING"
DOCUMENT_NO = "ACCTG-FOR-012"
DOCUMENT_EFFECTIVE = "08.18.2022"
DOCUMENT_REVISION = "02"

# Print view: 14 equal grid columns. SPAN replicates the HTML colspans.
GRID = 14
PAGE_W, PAGE_H = A4
MARGIN = 1.2 * cm
COLW = (PAGE_W - 2 * MARGIN) / GRID

# Print view band colours.
ORANGE = colors.HexColor("#fce4d6")
BAND_BORDER = colors.HexColor("#7c2d12")  # dark copy on the band
GRID_LINE = colors.HexColor("#000000")


def _money(value) -> str:
    try:
        return f"{Decimal(value):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return "0.00"


def _cycle_label(entry) -> str:
    start, end = cycle_range_for(entry.transaction_date, company=entry.company)
    if start.month == end.month:
        return f"{start:%b} {start.day}-{end.day}, {start:%Y}"
    return f"{start:%b} {start.day} - {end:%b} {end.day}, {end:%Y}"


def _logo_path():
    try:
        from django.contrib.staticfiles import finders
        return finders.find("stmiet-trans-logo.png")
    except Exception:
        return None


def _style_cell():
    return ParagraphStyle("cell", fontName="Helvetica", fontSize=7.5, leading=10)


def _style_cell_right():
    return ParagraphStyle("cellR", parent=_style_cell(), alignment=TA_RIGHT)


def _style_bold():
    return ParagraphStyle("bold", fontName="Helvetica-Bold", fontSize=7.5, leading=10)


def _style_bold_right():
    return ParagraphStyle("boldR", parent=_style_bold(), alignment=TA_RIGHT)


def _style_band():
    return ParagraphStyle(
        "band", fontName="Helvetica-Bold", fontSize=8.2, leading=11,
        textTransform="uppercase", textColor=BAND_BORDER,
    )


def _style_hdr():
    """Distribution column headers — 10px-ish bold uppercase, like the print."""
    return ParagraphStyle(
        "hdr", fontName="Helvetica-Bold", fontSize=7, leading=9,
        alignment=TA_LEFT, textTransform="uppercase",
    )


def _style_hdr_right():
    return ParagraphStyle("hdrR", parent=_style_hdr(), alignment=TA_RIGHT)


def _style_signame():
    return ParagraphStyle("sigN", fontName="Helvetica", fontSize=8.5, leading=11, alignment=TA_CENTER)


def _style_sigrole():
    return ParagraphStyle(
        "sigRole", fontName="Helvetica", fontSize=6.2, leading=8.5,
        alignment=TA_CENTER, textColor=colors.HexColor("#64748b"),
        textTransform="uppercase",
    )


def _base_style():
    return [
        ("GRID", (0, 0), (-1, -1), 0.4, GRID_LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]


def _band_row(text):
    """A single full-width band cell (section separator), like the print."""
    p = Paragraph(text, _style_band())
    t = Table([[p]], colWidths=[COLW * GRID])
    t.setStyle(TableStyle(
        _base_style() + [("BACKGROUND", (0, 0), (-1, -1), ORANGE)]
    ))
    return t


def _entry_info_table(entry):
    """ENTRY INFORMATION block — 14 columns, colspans mirror je_print.html."""
    cell = _style_cell()
    bold = _style_bold()
    rows = 6
    data = [[None] * GRID for _ in range(rows)]

    data[0][0] = Paragraph("VOUCHER REF #:", bold)
    data[0][3] = Paragraph(entry.entry_no, bold)
    data[0][7] = Paragraph("SUPPLIER / CUSTOMER:", bold)
    data[0][10] = Paragraph(entry.supplier_name or "-", cell)

    data[1][0] = Paragraph("PO:", bold)
    data[1][3] = Paragraph(entry.po or "-", cell)
    data[1][7] = Paragraph("REF #:", bold)
    data[1][10] = Paragraph(entry.ref_number or "-", cell)

    data[2][0] = Paragraph("DATE:", bold)
    data[2][3] = Paragraph(entry.transaction_date.strftime("%m/%d/%Y"), cell)
    data[2][7] = Paragraph("CYCLE:", bold)
    data[2][10] = Paragraph(_cycle_label(entry), cell)

    data[3][0] = Paragraph("SOURCE TYPE:", bold)
    data[3][3] = Paragraph(entry.source_doc_type or "-", cell)
    data[3][7] = Paragraph("SOURCE NO.:", bold)
    data[3][10] = Paragraph(entry.source_doc_no or "-", cell)

    data[4][0] = Paragraph("DESCRIPTION:", bold)
    data[4][3] = Paragraph(entry.description, cell)

    spans = [
        ("SPAN", (0, 0), (2, 0)),   # VOUCHER REF #
        ("SPAN", (3, 0), (6, 0)),
        ("SPAN", (7, 0), (9, 0)),   # SUPPLIER
        ("SPAN", (10, 0), (13, 0)),
        ("SPAN", (0, 1), (2, 1)), ("SPAN", (3, 1), (6, 1)),
        ("SPAN", (7, 1), (9, 1)), ("SPAN", (10, 1), (13, 1)),
        ("SPAN", (0, 2), (2, 2)), ("SPAN", (3, 2), (6, 2)),
        ("SPAN", (7, 2), (9, 2)), ("SPAN", (10, 2), (13, 2)),
        ("SPAN", (0, 3), (2, 3)), ("SPAN", (3, 3), (6, 3)),
        ("SPAN", (7, 3), (9, 3)), ("SPAN", (10, 3), (13, 3)),
        ("SPAN", (0, 4), (2, 4)), ("SPAN", (3, 4), (13, 4)),
    ]
    t = Table(data, colWidths=[COLW] * GRID)
    t.setStyle(TableStyle(_base_style() + spans))
    return t


def _distribution_table(entry):
    """ACCOUNT DISTRIBUTION — #|COA|Account Name|Segment|Cost Center|Description|Debit|Credit.

    Header row repeats on every page (repeatRows=1) so multi-page entries
    keep aligned columns; long names/descriptions wrap inside their fixed
    column (Paragraph cells).
    """
    cell = _style_cell()
    cell_right = _style_cell_right()
    bold = _style_bold()
    bold_right = _style_bold_right()

    header = [
        Paragraph("#", _style_hdr()),
        Paragraph("COA", _style_hdr()),
        Paragraph("Account Name", _style_hdr()),
        Paragraph("Segment", _style_hdr()),
        Paragraph("Cost Center", _style_hdr()),
        Paragraph("Description", _style_hdr()),
        Paragraph("Debit", _style_hdr_right()),
        Paragraph("Credit", _style_hdr_right()),
    ]
    rows = [header]
    entry_segment_code = entry.segment.code if entry.segment else ""
    for line in entry.lines.order_by("line_no"):
        # Lines may carry a NULL segment (system-posted entries); fall back
        # to the entry-level segment, mirroring je_detail/je_print.
        segment_code = line.segment.code if line.segment else entry_segment_code
        rows.append(
            [
                Paragraph(str(line.line_no), cell),
                Paragraph(line.account.code, cell),
                Paragraph(line.account.name, cell),
                Paragraph(segment_code, cell),
                Paragraph(line.cost_center or "-", cell),
                Paragraph(line.description or "-", cell),
                Paragraph(_money(line.debit), cell_right),
                Paragraph(_money(line.credit), cell_right),
            ]
        )
    totals = [
        Paragraph("TOTALS", bold),
        "", "", "", "", "",
        Paragraph(_money(entry.total_debit), bold_right),
        Paragraph(_money(entry.total_credit), bold_right),
    ]
    rows.append(totals)

    grid = Table(
        rows,
        colWidths=[c * cm for c in (0.45, 2.2, 3.6, 1.0, 2.4, 3.9, 2.2, 2.2)],
        repeatRows=1,
        splitByRow=1,
    )
    style = _base_style()
    style += [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, -1), (-1, -1), ORANGE),
        ("SPAN", (0, -1), (5, -1)),
        ("ALIGN", (6, -1), (7, -1), "RIGHT"),
    ]
    grid.setStyle(TableStyle(style))
    return grid


def _signature_table(requested_by, approved_by, rows=4):
    """PREPARED BY / APPROVED BY block (2 columns of 7 grid cols each)."""
    bold = _style_bold()
    signame = _style_signame()
    sigrole = _style_sigrole()
    data = [
        [Paragraph("Prepared By:", bold), Paragraph("Approved By:", bold)],
        ["", ""],  # empty signature line
        [Paragraph(requested_by or "", signame), Paragraph(approved_by or "", signame)],
        [Paragraph("Signature over Printed Name", sigrole),
         Paragraph("Signature over Printed Name", sigrole)],
    ]
    t = Table(data, colWidths=[7 * COLW, 7 * COLW])
    style = _base_style()
    style += [
        ("ALIGN", (0, -2), (-1, -2), "CENTER"),
        ("VALIGN", (0, 1), (-1, 2), "BOTTOM"),
        ("LINEBELOW", (0, 2), (-1, 2), 0.8, GRID_LINE),
        ("TOPPADDING", (0, 2), (-1, 2), 0),
        ("BOTTOMPADDING", (0, 2), (-1, 2), 2),
        ("ROWHEIGHTS", (1, 1), (1, 1), 0.55 * cm),
    ]
    t.setStyle(TableStyle(style))
    return t


def build_journal_voucher_pdf(entry, *, requested_by="", approved_by="") -> bytes:
    """Render the journal entry to the EXACT print-view (je_print.html) layout."""
    logo_path = _logo_path()
    company_name = (entry.company.name if entry.company else "") or COMPANY_FALLBACK

    # HEADER block: logo | company + GENERAL JOURNAL VOUCHER | dept/rev info
    logo = None
    if logo_path:
        try:
            logo = Image(logo_path, width=2.5 * cm, height=2.1 * cm)
        except Exception:
            logo = None
    title = [
        Paragraph(
            company_name.upper(),
            ParagraphStyle(
                "coName", fontName="Helvetica-Bold", fontSize=6.8, leading=9,
                alignment=TA_CENTER, textColor=colors.HexColor("#334155"),
            ),
        ),
        Paragraph(
            "GENERAL JOURNAL VOUCHER",
            ParagraphStyle(
                "gJv", fontName="Helvetica-Bold", fontSize=12, leading=15,
                alignment=TA_CENTER, backColor=ORANGE, textColor=BAND_BORDER,
                spaceBefore=2,
            ),
        ),
    ]
    header_data = [[None] * GRID for _ in range(4)]
    header_spans = [
        ("SPAN", (0, 0), (2, 3)),
        ("SPAN", (3, 0), (9, 3)),
        ("SPAN", (10, 0), (13, 0)),
        ("SPAN", (10, 1), (11, 1)),
        ("SPAN", (12, 1), (13, 1)),
        ("SPAN", (10, 2), (11, 2)),
        ("SPAN", (12, 2), (13, 2)),
        ("SPAN", (10, 3), (11, 3)),
        ("SPAN", (12, 3), (13, 3)),
    ]
    header_data[0][0] = logo if logo is not None else ""
    header_data[0][3] = title
    header_data[0][10] = Paragraph("ACCOUNTING DEPARTMENT", _style_bold())
    header_data[1][10] = Paragraph("Document No.:", _style_cell())
    header_data[1][12] = Paragraph(DOCUMENT_NO, _style_cell())
    header_data[2][10] = Paragraph("Effective Date:", _style_cell())
    header_data[2][12] = Paragraph(DOCUMENT_EFFECTIVE, _style_cell())
    header_data[3][10] = Paragraph("Revision No.:", _style_cell())
    header_data[3][12] = Paragraph(DOCUMENT_REVISION, _style_cell())
    header_tbl = Table(header_data, colWidths=[COLW] * GRID)
    header_tbl.setStyle(TableStyle(_base_style() + header_spans))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f"General Journal Voucher {entry.entry_no}",
        author="Accounting System",
    )

    story = [
        header_tbl,
        Spacer(1, 0.15 * cm),
        _band_row("Entry Information"),
        _entry_info_table(entry),
        Spacer(1, 0.15 * cm),
        _band_row("Account Distribution"),
        _distribution_table(entry),
        Spacer(1, 0.25 * cm),
        _signature_table(requested_by, approved_by),
    ]
    doc.build(story)
    return buf.getvalue()


def _bank_account_label(bank) -> str:
    """'CODE — Bank Name (Account Type)', e.g. 'PNB-CHK — PNB (Checking)'."""
    name = bank.bank_name or bank.name
    return f"{bank.code} — {name} ({bank.get_account_type_display()})"


def _ftv_doc_info_table(voucher_no, transfer_type, date_label, prepared_by):
    """DOCUMENT INFORMATION — two rows of label/value pairs, 14-col grid."""
    cell = _style_cell()
    bold = _style_bold()
    data = [[None] * GRID for _ in range(2)]

    data[0][0] = Paragraph("VOUCHER REF #:", bold)
    data[0][3] = Paragraph(voucher_no or "-", bold)
    data[0][7] = Paragraph("DATE:", bold)
    data[0][10] = Paragraph(date_label or "-", cell)

    data[1][0] = Paragraph("TRANSFER TYPE:", bold)
    data[1][3] = Paragraph(transfer_type or "-", cell)
    data[1][7] = Paragraph("PREPARED BY:", bold)
    data[1][10] = Paragraph(prepared_by or "-", cell)

    spans = [
        ("SPAN", (0, 0), (2, 0)), ("SPAN", (3, 0), (6, 0)),
        ("SPAN", (7, 0), (9, 0)), ("SPAN", (10, 0), (13, 0)),
        ("SPAN", (0, 1), (2, 1)), ("SPAN", (3, 1), (6, 1)),
        ("SPAN", (7, 1), (9, 1)), ("SPAN", (10, 1), (13, 1)),
    ]
    t = Table(data, colWidths=[COLW] * GRID)
    t.setStyle(TableStyle(_base_style() + spans))
    return t


def _ftv_transfer_details_table(transfer):
    """SOURCE / DESTINATION / AMOUNT / PURPOSE rows (TRANSFER DETAILS)."""
    cell = _style_cell()
    bold = _style_bold()
    bold_right = _style_bold_right()
    rows = 4
    data = [[None] * GRID for _ in range(rows)]

    data[0][0] = Paragraph("SOURCE (FROM / CREDIT):", bold)
    data[0][3] = Paragraph(_bank_account_label(transfer.from_account), cell)
    data[1][0] = Paragraph("DESTINATION (TO / DEBIT):", bold)
    data[1][3] = Paragraph(_bank_account_label(transfer.to_account), cell)
    data[2][0] = Paragraph("TRANSFER AMOUNT:", bold)
    data[2][3] = Paragraph(f"₱{_money(transfer.amount)}", bold_right)
    data[3][0] = Paragraph("PURPOSE / PARTICULAR:", bold)
    data[3][3] = Paragraph(transfer.purpose or "-", cell)

    spans = [
        ("SPAN", (0, r), (2, r))
        for r in range(rows)
    ] + [
        ("SPAN", (3, r), (13, r))
        for r in range(rows)
    ]
    t = Table(data, colWidths=[COLW] * GRID)
    t.setStyle(TableStyle(_base_style() + spans))
    return t


def _ftv_distribution_table(entry, fallback_amount):
    """ACCOUNT DISTRIBUTION — COA | Account Name | Particulars | Debit | Credit.

    Fixed column widths (Paragraph cells wrap long text inside their own
    column); the header repeats on every page when lines span pages.
    """
    cell = _style_cell()
    cell_right = _style_cell_right()
    bold = _style_bold()
    bold_right = _style_bold_right()

    header = [
        Paragraph("COA", _style_hdr()),
        Paragraph("Account Name", _style_hdr()),
        Paragraph("Particulars", _style_hdr()),
        Paragraph("Debit", _style_hdr_right()),
        Paragraph("Credit", _style_hdr_right()),
    ]
    rows = [header]
    debit_total = fallback_amount
    credit_total = fallback_amount
    if entry is not None:
        debit_total = entry.total_debit
        credit_total = entry.total_credit
        for line in entry.lines.order_by("line_no"):
            rows.append(
                [
                    Paragraph(line.account.code, cell),
                    Paragraph(line.account.name, cell),
                    Paragraph(line.description or "-", cell),
                    Paragraph(_money(line.debit), cell_right),
                    Paragraph(_money(line.credit), cell_right),
                ]
            )
    totals = [
        Paragraph("TOTALS", bold),
        "", "",
        Paragraph(_money(debit_total), bold_right),
        Paragraph(_money(credit_total), bold_right),
    ]
    rows.append(totals)

    grid = Table(
        rows,
        colWidths=[c * cm for c in (2.8, 4.6, 4.4, 2.4, 2.4)],
        repeatRows=1,
        splitByRow=1,
    )
    style = _base_style()
    style += [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, -1), (-1, -1), ORANGE),
        ("SPAN", (0, -1), (2, -1)),
        ("ALIGN", (3, -1), (4, -1), "RIGHT"),
    ]
    grid.setStyle(TableStyle(style))
    return grid


def _ftv_reference_table(reference):
    """REFERENCE / ATTACHMENTS — reference value + printable checklist."""
    cell = _style_cell()
    bold = _style_bold()
    data = [[None] * GRID for _ in range(2)]
    data[0][0] = Paragraph("REFERENCE:", bold)
    data[0][3] = Paragraph(reference or "-", cell)
    data[1][0] = Paragraph(
        "☐ Bank Transfer Slip    ☐ Online Banking Advice    ☐ Deposit Slip", cell
    )
    spans = [
        ("SPAN", (0, 0), (2, 0)),
        ("SPAN", (3, 0), (13, 0)),
        ("SPAN", (0, 1), (13, 1)),
    ]
    t = Table(data, colWidths=[COLW] * GRID)
    t.setStyle(TableStyle(_base_style() + spans))
    return t


def _ftv_signature_table(prepared_by, checked_by, approved_by):
    """PREPARED / CHECKED / APPROVED three-column signature block."""
    bold = _style_bold()
    signame = _style_signame()
    sigrole = _style_sigrole()
    data = [
        [Paragraph("Prepared By:", bold), Paragraph("Checked By:", bold),
         Paragraph("Approved By:", bold)],
        ["", "", ""],  # empty signature lines
        [Paragraph(prepared_by or "", signame), Paragraph(checked_by or "", signame),
         Paragraph(approved_by or "", signame)],
        [Paragraph("Signature over Printed Name", sigrole)] * 3,
    ]
    t = Table(data, colWidths=[5 * COLW, 4 * COLW, 5 * COLW])
    style = _base_style()
    style += [
        ("ALIGN", (0, -2), (-1, -2), "CENTER"),
        ("VALIGN", (0, 1), (-1, 2), "BOTTOM"),
        ("LINEBELOW", (0, 2), (-1, 2), 0.8, GRID_LINE),
        ("TOPPADDING", (0, 2), (-1, 2), 0),
        ("BOTTOMPADDING", (0, 2), (-1, 2), 2),
        ("ROWHEIGHTS", (1, 1), (1, 1), 0.55 * cm),
    ]
    t.setStyle(TableStyle(style))
    return t


def build_fund_transfer_voucher_pdf(
    transfer,
    *,
    voucher_no="",
    transfer_type="",
    date_label="",
    prepared_by="",
    checked_by="",
    approved_by="",
) -> bytes:
    """Render the Fund Transfer Voucher to the ftv_print.html layout.

    Same document grid, section bands and fixed column widths as the browser
    print view; real vector/text output (selectable text, embedded logo),
    repeating distribution header and safe page splits on multi-page output.
    """
    company = transfer.from_account.company
    company_name = (company.name if company else "") or COMPANY_FALLBACK

    logo_path = _logo_path()
    logo = None
    if logo_path:
        try:
            logo = Image(logo_path, width=2.5 * cm, height=2.1 * cm)
        except Exception:
            logo = None

    title = [
        Paragraph(
            company_name.upper(),
            ParagraphStyle(
                "coName", fontName="Helvetica-Bold", fontSize=6.8, leading=9,
                alignment=TA_CENTER, textColor=colors.HexColor("#334155"),
            ),
        ),
        Paragraph(
            "FUND TRANSFER VOUCHER (FTV)",
            ParagraphStyle(
                "fTV", fontName="Helvetica-Bold", fontSize=12, leading=15,
                alignment=TA_CENTER, backColor=ORANGE, textColor=BAND_BORDER,
                spaceBefore=2,
            ),
        ),
    ]
    header_data = [[None] * GRID for _ in range(3)]
    header_spans = [
        ("SPAN", (0, 0), (2, 2)),
        ("SPAN", (3, 0), (13, 2)),
    ]
    header_data[0][0] = logo if logo is not None else ""
    header_data[0][3] = title
    header_tbl = Table(header_data, colWidths=[COLW] * GRID)
    header_tbl.setStyle(TableStyle(_base_style() + header_spans))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f"Fund Transfer Voucher {voucher_no or transfer.id}",
        author="Accounting System",
    )

    story = [
        header_tbl,
        Spacer(1, 0.15 * cm),
        _ftv_doc_info_table(voucher_no, transfer_type, date_label, prepared_by),
        Spacer(1, 0.15 * cm),
        _band_row("Transfer Details"),
        _ftv_transfer_details_table(transfer),
        Spacer(1, 0.15 * cm),
        _band_row("Account Distribution"),
        _ftv_distribution_table(transfer.journal_entry, transfer.amount),
        Spacer(1, 0.15 * cm),
        _band_row("Reference / Attachments"),
        _ftv_reference_table(transfer.reference),
        Spacer(1, 0.25 * cm),
        _ftv_signature_table(prepared_by, checked_by, approved_by),
    ]
    doc.build(story)
    return buf.getvalue()