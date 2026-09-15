"""CSV / PDF export wrappers (back-compatible).

Both functions now delegate to the shared table engine (apps.core.exports) so
the statement/register exports render through the same machinery as every
other export in the system. Signatures and observable output (header row for
CSV; portrait PDF table for pdf_response) are unchanged.
"""

from django.http import HttpResponse

from apps.core.exports import (
    Align,
    Column,
    TableSpec,
    csv_spec_response,
    pdf_spec_response,
)


def csv_response(rows, filename: str, header: list[str] | None = None) -> HttpResponse:
    """Build an HTTP response with a CSV attachment."""
    columns = [Column(h) for h in header] if header else []
    spec = TableSpec(columns=columns, rows=[list(r) for r in rows])
    return csv_spec_response(spec, filename)


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
    spec = TableSpec(
        title=title,
        columns=[Column(label, align=Align.RIGHT) for label in column_labels],
        rows=[list(r) for r in data],
        page="portrait",
        sheet_title=title[:31],
    )
    return pdf_spec_response(spec, filename)