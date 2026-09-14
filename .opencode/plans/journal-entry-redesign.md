# Journal Entry Form Redesign — Complete Implementation Plan

## Overview

Redesign the Journal Entry frontend to follow the reference voucher layout exactly, while preserving all existing backend functionality. Add supplier_name, po, and ref_number fields to the model. Implement CSV export. Use browser print-to-PDF for PDF export.

---

## FILES TO MODIFY (6)

### 1. `backend/apps/posting/models.py` — Add 3 new fields to JournalEntry

Add after `total_credit` field (around line 74):

```python
    # Document metadata for voucher layout (ACCTG-FOR-012)
    supplier_name = models.CharField(max_length=255, blank=True, default="")
    po = models.CharField(max_length=128, blank=True, default="")
    ref_number = models.CharField(max_length=128, blank=True, default="")
```

---

### 2. `backend/apps/ui/views.py` — Update form processing + add CSV export

#### A. Update `_create_entry_from_form()` (around line 239)

After the existing `source_doc_no` parsing (line ~251), add:

```python
    supplier_name = request.POST.get("supplier_name", "").strip()[:255]
    po = request.POST.get("po", "").strip()[:128]
    ref_number = request.POST.get("ref_number", "").strip()[:128]
```

Then find where `entry = JournalEntry(...)` is created and add these fields:

```python
    entry = JournalEntry.objects.create(
        ...existing fields...
        supplier_name=supplier_name,
        po=po,
        ref_number=ref_number,
    )
```

#### B. Update `_update_entry_from_form()` (around line 549)

Add the same three field reads before saving:

```python
    entry.supplier_name = request.POST.get("supplier_name", "").strip()[:255]
    entry.po = request.POST.get("po", "").strip()[:128]
    entry.ref_number = request.POST.get("ref_number", "").strip()[:128]
    entry.save(update_fields=["supplier_name", "po", "ref_number", "updated_at"])
```

#### C. Add CSV Export View (new function at end of file)

```python
from django.http import HttpResponse


@login_required
def je_csv_export(request, pk):
    """Export journal entry as CSV download."""
    entry = get_object_or_404(
        JournalEntry.objects.select_related("company", "segment")
            .prefetch_related("lines__account", "lines__segment"),
        pk=pk,
    )

    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Header metadata
    writer.writerow(["Voucher Ref #", entry.entry_no])
    writer.writerow(["Date", entry.transaction_date.isoformat()])
    writer.writerow(["Segment", entry.segment.code])
    writer.writerow(["Supplier / Customer Name", entry.supplier_name or ""])
    writer.writerow(["PO", entry.po or ""])
    writer.writerow(["REF #", entry.ref_number or ""])
    writer.writerow(["Source Type", entry.source_doc_type or ""])
    writer.writerow(["Source No.", entry.source_doc_no or ""])
    writer.writerow([])

    # Column headers
    writer.writerow([
        "COA", "Account Name", "Description", "Debit", "Credit"
    ])

    # Data rows
    for line in entry.lines.order_by("line_no"):
        writer.writerow([
            line.account.code,
            line.account.name,
            line.description or "",
            str(line.debit.quantize(Decimal("0.01"))),
            str(line.credit.quantize(Decimal("0.01"))),
        ])

    # Totals
    writer.writerow([])
    writer.writerow([
        "TOTALS", "", "",
        str(entry.total_debit.quantize(Decimal("0.01"))),
        str(entry.total_credit.quantize(Decimal("0.01"))),
    ])

    response = HttpResponse(
        output.getvalue(),
        content_type="text/csv",
    )
    response["Content-Disposition"] = f'attachment; filename="JE_{entry.entry_no}.csv"'
    return response
```

---

### 3. `backend/apps/ui/urls.py` — Add CSV export route

Find the journal entries routes section and add:

```python
path("journal/<int:pk>/csv/", views.je_csv_export, name="je_csv_export"),
```

Place it near the existing `je_print` route.

---

### 4. `backend/apps/ui/templates/ui/posting/je_form.html` — FULL REWRITE

This is the main redesign. Replace the entire file with:

```html
{% extends "ui/base.html" %}
{% load static ui_filters %}
{% block title %}{% if editing %}Edit Journal Entry {{ editing.entry_no }}{% else %}New Journal Entry{% endif %}{% endblock %}
{% block content %}
<div class="p-6">
  <!-- Breadcrumb -->
  <a href="{% url 'ui:je_list' %}" class="text-sm text-slate-500 hover:text-slate-700">&larr; Journal entries</a>

  <!-- Page Title -->
  <h1 class="text-xl font-semibold text-slate-900 mt-1">
    {% if editing %}Edit Journal Entry {{ editing.entry_no }}{% else %}New Journal Entry{% endif %}
  </h1>
  <p class="text-sm text-slate-500 mt-1">Debits must equal credits — the system never force-balances (ADR-002).</p>

  <form method="post" class="mt-6 space-y-5">
    {% csrf_token %}

    <!-- ===== COMPANY BRANDING HEADER ===== -->
    <div class="flex items-center gap-4 pb-4 border-b border-slate-200">
      <img src="{% static 'stmiet-trans-logo.png' %}" alt="" class="h-12 w-auto">
      <div>
        <div class="text-base font-bold text-slate-900">{{ company.name }}</div>
        <div class="text-xs text-slate-500 uppercase tracking-wider">General Journal Voucher</div>
      </div>
    </div>

    <!-- ===== DOCUMENT METADATA (Two-Sided Layout) ===== -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
      <!-- LEFT SIDE -->
      <div class="space-y-2">
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="id_entry_no">Voucher Ref #</label>
          <input type="text" id="id_entry_no" value="{{ editing.entry_no|default:'—' }}" readonly
                 class="w-full rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-500">
        </div>
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="id_supplier_name">Supplier / Customer Name</label>
          <input type="text" name="supplier_name" id="id_supplier_name" maxlength="255"
                 value="{{ editing.supplier_name|default:'' }}"
                 class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
        </div>
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="id_po">PO</label>
          <input type="text" name="po" id="id_po" maxlength="128"
                 value="{{ editing.po|default:'' }}"
                 class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
        </div>
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="id_ref_number">REF #</label>
          <input type="text" name="ref_number" id="id_ref_number" maxlength="128"
                 value="{{ editing.ref_number|default:'' }}"
                 class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
        </div>
      </div>

      <!-- RIGHT SIDE -->
      <div class="space-y-2">
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="id_transaction_date">Date</label>
          <input type="date" name="transaction_date" id="id_transaction_date" required
                 value="{{ editing.transaction_date|date:'Y-m-d'|default:today|date:'Y-m-d' }}"
                 class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
        </div>
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="id_cycle">Cycle</label>
          {% if editing.fiscal_period %}
          <input type="text" id="id_cycle" value="{{ editing.fiscal_period.name }}" readonly
                 class="w-full rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-500">
          {% else %}
          <input type="text" id="id_cycle" placeholder="Auto-derived from date" readonly
                 class="w-full rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-500">
          {% endif %}
        </div>
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="id_source_doc_type">Source Type</label>
          <input type="text" name="source_doc_type" id="id_source_doc_type" list="source-types"
                 maxlength="16"
                 value="{{ editing.source_doc_type|default:'' }}"
                 class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
          <datalist id="source-types">
            <option value="AR"><option value="AP"><option value="CV"><option value="PCV">
            <option value="RFP"><option value="DEP"><option value="ADJ"><option value="JE">
          </datalist>
        </div>
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="id_source_doc_no">Source No.</label>
          <input type="text" name="source_doc_no" id="id_source_doc_no"
                 maxlength="32"
                 value="{{ editing.source_doc_no|default:'' }}"
                 class="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
        </div>
      </div>
    </div>

    <!-- ===== ACCOUNT DISTRIBUTION SECTION ===== -->
    <div>
      <div class="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-3">Account Distribution</div>

      <div class="bg-white rounded-xl border border-slate-200 overflow-x-auto">
        <table class="line-table w-full text-sm" style="min-width: 1050px;">
          <colgroup>
            <col style="width:70px"><!-- COA -->
            <col style="width:260px"><!-- Account Name -->
            <col style="width:100px"><!-- Description -->
            <col style="width:160px"><!-- Debit -->
            <col style="width:160px"><!-- Credit -->
          </colgroup>
          <thead class="bg-slate-50 text-left text-xs uppercase tracking-wider text-slate-500">
            <tr>
              <th class="px-3 py-2.5">COA</th>
              <th class="px-3 py-2.5">Account Name</th>
              <th class="px-3 py-2.5">Description</th>
              <th class="px-3 py-2.5 text-right">Debit</th>
              <th class="px-3 py-2.5 text-right">Credit</th>
            </tr>
          </thead>
          <tbody id="lines-body" data-line-grid="je"
                 data-total-debit="#total-debit" data-total-credit="#total-credit" data-hint="#balance-hint"
                 class="divide-y divide-slate-100">
            {% if editing %}
            {% for line in editing.lines.all %}
            <tr>
              <td class="px-3 py-2">
                <div class="flex items-center gap-1">
                  <span class="coa-display font-mono text-xs whitespace-nowrap">{{ line.account.code }}</span>
                  <select name="account" data-searchable data-search-compact
                          data-search-placeholder="Search code or name…"
                          data-search-url="{% url 'ui:account_options' %}?scope=all&selected={{ line.account.code }}"
                          data-search-value="id"
                          title="{{ line.account.code }} — {{ line.account.name }}"
                          class="block w-full max-w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs overflow-hidden text-ellipsis whitespace-nowrap">
                    <option value="{{ line.account.id }}" selected>{{ line.account.code }} {{ line.account.name }}</option>
                  </select>
                </div>
              </td>
              <td class="px-3 py-2">
                <span class="account-name-display text-xs">{{ line.account.name }}</span>
              </td>
              <td class="px-3 py-2 overflow-hidden">
                <textarea name="line_description" data-autogrow rows="1"
                          class="block w-full resize-none overflow-hidden rounded-md border border-slate-300 px-2 py-1.5 text-xs leading-5"
                          style="word-break:break-word">{{ line.description }}</textarea>
              </td>
              <td class="px-3 py-2 overflow-hidden">
                <input type="text" inputmode="decimal" autocomplete="off"
                       data-amount pattern="[0-9,]*[.]?[0-9]*"
                       name="debit" value="{{ line.debit|money }}"
                       class="block w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs text-right tabular-nums amount-debit">
              </td>
              <td class="px-3 py-2 overflow-hidden">
                <input type="text" inputmode="decimal" autocomplete="off"
                       data-amount pattern="[0-9,]*[.]?[0-9]*"
                       name="credit" value="{{ line.credit|money }}"
                       class="block w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs text-right tabular-nums amount-credit">
              </td>
            </tr>
            {% endfor %}
            {% else %}
            <tr>
              <td class="px-3 py-2">
                <div class="flex items-center gap-1">
                  <span class="coa-display font-mono text-xs whitespace-nowrap"></span>
                  <select name="account" data-searchable data-search-compact
                          data-search-placeholder="Search code or name…"
                          data-search-url="{% url 'ui:account_options' %}?scope=all"
                          data-search-value="id"
                          title="— select —"
                          class="block w-full max-w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs overflow-hidden text-ellipsis whitespace-nowrap">
                    <option value="">— select —</option>
                  </select>
                </div>
              </td>
              <td class="px-3 py-2">
                <span class="account-name-display text-xs"></span>
              </td>
              <td class="px-3 py-2 overflow-hidden">
                <textarea name="line_description" data-autogrow rows="1"
                          class="block w-full resize-none overflow-hidden rounded-md border border-slate-300 px-2 py-1.5 text-xs leading-5"
                          style="word-break:break-word"></textarea>
              </td>
              <td class="px-3 py-2 overflow-hidden">
                <input type="text" inputmode="decimal" autocomplete="off"
                       data-amount pattern="[0-9,]*[.]?[0-9]*"
                       name="debit"
                       class="block w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs text-right tabular-nums amount-debit">
              </td>
              <td class="px-3 py-2 overflow-hidden">
                <input type="text" inputmode="decimal" autocomplete="off"
                       data-amount pattern="[0-9,]*[.]?[0-9]*"
                       name="credit"
                       class="block w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs text-right tabular-nums amount-credit">
              </td>
            </tr>
            {% endif %}
          </tbody>
          <tfoot class="bg-slate-50">
            <tr>
              <td colspan="3" class="px-3 py-3 text-right font-semibold">TOTALS</td>
              <td id="total-debit" class="px-3 py-3 text-right font-semibold tabular-nums">0.00</td>
              <td id="total-credit" class="px-3 py-3 text-right font-semibold tabular-nums">0.00</td>
            </tr>
            <tr>
              <td colspan="5" class="px-3 py-2">
                <button type="button" id="add-line" data-add-row
                        class="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100">
                  + Add line
                </button>
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>

    <!-- ===== ACTIONS BAR ===== -->
    <div class="flex items-center gap-3">
      <button type="submit" class="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700">
        {% if editing %}Save changes{% else %}Save draft{% endif %}
      </button>
      <span id="balance-hint" class="text-sm"></span>
    </div>

    <!-- ===== SIGNATURE SECTION ===== -->
    <div class="mt-12 pt-8 border-t border-slate-200">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-16">
        <div>
          <div class="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-8">Prepared By:</div>
          <div class="border-b border-slate-400 mb-1 h-12"></div>
          <div class="text-xs text-slate-500">Signature over Printed Name</div>
        </div>
        <div>
          <div class="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-8">Approved By:</div>
          <div class="border-b border-slate-400 mb-1 h-12"></div>
          <div class="text-xs text-slate-500">Signature over Printed Name</div>
        </div>
      </div>
    </div>

  </form>
</div>
{% endblock %}

{% block extra_js %}
<script src="{% static 'js/line-grid.js' %}"></script>
<script>
  (function () {
    // Split account display into COA code + Account Name columns
    function syncAccountDisplay(sel, coaSpan, nameSpan) {
      var opt = sel.options[sel.selectedIndex];
      if (!opt || !opt.text || opt.value === '') {
        if (coaSpan) coaSpan.textContent = '';
        if (nameSpan) nameSpan.textContent = '';
        return;
      }
      var parts = opt.text.split(' ', 1);
      if (coaSpan) coaSpan.textContent = parts[0] || '';
      if (nameSpan) nameSpan.textContent = opt.text.substring(parts[0].length).trim();
    }

    // Initialize existing selects
    document.querySelectorAll('#lines-body select[name="account"]').forEach(function(sel) {
      var row = sel.closest('tr');
      var coaSpan = row.querySelector('.coa-display');
      var nameSpan = row.querySelector('.account-name-display');
      syncAccountDisplay(sel, coaSpan, nameSpan);
    });

    // Sync on change
    document.addEventListener("change", function (e) {
      if (e.target && e.target.matches && e.target.matches('#lines-body select[name="account"]')) {
        var row = e.target.closest('tr');
        var coaSpan = row.querySelector('.coa-display');
        var nameSpan = row.querySelector('.account-name-display');
        syncAccountDisplay(e.target, coaSpan, nameSpan);
      }
    });

    // Sync newly added rows
    document.getElementById("add-line").addEventListener("click", function () {
      setTimeout(function () {
        var rows = document.querySelectorAll('#lines-body tr');
        var last = rows[rows.length - 1];
        if (!last) return;
        var sel = last.querySelector('select[name="account"]');
        if (sel) {
          var coaSpan = last.querySelector('.coa-display');
          var nameSpan = last.querySelector('.account-name-display');
          syncAccountDisplay(sel, coaSpan, nameSpan);
        }
      }, 0);
    });
  })();
</script>
{% endblock %}
```

---

### 5. `backend/apps/ui/templates/ui/posting/je_print.html` — Enhanced Print Template

Replace the entire file with this enhanced version that matches the reference voucher layout:

```html
{% extends "ui/base.html" %}
{% load static ui_filters %}
{% block title %}JE {{ entry.entry_no}} — Print{% endblock %}
{% block content %}
<style>
  @page { size: A5 portrait; margin: 6mm; }
  .print-a4 @page { size: A4 portrait; margin: 8mm; }
  @media print {
    html, body { width: 100%; margin: 0; padding: 0; background: #fff !important; }
    #sidebar, header, .p-4, .no-print, .print-toolbar { display: none !important; }
    .je-paper { box-shadow: none; margin: 0; padding: 0; border: none; width: 100% !important; max-width: none !important; }
    .je-paper table { width: 100%; border-collapse: collapse; table-layout: fixed; }
    .je-paper td { padding: 1px 4px; }
    tr, td { page-break-inside: avoid; break-inside: avoid; }
  }
  .print-toolbar {
    display: flex; justify-content: center; gap: 8px; padding: 12px 16px;
    background: #f1f5f9; border-bottom: 1px solid #e2e8f0;
  }
  .print-toolbar button {
    padding: 6px 14px; border: 1px solid #cbd5e1; border-radius: 4px;
    font-size: 12px; cursor: pointer; background: #fff; transition: all .15s;
  }
  .print-toolbar button:hover { background: #f8fafc; border-color: #94a3b8; }
  .print-toolbar button.active { background: #1e293b; color: #fff; border-color: #1e293b; }
  .print-toolbar button:last-child { background: #16a34a; color: #fff; border-color: #16a34a; }
  .print-toolbar button:last-child:hover { background: #15803d; }
  .je-paper {
    background: #fff; box-shadow: none;
    margin: 0 auto; padding: 0; max-width: 148mm;
  }
  .je-paper table { width: 100%; table-layout: fixed; border-collapse: collapse; }
  .je-paper td { border: 1px solid #000; box-sizing: border-box; padding: 1px 4px; }
  .je-paper *, .je-paper { -webkit-print-color-adjust: exact; print-color-adjust: exact; color-adjust: exact; }
</style>

<!-- Print Toolbar -->
<div class="no-print print-toolbar">
  <button class="active" onclick="setPaper('a5')">A5 / Half-Bond</button>
  <button onclick="setPaper('a4')">A4</button>
  <button onclick="window.print()">Print / Save as PDF</button>
</div>

<div class="je-paper">
  <!-- 12-column grid: every row colspans sum to exactly 12 -->
  <table>
    <colgroup>
      <col><col><col><col><col><col><col><col><col><col><col><col>
    </colgroup>
    <tbody>

      <!-- ===== HEADER BLOCK ===== -->
      <!-- Row 1: logo + JOURNAL ENTRY + ACCOUNTING DEPARTMENT -->
      <tr>
        <td rowspan="4" colspan="3" style="text-align:center; vertical-align:middle">
          <img src="{% static 'stmiet-trans-logo.png' %}" alt="" style="height:44px; width:auto; max-width:100%; display:block; margin:0 auto">
        </td>
        <td rowspan="4" colspan="6" style="text-align:center; vertical-align:middle; font-size:16px; font-weight:900; letter-spacing:.08em; background:#fce4d6">
          JOURNAL ENTRY
        </td>
        <td colspan="5" style="text-align:right; vertical-align:top; font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.06em">
          ACCOUNTING DEPARTMENT
        </td>
      </tr>
      <!-- Row 2: Document No. -->
      <tr style="font-size:10px">
        <td colspan="2">Document No.:</td>
        <td colspan="3">ACCTG-FOR-012</td>
      </tr>
      <!-- Row 3: Effective Date -->
      <tr style="font-size:10px">
        <td colspan="2">Effective Date:</td>
        <td colspan="3">08.18.2022</td>
      </tr>
      <!-- Row 4: Revision No. -->
      <tr style="font-size:10px">
        <td colspan="2">Revision No.:</td>
        <td colspan="3">02</td>
      </tr>

      <!-- ===== ENTRY INFORMATION ===== -->
      <tr>
        <td colspan="12" style="background:#fce4d6; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.04em">
          Entry Information
        </td>
      </tr>
      <!-- Row: Supplier/Customer Name -->
      <tr style="font-size:10px">
        <td colspan="2" style="font-weight:600">SUPPLIER / CUSTOMER:</td>
        <td colspan="10" style="white-space:normal; font-weight:500">{{ entry.supplier_name|default:"—" }}</td>
      </tr>
      <!-- Row: PO / REF # -->
      <tr style="font-size:10px">
        <td colspan="2" style="font-weight:600">PO:</td>
        <td colspan="5">{{ entry.po|default:"—" }}</td>
        <td colspan="2" style="font-weight:600">REF #:</td>
        <td colspan="5">{{ entry.ref_number|default:"—" }}</td>
      </tr>
      <!-- Row: Date / Segment -->
      <tr style="font-size:10px">
        <td colspan="3" style="font-weight:600">DATE:</td>
        <td colspan="5">{{ entry.transaction_date|date:"m/d/Y" }}</td>
        <td colspan="2" style="font-weight:600">SEGMENT:</td>
        <td colspan="4">{{ entry.segment.code }}</td>
      </tr>
      <!-- Row: Source Type / Source No. -->
      <tr style="font-size:10px">
        <td colspan="3" style="font-weight:600">SOURCE TYPE:</td>
        <td colspan="5">{{ entry.source_doc_type|default:"—" }}</td>
        <td colspan="2" style="font-weight:600">SOURCE NO.:</td>
        <td colspan="4">{{ entry.source_doc_no|default:"—" }}</td>
      </tr>
      <!-- Row: Description -->
      <tr style="font-size:10px">
        <td colspan="3" style="font-weight:600; white-space:normal;">DESCRIPTION:</td>
        <td colspan="9">{{ entry.description }}</td>
      </tr>

      <!-- ===== ACCOUNT DISTRIBUTION ===== -->
      <tr>
        <td colspan="12" style="background:#fce4d6; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.04em">
          Account Distribution
        </td>
      </tr>
      <!-- Column headers: 1+3+1+4+2+1=12 -->
      <tr style="font-size:10px; text-transform:uppercase; letter-spacing:.03em">
        <td style="font-weight:700">#</td>
        <td colspan="3" style="font-weight:700">COA</td>
        <td colspan="2" style="font-weight:700">Description</td>
        <td colspan="4" style="font-weight:700">Account Name</td>
        <td colspan="2" style="font-weight:700; text-align:right">Debit</td>
        <td colspan="2" style="font-weight:700; text-align:right">Credit</td>
      </tr>
      <!-- Data rows: 1+3+1+4+2+1=12 -->
      {% for line in lines %}
      <tr style="font-size:10px; line-height:2;">
        <td>{{ line.line_no }}</td>
        <td colspan="3" style="font-family:monospace; font-size:9px; white-space:normal">{{ line.account.code }}</td>
        <td colspan="2" style="overflow:hidden; text-overflow:ellipsis; white-space:normal">{{ line.description|default:"—" }}</td>
        <td colspan="4" style="overflow:hidden; text-overflow:ellipsis; white-space:normal">{{ line.account.name }}</td>
        <td colspan="2" style="text-align:right; font-variant-numeric:tabular-nums">{{ line.debit|money }}</td>
        <td colspan="2" style="text-align:right; font-variant-numeric:tabular-nums">{{ line.credit|money }}</td>
      </tr>
      {% endfor %}
      {% if not lines %}
      <tr>
        <td colspan="12" style="font-size:10px; color:#94a3b8">No distribution lines.</td>
      </tr>
      {% endif %}

      <!-- Totals row -->
      <tr style="font-size:10px; font-weight:600">
        <td colspan="10" style="text-align:right">TOTALS</td>
        <td colspan="2" style="text-align:right; font-variant-numeric:tabular-nums">{{ total|money }}</td>
        <td colspan="2" style="text-align:right; font-variant-numeric:tabular-nums">{{ total|money }}</td>
      </tr>

      <!-- ===== SIGNATURE SECTION ===== -->
      <tr style="font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.03em">
        <td colspan="6">Prepared By:</td>
        <td colspan="6">Approved By:</td>
      </tr>
      <!-- Signature lines -->
      <tr style="height:22px">
        <td colspan="6" style="border-top:1px solid #000; text-align:center; vertical-align:bottom; font-size:10px; font-weight:600">{{ requested_by }}</td>
        <td colspan="6" style="border-top:1px solid #000; text-align:center; vertical-align:bottom; font-size:10px; font-weight:600">{{ checked_by }}</td>
      </tr>
      <!-- Role labels -->
      <tr style="font-size:8px; text-transform:uppercase; letter-spacing:.03em; color:#64748b">
        <td colspan="6" style="text-align:center">Signature over Printed Name</td>
        <td colspan="6" style="text-align:center">Signature over Printed Name</td>
      </tr>

    </tbody>
  </table>
</div>
{% endblock %}

{% block extra_js %}
<script>
  function setPaper(size) {
    document.body.classList.toggle('print-a4', size === 'a4');
    document.querySelectorAll('.print-toolbar button').forEach(function(btn, i) {
      if (i < 2) btn.classList.toggle('active', (i === 0 && size === 'a5') || (i === 1 && size === 'a4'));
    });
  }
  window.addEventListener("load", function () {
    setTimeout(function () { window.print(); }, 350);
  });
</script>
{% endblock %}
```

---

### 6. `backend/static/css/line-table.css` — Minor CSS Enhancement

Add these rules to ensure proper text wrapping in cells:

```css
/* Allow textarea inputs to wrap within fixed cells */
.line-table textarea {
  white-space: normal;
  word-wrap: break-word;
  overflow-wrap: break-word;
}

/* Ensure account name column wraps long names */
.line-table .account-name-display {
  white-space: normal;
  word-wrap: break-word;
  overflow-wrap: break-word;
  display: inline-block;
  max-width: 100%;
}
```

---

## Migration Command

After modifying `models.py`, run:

```bash
cd backend
python manage.py makemigrations posting
python manage.py migrate
```

---

## Testing Plan

### Phase 1: Model + Migration Tests
1. Run `python manage.py check` — no issues
2. Run `python manage.py makemigrations posting --check` — confirms migration is clean
3. Verify new fields exist: `python -c "from apps.posting.models import JournalEntry; print(JournalEntry._meta.get_fields())"`

### Phase 2: View Tests
1. Create draft JE via `/journal/new/` with all new fields filled
2. Edit draft JE — verify new fields persist
3. Submit → Approve → Post workflow still works
4. Test CSV export endpoint
5. Test print/PDF output

### Phase 3: Full Test Suite
Run `python -m pytest -q --tb=short` — expect same results as baseline (1 pre-existing failure, everything else passes)

### Phase 4: Manual Verification Checklist
- [ ] `/journal/new/` renders with company branding header
- [ ] Two-sided metadata layout displays correctly
- [ ] Voucher Ref # is read-only
- [ ] Supplier / Customer Name field saves and persists
- [ ] PO field saves and persists
- [ ] REF # field saves and persists
- [ ] Date field works
- [ ] Cycle shows fiscal period name (read-only)
- [ ] Source Type has datalist suggestions
- [ ] Source No. saves correctly
- [ ] Account Distribution table has correct columns (COA | Account Name | Description | Debit | Credit)
- [ ] COA column shows monospaced code
- [ ] Account Name column updates when account selected
- [ ] Description textarea wraps properly
- [ ] Debit/Credit columns always aligned (fixed widths)
- [ ] Long account names wrap without breaking table
- [ ] "+ Add line" creates new row with clean state
- [ ] Balance hint shows "Balanced" or "Difference: X.XX"
- [ ] Save draft creates entry with all fields
- [ ] Edit draft preserves all data
- [ ] Submit → Approve → Post workflow completes
- [ ] Print view opens with correct formatting
- [ ] Browser "Save as PDF" produces selectable-text PDF
- [ ] CSV download contains all metadata + line data
- [ ] CSV opens correctly in Excel
- [ ] Signature section displays on form and print
- [ ] All existing tests still pass
- [ ] No JavaScript console errors

---

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| Removing segment column breaks per-line segment override | Lines inherit entry segment — acceptable for most workflows. Can restore later if needed. |
| New POST params cause validation errors | Backend strips unknown params; only known fields are read |
| JS selector mismatch with line-grid.js | Keep `data-line-grid="je"`, `select[name="account"]`, `.amount-debit`, `.amount-credit` selectors intact |
| Tailwind classes not compiled | Run `npm run build` after template changes |
| Print layout breaks on multi-page | CSS `page-break-inside: avoid` on tr/tdd prevents awkward row splits |
| CSV special characters corrupt file | Python csv.writer handles quoting automatically |
