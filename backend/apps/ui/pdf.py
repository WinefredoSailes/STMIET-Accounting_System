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
from reportlab.lib.pagesizes import A4, A5, landscape
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


# ---------------------------------------------------------------------------
# Request for Payment (ACCTG-FOR-012) + Check Voucher (ACCTG-FOR-010) + PCF.
# The voucher forms reproduce the *_print.html layouts on A5/A4; the PCF
# workpaper is the A4-landscape 23-column summary.
# ---------------------------------------------------------------------------

GREEN = colors.HexColor("#e2efda")


def _signatory_name(user):
    from apps.core.approvals import signatory_name

    if user is None:
        return ""
    return signatory_name(user)


def _t(value):
    """Font-safe text: base-14 Helvetica cannot render the em dash glyph."""
    return str(value).replace("—", "-")


def _form_header(colw, company_name, title_text, band_color, doc_no, doc_effective, doc_revision):
    """Generic form header (logo | title band | dept + doc meta rows), 14-col grid."""
    bold = _style_bold()
    title = [
        Paragraph(
            company_name.upper(),
            ParagraphStyle(
                "coName", fontName="Helvetica-Bold", fontSize=6.8, leading=9,
                alignment=TA_CENTER, textColor=colors.HexColor("#334155"),
            ),
        ),
        Paragraph(
            title_text,
            ParagraphStyle(
                "formTitle", fontName="Helvetica-Bold", fontSize=12, leading=15,
                alignment=TA_CENTER, backColor=band_color, textColor=BAND_BORDER,
                spaceBefore=2,
            ),
        ),
    ]
    data = [[None] * GRID for _ in range(4)]
    spans = [
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
    logo_path = _logo_path()
    logo = None
    if logo_path:
        try:
            logo = Image(logo_path, width=2.2 * cm, height=1.9 * cm)
        except Exception:
            logo = None
    data[0][0] = logo if logo is not None else ""
    data[0][3] = title
    data[0][10] = Paragraph("ACCOUNTING DEPARTMENT", bold)
    data[1][10] = Paragraph("Document No.:", _style_cell())
    data[1][12] = Paragraph(doc_no, _style_cell())
    data[2][10] = Paragraph("Effective Date:", _style_cell())
    data[2][12] = Paragraph(doc_effective, _style_cell())
    data[3][10] = Paragraph("Revision No.:", _style_cell())
    data[3][12] = Paragraph(doc_revision, _style_cell())
    t = Table(data, colWidths=[colw] * GRID)
    t.setStyle(TableStyle(_base_style() + spans))
    return t


def _band_row_custom(colw, text, color=ORANGE):
    p = Paragraph(text, _style_band())
    t = Table([[p]], colWidths=[colw * GRID])
    t.setStyle(TableStyle(_base_style() + [("BACKGROUND", (0, 0), (-1, -1), color)]))
    return t


def _payee_table(colw, fields):
    """labels/values grid — two label+value pairs per row, 14-col grid."""
    cell = _style_cell()
    bold = _style_bold()
    data = [[None] * GRID for _ in fields]
    spans = []
    for r, (l1, v1, l2, v2) in enumerate(fields):
        data[r][0] = Paragraph(l1, bold)
        data[r][3] = Paragraph(_t(v1), cell)
        data[r][7] = Paragraph(l2, bold)
        data[r][10] = Paragraph(_t(v2), cell)
        spans += [
            ("SPAN", (0, r), (2, r)),
            ("SPAN", (3, r), (6, r)),
            ("SPAN", (7, r), (9, r)),
            ("SPAN", (10, r), (13, r)),
        ]
    t = Table(data, colWidths=[colw] * GRID)
    t.setStyle(TableStyle(_base_style() + spans))
    return t


def _rfp_distribution_table(colw, dr_lines, rfp):
    """Purpose of Payment | Segment | Cost Center | Amount (7/2/2/3 of 14)."""
    cell = _style_cell()
    cell_right = _style_cell_right()
    header = [
        Paragraph("Purpose of Payment", _style_hdr()),
        Paragraph("Segment", _style_hdr()),
        Paragraph("Cost Center", _style_hdr()),
        Paragraph("Amount", _style_hdr_right()),
    ]
    rows = [header]
    for line in dr_lines:
        rows.append(
            [
                Paragraph(_t(line.description or rfp.particulars), cell),
                Paragraph(_t(line.segment.code), cell),
                Paragraph(_t(line.cost_center or ""), cell),
                Paragraph(_money(line.amount), cell_right),
            ]
        )
    if not dr_lines:
        rows.append([Paragraph("No distribution lines.", cell), "", "", ""])
    grid = Table(rows, colWidths=[c * colw for c in (7, 2, 2, 3)], repeatRows=1)
    grid.setStyle(TableStyle(
        _base_style() + [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0"))]
    ))
    return grid


def _rfp_coa_table(colw, lines, total):
    """CHART OF ACCOUNTS — Dr./Cr. sides, VAT and Net Invoice rows."""
    cell = _style_cell()
    cell_right = _style_cell_right()
    bold = _style_bold()
    bold_right = _style_bold_right()
    data = [[None] * GRID for _ in range(3 + len(lines))]
    spans = []

    data[0][0] = Paragraph("CHART OF ACCOUNTS:", bold)
    data[0][9] = Paragraph("Total Amount:", bold)
    data[0][12] = Paragraph(_money(total), bold_right)

    for r, line in enumerate(lines, start=1):
        data[r][0] = Paragraph(f"{line.side.upper()}.", bold)
        data[r][3] = Paragraph(_t(line.account.name), cell)
        data[r][12] = Paragraph(_money(line.amount), cell_right)

    last = 1 + len(lines)
    data[last][9] = Paragraph("VAT:", cell)
    data[last][12] = Paragraph(_money(0), cell_right)
    data[last + 1][9] = Paragraph("Net Invoice:", bold)
    data[last + 1][12] = Paragraph(_money(total), bold_right)

    spans = [
        ("SPAN", (0, 0), (2, 0)), ("SPAN", (3, 0), (8, 0)),
        ("SPAN", (9, 0), (11, 0)), ("SPAN", (12, 0), (13, 0)),
    ]
    for r in range(1, last):
        spans += [
            ("SPAN", (0, r), (2, r)), ("SPAN", (3, r), (8, r)),
            ("SPAN", (9, r), (11, r)), ("SPAN", (12, r), (13, r)),
        ]
    for r in (last, last + 1):
        spans += [
            ("SPAN", (0, r), (8, r)), ("SPAN", (9, r), (11, r)),
            ("SPAN", (12, r), (13, r)),
        ]
    t = Table(data, colWidths=[colw] * GRID)
    t.setStyle(TableStyle(_base_style() + spans))
    return t


def _signature_block(colw, groups, widths):
    """Groups: (label, name, role) — bottom 'line' sits under the names row."""
    bold = _style_bold()
    signame = _style_signame()
    sigrole = _style_sigrole()
    data = [
        [Paragraph(label.upper(), bold) for label, _, _ in groups],
        [""] * len(groups),
        [Paragraph(_t(name), signame) for _, name, _ in groups],
        [Paragraph(role, sigrole) for _, _, role in groups],
    ]
    t = Table(data, colWidths=[(w * colw) for w in widths])
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


def _form_doc(margin, pagesize, title, **kwargs):
    return SimpleDocTemplate(
        io.BytesIO(),
        pagesize=pagesize,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=title,
        author="Accounting System",
        **kwargs,
    )


def build_rfp_pdf(rfp, *, paper="a5") -> bytes:
    """RFP form (ACCTG-FOR-012) reproduced from rfp_print.html.

    `paper` is "a5" (default, half-bond) or "a4" — matching the print toolbar.
    """
    from apps.ap.models import RFPDocument
    from apps.foundation.models import Segment

    rfp = rfp if isinstance(rfp, RFPDocument) else RFPDocument.objects.get(pk=int(rfp))
    lines = list(rfp.lines.select_related("account", "segment").order_by("line_no"))
    dr_lines = [line for line in lines if line.side == "dr"]
    total = sum((line.amount for line in dr_lines), Decimal("0.00")) or rfp.amount

    pagesize = A4 if paper == "a4" else A5
    margin = 0.9 * cm
    colw = (pagesize[0] - 2 * margin) / GRID
    company = rfp.segment.company if rfp.segment else None
    company_name = (company.name if company else "") or COMPANY_FALLBACK

    story = [
        _form_header(colw, company_name, "REQUEST FOR PAYMENT", ORANGE,
                     "ACCTG-FOR-012", "11.16.2024", "00"),
        Spacer(1, 0.15 * cm),
        _band_row_custom(colw, "Payee Information"),
        _payee_table(colw, [
            ("NAME:", rfp.payee.name, "DATE OF REQUEST:", rfp.rfp_date.strftime("%m/%d/%Y")),
            ("POSITION:", rfp.payee.position or rfp.payee.contact_no or "",
             "VENDOR NO:", rfp.payee.code),
            ("DEPARTMENT/ADDRESS:", rfp.payee.address
             or f"{rfp.segment.name} ({rfp.segment.code})", "AP NO:", rfp.ap_number),
        ]),
        Spacer(1, 0.15 * cm),
        _band_row_custom(colw, "Distribution Charges"),
        _rfp_distribution_table(colw, dr_lines, rfp),
        Spacer(1, 0.15 * cm),
        _band_row_custom(colw, "Chart of Accounts"),
        _rfp_coa_table(colw, lines, total),
        Spacer(1, 0.25 * cm),
        _signature_block(
            colw,
            [
                ("Requested By:", _signatory_name(rfp.created_by), "Print Name/Sign/Date"),
                ("Recommending Approver / or Checker", _signatory_name(rfp.checked_by), "Department Head"),
                ("Accounting Manager", _signatory_name(rfp.approved_by_acctg), "Accounting Manager"),
                ("Finance Manager", _signatory_name(rfp.approved_by_fin), "Finance Manager"),
            ],
            [3, 5, 3, 3],
        ),
    ]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=pagesize, leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin,
        title=f"Request for Payment {rfp.ap_number}", author="Accounting System",
    )
    doc.build(story)
    return buf.getvalue()


def _coo_name():
    from apps.core.approvals import role_assignee

    return role_assignee("coo")


def build_cv_pdf(cv, *, paper="a5") -> bytes:
    """Check Voucher (ACCTG-FOR-010) reproduced from cv_print.html.

    `paper` is "a5" (default, half-bond) or "a4".
    """
    from apps.ap.models import CheckVoucher

    cv = cv if isinstance(cv, CheckVoucher) else CheckVoucher.objects.get(pk=int(cv))
    rfp = getattr(cv, "rfp", None)
    lines = list(rfp.lines.select_related("account", "segment")) if rfp else []
    dr_lines = [line for line in lines if line.side == "dr"]
    total = sum((line.amount for line in dr_lines), Decimal("0.00"))
    position = cv.payee.position or cv.payee.get_supplier_type_display()
    date_of_request = (rfp.rfp_date if rfp and rfp.rfp_date else cv.cv_date) if rfp else cv.cv_date

    pagesize = A4 if paper == "a4" else A5
    margin = 0.9 * cm
    colw = (pagesize[0] - 2 * margin) / GRID
    company = None
    if rfp and rfp.segment and rfp.segment.company:
        company = rfp.segment.company
    elif cv.payee.default_segment and cv.payee.default_segment.company:
        company = cv.payee.default_segment.company
    company_name = (company.name if company else "") or COMPANY_FALLBACK

    # Distribution Charges — Purpose | Segment | Cost Center | GL Account | Amount
    cell = _style_cell()
    cell_right = _style_cell_right()
    dist_rows = [
        [
            Paragraph("Purpose of Payment", _style_hdr()),
            Paragraph("Segment", _style_hdr()),
            Paragraph("Cost Center", _style_hdr()),
            Paragraph("GL Account", _style_hdr()),
            Paragraph("Amount", _style_hdr_right()),
        ]
    ]
    for line in dr_lines:
        dist_rows.append(
            [
                Paragraph(_t(line.description or (rfp.particulars if rfp else "")), cell),
                Paragraph(_t(line.segment.code), cell),
                Paragraph(_t(rfp.purpose if rfp else ""), cell),
                Paragraph(_t(line.account.code), cell),
                Paragraph(_money(line.amount), cell_right),
            ]
        )
    if not dr_lines:
        dist_rows.append([Paragraph("No distribution lines.", cell), "", "", "", ""])
    dist_tbl = Table(dist_rows, colWidths=[c * colw for c in (5, 2, 2, 2, 3)], repeatRows=1)
    dist_tbl.setStyle(TableStyle(_base_style() + [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0"))
    ]))

    # TOTAL / REMARKS row + disclaimer
    remarks = f"Other Remarks: See attached RFP {rfp.ap_number}" if rfp else "Other Remarks:"
    total_data = [[None] * GRID]
    total_data[0][0] = Paragraph(remarks, _style_cell())
    total_data[0][9] = Paragraph("Total Amount", _style_bold())
    total_data[0][12] = Paragraph(_money(total), _style_bold_right())
    total_tbl = Table(total_data, colWidths=[colw] * GRID)
    total_tbl.setStyle(TableStyle(_base_style() + [
        ("SPAN", (0, 0), (8, 0)), ("SPAN", (9, 0), (11, 0)), ("SPAN", (12, 0), (13, 0))
    ]))

    disclaimer = Table(
        [[Paragraph(
            "Each check issued shall be supported with sufficient documentation. "
            "Failure to do so shall constitute neglect to the requester and/or the department.",
            ParagraphStyle("dis", fontName="Helvetica-Oblique", fontSize=7.5, leading=9.5),
        )]],
        colWidths=[colw * GRID],
    )
    disclaimer.setStyle(TableStyle(_base_style()))

    story = [
        _form_header(colw, company_name, "CHECK VOUCHER", GREEN,
                     "ACCTG-FOR-010", "08.18.2022", "02"),
        Spacer(1, 0.15 * cm),
        _band_row_custom(colw, "Payee Information", GREEN),
        _payee_table(colw, [
            ("NAME:", cv.payee.name, "DATE OF REQUEST:", date_of_request.strftime("%m/%d/%Y")),
            ("POSITION:", position, "CHECK ISSUED & NO.:", cv.check_no or ""),
        ]),
        Spacer(1, 0.15 * cm),
        _band_row_custom(colw, "Distribution Charges", GREEN),
        dist_tbl,
        Spacer(1, 0.15 * cm),
        total_tbl,
        disclaimer,
        Spacer(1, 0.25 * cm),
        _signature_block(
            colw,
            [
                ("Prepared By:", _signatory_name(cv.created_by), "Print Name/Sign/Date"),
                ("Requested By:", _signatory_name(rfp.created_by) if rfp else "",
                 "Print Name/Sign/Date"),
                ("Checked By:", _signatory_name(rfp.checked_by) if rfp
                 else _signatory_name(cv.approved_by), "Finance & Acctg. Head / Sign and Date"),
                ("Approved By:", _coo_name(), "COO"),
                ("Payment Received By:", cv.payee.name, "Signature Over Printed Name/Date"),
            ],
            [3, 3, 3, 3, 2],
        ),
    ]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=pagesize, leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin,
        title=f"Check Voucher {cv.cv_number}", author="Accounting System",
    )
    doc.build(story)
    return buf.getvalue()


_PCF_COL_WIDTHS = [
    0.5, 0.8, 2.6, 0.6, 1.1, 1.2, 2.8, 1.2, 1.1, 1.1, 3.2,
    1.1, 1.1, 0.6, 0.9, 1.1, 1.1, 1.1, 1.1, 0.9, 0.9, 0.9, 0.7,
]
_PCF_COL_HEADERS = [
    "Type", "DATE", "Vendor/Customer", "REF.", "TIN", "Address", "REMARKS",
    "BUSINESS SEGMENT", "COST CENTER", "COA", "Account Titles",
    "Dr.", "Cr.", "VAT", "Segment", "Classification", "Category", "Sub-Accounts",
    "Major Accounts", "Behavior", "Traceability", "Controllability", "AP NO",
]


def _pcf_cell(text, right=False, bold=False):
    style = ParagraphStyle(
        "pcf" + ("B" if bold else "") + ("R" if right else ""),
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=5.5, leading=7,
        alignment=TA_RIGHT if right else TA_LEFT,
    )
    return Paragraph(_t(text), style)


def _pcf_header_cell(text):
    return Paragraph(
        text,
        ParagraphStyle("pcfHdr", fontName="Helvetica-Bold", fontSize=5, leading=6.5),
    )


def build_pcf_replenishment_pdf(replen, *, rows=None, total=None, fund_label=None, custodian_label=None) -> bytes:
    """Petty Cash Replenishment workpaper (A4 landscape, 23 columns).

    Mirrors pcf_replenishment_print.html — quirk kept: the totals row spans
    columns 0-11 and puts the total under the Cr. column (col 12).
    """
    from apps.cash.models import PCFReplenishment
    from apps.foundation.models import Account

    replen = replen if isinstance(replen, PCFReplenishment) else PCFReplenishment.objects.get(pk=int(replen))
    if rows is None:
        rows = []
        for exp in replen.expenses or []:
            acct = Account.objects.filter(code=exp.get("account_code", "")).first()
            rows.append({
                "coa": exp.get("account_code", ""),
                "title": acct.name if acct else exp.get("account_code", ""),
                "dr": exp.get("amount", 0),
                "cr": exp.get("amount", 0),
                "side": str(exp.get("side", "dr")).lower(),
                "segment": exp.get("segment", ""),
                "cost_center": exp.get("cost_center", ""),
                "remarks": exp.get("description", ""),
                "business_name": exp.get("business_name", ""),
                "tin": exp.get("tin", ""),
                "classification": acct.classification if acct else "",
                "category": acct.category if acct else "",
                "sub_accounts": acct.sub_accounts if acct else "",
                "major_accounts": acct.major_accounts if acct else "",
                "behavior": acct.behavior if acct else "",
                "traceability": acct.traceability if acct else "",
                "controllability": acct.controllability if acct else "",
            })
    if total is None:
        total = sum((Decimal(str(row["dr"])) for row in rows), Decimal("0.00"))
    if fund_label is None:
        fund_label = replen.fund.name or replen.fund.fund_code
    if custodian_label is None:
        custodian = replen.fund.custodian
        custodian_label = (custodian.get_full_name() or custodian.username) if custodian else "-"

    header_row = [_pcf_header_cell(h) for h in _PCF_COL_HEADERS]
    table_rows = [header_row]
    for row in rows:
        money_right = (not row["side"] == "cr")
        table_rows.append([
            _pcf_cell(""), _pcf_cell(""), _pcf_cell(row["business_name"]), _pcf_cell(""),
            _pcf_cell(row["tin"]), _pcf_cell(""), _pcf_cell(row["remarks"]),
            _pcf_cell(row["segment"] or fund_label), _pcf_cell(row["cost_center"]),
            _pcf_cell(row["coa"]), _pcf_cell(row["title"]),
            _pcf_cell(_money(row["dr"]) if money_right else "", right=True, bold=True),
            _pcf_cell(_money(row["cr"]) if row["side"] == "cr" else "", right=True, bold=True),
            _pcf_cell("", right=True),
            _pcf_cell(row["segment"]), _pcf_cell(row["classification"]),
            _pcf_cell(row["category"]), _pcf_cell(row["sub_accounts"]),
            _pcf_cell(row["major_accounts"]), _pcf_cell(row["behavior"]),
            _pcf_cell(row["traceability"]), _pcf_cell(row["controllability"]), _pcf_cell(""),
        ])
    if not table_rows:
        table_rows.append([_pcf_cell("No expense lines.")] + [_pcf_cell("")] * 22)

    grand = [_pcf_cell("")] * 23
    grand[0] = _pcf_cell("Total", bold=True)
    grand[12] = _pcf_cell(_money(total), right=True, bold=True)
    table_rows.append(grand)

    grid = Table(table_rows, colWidths=[w * cm for w in _PCF_COL_WIDTHS], repeatRows=1)
    style = _base_style()
    style += [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, -1), (-1, -1), ORANGE),
        ("SPAN", (0, -1), (11, -1)),
        ("ALIGN", (12, -1), (12, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]
    grid.setStyle(TableStyle(style))

    title = Paragraph(
        "PETTY CASH REPLENISHMENT",
        ParagraphStyle("pcfTitle", fontName="Helvetica-Bold", fontSize=11, leading=14, alignment=TA_CENTER),
    )
    subtitle = Paragraph(
        f"{_t(fund_label)} · Custodian: {_t(custodian_label)} · "
        f"{replen.request_date.strftime('%b %d, %Y')} · Total ₱{_money(total)}"
        + (f" · Voucher: {_t(replen.voucher_no)}" if replen.voucher_no else ""),
        ParagraphStyle("pcfSub", fontName="Helvetica", fontSize=7, leading=9, alignment=TA_CENTER),
    )
    margin = 0.8 * cm
    story = [title, Paragraph("&nbsp;", ParagraphStyle("s", fontSize=1, leading=2)), subtitle]
    story.extend([Spacer(1, 0.35 * cm), grid])
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4), leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin,
        title=f"Petty Cash Replenishment {replen.voucher_no or replen.id}", author="Accounting System",
    )
    doc.build(story)
    return buf.getvalue()