"""Fund Transfer Voucher (FTV) print/PDF output tests.

The print/PDF presentation is a separate voucher-style layer; the transfers
HTML form must stay untouched. These tests pin the voucher sections, dynamic
values from the actual transfer data, stable FTV numbering, and real PDF
output (ReportLab, selectable text).
"""

import base64
import re
import zlib

import pytest

from apps.cash.models import BankAccount
from apps.cash.services import TransferService


@pytest.fixture
def banks(db, company, segment, accounts, role_users):
    """Two bank accounts (different banks) + one posted transfer via service."""
    bank_from = BankAccount.objects.create(
        code="1VB-CHK", name="First Valley Bank",
        account_type="checking", bank_name="First Valley Bank", bank_code="1VB",
        gl_account=accounts["10110"], company=company,
    )
    bank_to = BankAccount.objects.create(
        code="PNB-CHK", name="Philippine National Bank",
        account_type="checking", bank_name="Philippine National Bank", bank_code="PNB",
        gl_account=accounts["10010"], company=company,
    )
    transfer = TransferService.transfer(
        from_account=bank_from,
        to_account=bank_to,
        amount="25000.00",
        purpose="Fund transfer to PNB for payroll coverage",
        transfer_date="2026-09-12",
        segment=segment,
        user=role_users["staff"],
    )
    # Voucher layer prints an approved transfer: the preparer submits, head
    # approval posts the JE.
    TransferService.submit(transfer, user=role_users["staff"])
    transfer = TransferService.approve(transfer, user=role_users["head"])
    return bank_from, bank_to, transfer


@pytest.fixture
def named_staff(role_users):
    role_users["staff"].first_name = "Jane"
    role_users["staff"].last_name = "Doe"
    role_users["staff"].save()
    return role_users["staff"]


def _pdf_text(data):
    """Decompress the PDF's content streams -> real selectable text bytes."""
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        try:
            raw = base64.a85decode(m.group(1), adobe=True)
            out.append(zlib.decompress(raw))
        except zlib.error:
            pass
        except ValueError:
            pass
    return b"".join(out)


def test_ftv_print_renders_voucher_sections(client, company, banks, named_staff):
    _, _, transfer = banks
    client.force_login(named_staff)
    resp = client.get(f"/cash/transfers/{transfer.id}/print/")
    assert resp.status_code == 200
    body = resp.content.decode()

    # Header: logo, company name from the transfer, dynamic document title.
    assert "stmiet-trans-logo.png" in body
    assert company.name in body
    assert "FUND TRANSFER VOUCHER (FTV)" in body

    # Document information (dynamic values from the transfer).
    assert "VOUCHER REF #:" in body
    assert "FTV-2026-0001" in body
    assert "TRANSFER TYPE:" in body
    assert "Inter-Bank Transfer" in body
    assert "DATE:" in body
    assert "September 12, 2026" in body
    assert "PREPARED BY:" in body
    assert "Jane Doe" in body

    # Transfer details.
    assert "Transfer Details" in body
    assert "SOURCE (FROM / CREDIT):" in body
    assert "1VB-CHK" in body
    assert "First Valley Bank (Checking)" in body
    assert "DESTINATION (TO / DEBIT):" in body
    assert "PNB-CHK" in body
    assert "Philippine National Bank (Checking)" in body
    assert "TRANSFER AMOUNT:" in body
    assert "₱25,000.00" in body
    assert "PURPOSE / PARTICULAR:" in body
    assert "Fund transfer to PNB for payroll coverage" in body

    # Account distribution from the linked JE (single source of truth).
    assert "Account Distribution" in body
    assert "COA" in body and "Account Name" in body and "Particulars" in body
    assert "10110" in body and "10010" in body
    assert "Fund transfer to PNB for payroll coverage" in body
    assert "TOTALS" in body
    # Totals appear once under Debit and once under Credit (balanced).
    assert body.count("25,000.00") >= 3

    # Reference / attachments.
    assert "Reference / Attachments" in body
    assert "Bank Transfer Slip" in body
    assert "Online Banking Advice" in body
    assert "Deposit Slip" in body

    # Approval section.
    assert "Prepared By:" in body
    assert "Checked By:" in body
    assert "Approved By:" in body
    assert "Signature over Printed Name" in body


def test_ftv_print_intra_bank_transfer_type(client, company, accounts, segment, role_users):
    bank_from = BankAccount.objects.create(
        code="BDO-A", name="BDO Main", account_type="checking",
        bank_name="BDO", bank_code="BDO",
        gl_account=accounts["10110"], company=company,
    )
    bank_to = BankAccount.objects.create(
        code="BDO-B", name="BDO Branch", account_type="checking",
        bank_name="BDO", bank_code="BDO",
        gl_account=accounts["10010"], company=company,
    )
    transfer = TransferService.transfer(
        from_account=bank_from, to_account=bank_to,
        amount="10000.00", purpose="Sweep", transfer_date="2026-09-12",
        segment=segment, user=role_users["staff"],
    )
    client.force_login(role_users["staff"])
    resp = client.get(f"/cash/transfers/{transfer.id}/print/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Intra-Bank Transfer" in body
    assert "Inter-Bank Transfer" not in body


def test_ftv_print_voucher_no_allocated_once_and_stable(client, banks, role_users):
    _, _, transfer = banks
    client.force_login(role_users["staff"])

    # Legacy transfer: no voucher number yet -> print backfills it and keeps it.
    transfer.voucher_no = ""
    transfer.save(update_fields=["voucher_no"])
    first = client.get(f"/cash/transfers/{transfer.id}/print/").content.decode()
    transfer.refresh_from_db()
    allocated = transfer.voucher_no
    assert allocated.startswith("FTV-2026-")
    assert allocated in first

    second = client.get(f"/cash/transfers/{transfer.id}/print/").content.decode()
    transfer.refresh_from_db()
    assert transfer.voucher_no == allocated
    assert second.count(allocated) == first.count(allocated)


def test_ftv_print_long_text_never_moves_columns(client, banks, role_users):
    _, _, transfer = banks
    transfer.purpose = "P" * 500
    transfer.save(update_fields=["purpose"])
    accounts = [transfer.journal_entry.lines.first()]
    acc = accounts[0].account
    acc.name = "Very Long Account Name For Testing Fixed Column Layout Wrapping " * 3
    acc.save()

    client.force_login(role_users["staff"])
    resp = client.get(f"/cash/transfers/{transfer.id}/print/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "table-layout: fixed" in body
    assert transfer.purpose in body
    assert acc.name in body
    # Long/unbroken text wraps inside the fixed columns instead of clipping.
    assert "overflow-wrap: anywhere" in body
    assert "word-break: break-word" in body
    # Debit/Credit cells must stay right-aligned inside their fixed columns.
    assert 'text-align:right; font-variant-numeric:tabular-nums' in body


def test_ftv_print_shows_full_purpose_with_spaces(client, banks, role_users):
    """A spaced long purpose wraps and renders in full on the voucher."""
    _, _, transfer = banks
    purpose = ("Payroll coverage " * 28).strip()
    assert 450 < len(purpose) <= 500
    transfer.purpose = purpose
    transfer.save(update_fields=["purpose"])
    client.force_login(role_users["staff"])
    resp = client.get(f"/cash/transfers/{transfer.id}/print/")
    assert resp.status_code == 200
    assert transfer.purpose in resp.content.decode()


def test_ftv_pdf_export_downloads_real_pdf(client, banks, role_users):
    _, _, transfer = banks
    client.force_login(role_users["staff"])
    resp = client.get(f"/cash/transfers/{transfer.id}/pdf/")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"
    assert "FTV_FTV-2026-0001.pdf" in resp["Content-Disposition"]
    data = resp.content
    assert data.startswith(b"%PDF")
    # Real selectable text (not a screenshot): the voucher reference and
    # document title appear as text inside the (compressed) content streams.
    text = _pdf_text(data)
    assert b"FTV-2026-0001" in text
    assert b"FUND TRANSFER VOUCHER" in text
    assert b"25,000.00" in text
    assert b"Inter-Bank Transfer" in text


def test_transfer_form_page_is_batch_grid(client, company, segment, accounts, role_users):
    """The dedicated new-transfer form is a batch line grid (From/To/Amount/
    Purpose) — no voucher markup leaks in, and the grid renders."""
    BankAccount.objects.create(
        code="1VB-CHK", name="First Valley Bank",
        account_type="checking", bank_name="First Valley Bank", bank_code="1VB",
        gl_account=accounts["10110"], company=company,
    )
    BankAccount.objects.create(
        code="PNB-CHK", name="Philippine National Bank",
        account_type="checking", bank_name="Philippine National Bank",
        bank_code="PNB", gl_account=accounts["10010"], company=company,
    )
    client.force_login(role_users["staff"])
    resp = client.get("/cash/transfers/new/")
    assert resp.status_code == 200
    body = resp.content.decode()
    # The batch grid posts named line fields, one full transfer leg per row.
    assert 'name="line_from"' in body
    assert 'name="line_to"' in body
    assert 'name="line_amount"' in body
    assert 'name="line_purpose"' in body
    assert 'data-line-grid="transfer"' in body
    assert 'data-add-row' in body
    assert 'data-remove-row' in body
    assert "FUND TRANSFER VOUCHER (FTV)" not in body


def _table_max_columns(body):
    """Lay out the table row by row (honouring rowspan/colspan) and return the
    widest column index reached — i.e. how many columns the browser builds."""
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.S | re.I)
    claimed = set()  # (row_index, column) occupied by a rowspan
    max_cols = 0
    for r, row in enumerate(rows):
        col = 1
        for attrs in re.findall(r"<t[dh]\b([^>]*)>", row, re.I):
            cs = re.search(r'colspan="(\d+)"', attrs)
            rs = re.search(r'rowspan="(\d+)"', attrs)
            colspan = int(cs.group(1)) if cs else 1
            rowspan = int(rs.group(1)) if rs else 1
            while (r, col) in claimed:
                col += 1
            for k in range(colspan):
                for rr in range(r, r + rowspan):
                    claimed.add((rr, col + k))
            col += colspan
            max_cols = max(max_cols, col - 1)
    return max_cols


def test_ftv_print_every_row_sums_to_grid(client, banks, role_users):
    """Regression: the FTV is a 14-column grid — no row may overflow it.

    The old header used rowspan=3 on logo+title while the next two rows also
    spanned all 14 columns, so the browser created a 28-column table and the
    document info shifted right."""
    _, _, transfer = banks
    client.force_login(role_users["staff"])
    body = client.get(f"/cash/transfers/{transfer.id}/print/").content.decode()
    assert _table_max_columns(body) == 14


def test_transfers_register_is_clean(client, company, segment, accounts, role_users):
    """The register no longer carries the entry form — just the list + link."""
    bank_from = BankAccount.objects.create(
        code="1VB-CHK", name="First Valley Bank",
        account_type="checking", bank_name="First Valley Bank", bank_code="1VB",
        gl_account=accounts["10110"], company=company,
    )
    bank_to = BankAccount.objects.create(
        code="PNB-CHK", name="Philippine National Bank",
        account_type="checking", bank_name="Philippine National Bank",
        bank_code="PNB", gl_account=accounts["10010"], company=company,
    )
    transfer = TransferService.transfer(
        from_account=bank_from, to_account=bank_to,
        amount="25000.00", purpose="Payroll coverage", transfer_date="2026-09-12",
        segment=segment, user=role_users["staff"],
    )
    client.force_login(role_users["staff"])
    resp = client.get("/cash/transfers/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'name="line_from"' not in body
    assert 'href="/cash/transfers/new/"' in body
    assert f'href="/cash/transfers/{transfer.id}/"' in body
    assert transfer.purpose in body

# --------------------------------------------------------------------------- debit-first rows

def _make_legacy_credit_first(transfer):
    """Rewind the stored line order to the OLD credit-first layout, so we can
    prove display layers normalize it for legacy vouchers like FTV-2026-0010."""
    a, b = list(transfer.journal_entry.lines.order_by("line_no"))
    assert a.debit and b.credit, "service must now store debit-first"
    # (entry, line_no) is unique: swap via a temporary number.
    a.line_no = 99
    a.save(update_fields=["line_no"])
    b.line_no = 1
    b.save(update_fields=["line_no"])
    a.line_no = 2
    a.save(update_fields=["line_no"])


def test_new_ftv_stores_debit_line_first(client, company, banks):
    bank_from, bank_to, transfer = banks
    lines = list(transfer.journal_entry.lines.order_by("line_no"))
    assert lines[0].debit and lines[0].account_id == bank_to.gl_account_id
    assert lines[1].credit and lines[1].account_id == bank_from.gl_account_id


def test_print_and_detail_show_debit_first_even_for_legacy_rows(client, company, banks, role_users):
    from django.urls import reverse

    bank_from, bank_to, transfer = banks
    _make_legacy_credit_first(transfer)
    client.force_login(role_users["head"])

    for url in (f"/cash/transfers/{transfer.id}/print/", f"/cash/transfers/{transfer.id}/"):
        body = client.get(url).content.decode()
        assert body.index(str(bank_to.gl_account.code)) < body.index(str(bank_from.gl_account.code)), url

    csv = client.get(reverse("ui:transfer_export", args=[transfer.id, "csv"]))
    rows = [r for r in csv.content.decode().splitlines() if str(bank_from.gl_account.code) in r or str(bank_to.gl_account.code) in r]
    assert rows and str(bank_to.gl_account.code) in rows[0]
