"""Generic table export engine — one ``TableSpec`` renders to XLSX / CSV / PDF
identically so the three download formats can never diverge.

The engine is the single source of truth for every tabular export (registers,
lists, workpapers, statements). Column widths and alignment are declared once
in the spec, which also fixes the old defect where fixed ~2.5in columns
overwhelmed multi-column tables.

reporting.exports.csv_response/pdf_response remain as back-compatible thin
wrappers over this module.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from typing import Optional

from django.http import HttpResponse

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, LETTER, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle


class Align:
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    CENTER = "CENTER"


@dataclass(frozen=True)
class Column:
    label: str
    width_cm: Optional[float] = None  # None → share remaining width evenly
    align: str = Align.LEFT
    money: bool = False  # right-aligned tabular money; numeric cells in xlsx


@dataclass
class TableSpec:
    columns: list[Column]
    rows: list[list] = field(default_factory=list)
    title: str = ""
    preamble: list = field(default_factory=list)  # meta label/value rows
    totals_row: Optional[list] = None
    notes: list[str] = field(default_factory=list)
    page: str = "landscape"  # landscape | portrait
    sheet_title: str = "SHEET"


def _money(value) -> str:
    try:
        return f"{Decimal(value):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return "0.00"


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def csv_spec_response(spec: TableSpec, filename: str) -> HttpResponse:
    buffer = StringIO()
    writer = csv_writer(buffer)
    for row in spec.preamble:
        writer.writerow([_to_text(v) for v in row])
    if spec.columns:
        writer.writerow([c.label for c in spec.columns])
    if not spec.rows and spec.totals_row is None:
        writer.writerow(["No data."])
    for row in spec.rows:
        writer.writerow([_to_text(v) for v in row])
    if spec.totals_row is not None:
        writer.writerow([_to_text(v) for v in spec.totals_row])
    for note in spec.notes:
        writer.writerow([note])
    response = HttpResponse(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def csv_writer(buffer):
    import csv

    return csv.writer(buffer)


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------


def xlsx_spec_response(spec: TableSpec, filename: str, filename_fallback: str = "") -> HttpResponse:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = (spec.sheet_title or "SHEET")[:31]

    ncols = len(spec.columns)
    if spec.title:
        ws.append([spec.title])
        if ncols:
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
        ws.cell(row=1, column=1).font = Font(bold=True, size=12)
    row_no = 2 if spec.title else 1

    for r in spec.preamble:
        ws.append([_to_text(v) for v in r])
        row_no += 1

    header_row = row_no
    ws.append([c.label for c in spec.columns])
    for cell in ws[header_row]:
        cell.font = Font(bold=True)
    row_no += 1

    if not spec.rows and spec.totals_row is None:
        ws.append(["No data."])
        row_no += 1

    for row in spec.rows:
        _write_xlsx_row(ws, row, spec)
        row_no += 1

    if spec.totals_row is not None:
        _write_xlsx_row(ws, spec.totals_row, spec, bold=True)
        row_no += 1

    from openpyxl.utils import get_column_letter

    for i, col in enumerate(spec.columns, start=1):
        if col.width_cm:
            ws.column_dimensions[get_column_letter(i)].width = int(col.width_cm * 4.5)

    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


def _write_xlsx_row(ws, row, spec: TableSpec, bold=False):
    from openpyxl.styles import Font

    cells = []
    target_row = ws.max_row + 1
    for i, value in enumerate(row):
        cell = ws.cell(row=target_row, column=i + 1)
        col = spec.columns[i] if i < len(spec.columns) else None
        if col and col.money and value not in (None, ""):
            try:
                cell.value = Decimal(value)
            except (InvalidOperation, TypeError, ValueError):
                cell.value = _to_text(value)
            if isinstance(cell.value, Decimal):
                cell.number_format = "#,##0.00"
        elif value is None:
            cell.value = ""
        else:
            cell.value = _to_text(value)
        if bold:
            cell.font = Font(bold=True)
        cells.append(cell)
    return cells


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def pdf_spec_response(spec: TableSpec, filename: str) -> HttpResponse:
    from io import BytesIO

    page_w, page_h = landscape(LETTER) if spec.page == "landscape" else A4
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=(page_w, page_h),
        leftMargin=1 * cm,
        rightMargin=1 * cm,
        topMargin=0.8 * cm,
        bottomMargin=0.8 * cm,
    )
    usable_w = (page_w - 2 * cm) / cm  # in cm units for the width arithmetic
    story = _pdf_story(spec, usable_w)
    doc.build(story)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _pdf_story(spec: TableSpec, usable_cm: float) -> list:
    from reportlab.platypus import Paragraph

    style_body = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=7.5, leading=9.5,
    )
    style_body_right = ParagraphStyle(
        "bodyR", parent=style_body, alignment=TA_RIGHT,
    )
    style_cell = ParagraphStyle(
        "cell", fontName="Helvetica", fontSize=7, leading=9,
    )
    style_cell_right = ParagraphStyle(
        "cellR", parent=style_cell, alignment=TA_RIGHT,
    )
    style_hdr = ParagraphStyle(
        "hdr", fontName="Helvetica-Bold", fontSize=7, leading=9,
    )
    style_hdr_right = ParagraphStyle(
        "hdrR", parent=style_hdr, alignment=TA_RIGHT,
    )
    style_title = ParagraphStyle(
        "title", fontName="Helvetica-Bold", fontSize=12, leading=15,
    )

    story = []
    if spec.title:
        story.append(Paragraph(spec.title, style_title))
        story.append(Spacer(1, 0.1 * cm))

    widths = _column_widths(spec, usable_cm)

    header = []
    body_style_map = []
    for i, col in enumerate(spec.columns):
        right = col.align == Align.RIGHT or col.money
        header.append(Paragraph(col.label, style_hdr_right if right else style_hdr))
        body_style_map.append(style_cell_right if right else style_cell)

    rows = [header]
    for row in spec.rows:
        rows.append(_paragraph_cells(row, spec, body_style_map))
    if spec.totals_row is not None:
        rows.append(_paragraph_cells(spec.totals_row, spec, body_style_map, bold=True))

    table = Table(rows, colWidths=[w * cm for w in widths], repeatRows=1, splitByRow=1)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 1), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f0f0")]),
    ]
    if spec.totals_row is not None:
        style.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fce4d6")))
        style.append(("TEXTCOLOR", (0, -1), (-1, -1), colors.black))
    table.setStyle(TableStyle(style))
    story.append(table)

    if spec.notes:
        for note in spec.notes:
            story.append(Spacer(1, 0.1 * cm))
            story.append(Paragraph(note, style_body))
    return story


def _paragraph_cells(row, spec, style_map, bold=False):
    from reportlab.platypus import Paragraph

    bold_cell = ParagraphStyle(
        "b", fontName="Helvetica-Bold", fontSize=7, leading=9,
    )
    bold_cell_right = ParagraphStyle(
        "bR", parent=bold_cell, alignment=TA_RIGHT,
    )
    out = []
    for i, value in enumerate(row):
        style = style_map[i] if i < len(style_map) else None
        if bold:
            style = bold_cell_right if (style and getattr(style, "alignment", None) == TA_RIGHT) else bold_cell
        col = spec.columns[i] if i < len(spec.columns) else None
        if col and col.money and value not in (None, ""):
            text = _money(value)
        elif value is None:
            text = ""
        else:
            text = _to_text(value)
        out.append(Paragraph(text, style or ParagraphStyle("c", fontSize=7)))
    return out


def _column_widths(spec: TableSpec, usable_cm: float) -> list[float]:
    fixed = sum(c.width_cm for c in spec.columns if c.width_cm)
    flex_n = sum(1 for c in spec.columns if not c.width_cm)
    flex = (usable_cm - fixed) / flex_n if flex_n else 0
    return [c.width_cm if c.width_cm is not None else flex for c in spec.columns]


# ---------------------------------------------------------------------------
# Response helper
# ---------------------------------------------------------------------------


def table_export(spec: TableSpec, fmt: str, filename: str) -> HttpResponse:
    """Render a TableSpec to the requested format as a download response.

    fmt is one of "xlsx" | "csv" | "pdf".
    """
    fmt = (fmt or "xlsx").lower()
    if fmt == "csv":
        return csv_spec_response(spec, filename)
    if fmt == "pdf":
        return pdf_spec_response(spec, filename)
    return xlsx_spec_response(spec, filename)