"""CSV / PDF / XLSX export of the six financial statements (and Trial Balance).

Each builder produces plain‑data output (no workbook styling for CSV,
and a minimal table for PDF via reportlab) that mirrors the screen layout.
The XLSX builders are the existing openpyxl ones in reporting.excel_export.

Formats are selected via ?format=xlsx|csv|pdf on the export URLs.
"""

from decimal import Decimal
from io import BytesIO, StringIO

from django.http import HttpResponse

COMPANY_NAME = "SEVEN-TRENT MACHINERIES INDUSTRIAL EQUIPMENT TRADING"


def csv_response(rows, filename: str, header: list[str] | None = None) -> HttpResponse:
    """Build an HTTP response with a CSV attachment."""
    buffer = StringIO()
    writer = csv.writer(buffer)
    if header:
        writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    response = HttpResponse(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def pdf_response(
    title: str,
    column_labels: list[str],
    data: list[list],
    filename: str,
) -> HttpResponse:
    """Build an HTTP response with a PDF attachment via reportlab.

    data: list of rows, each row is a list of cell values (strings/Decimals).
    column_labels: list of column header strings.
    """
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
    from reportlab.lib import colors

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER, leftMargin=0.6*inch, rightMargin=0.6*inch, topMargin=0.6*inch, bottomMargin=0.6*inch)
    elements = []

    table = Table([column_labels] + data, colWidths=[2.5*inch] * len(column_labels))
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f0f0")]),
            ]
        )
    )
    elements.append(table)
    doc.build(elements)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _money_vals(values: list) -> list[str]:
    """Format a list of Decimal values as money strings (2dp, thousand sep)."""
    return [f"{Decimal(v):,.2f}" if v is not None else "" for v in values]