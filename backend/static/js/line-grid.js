/*
 * line-grid.js — generic line-item grids.
 * Supports the three line grids in the codebase:
 *   je  — debit/credit pair columns (.amount-debit / .amount-credit)
 *   rfp — debit/credit pair columns (.amount-dr / .amount-cr)
 *   pcv — expense rows (input[name="exp_amount"]) with total only
 *
 * The grid tbody declares behaviour via data attributes:
 *   data-line-grid="<variant>"
 *   variant je: data-total-debit / data-total-credit / data-hint
 *   variant rfp: data-total-dr / data-total-cr / data-hint
 *   variant pcv: data-total
 * All selectors are CSS selectors resolved in document scope, the add button is
 * any [data-add-row] inside the grid's <table>, row removal is any
 * [data-remove-row] inside the tbody. Cloned rows keep cost-center selections
 * unless the variant sets resetSelects.
 *
 * Note: searchable clones are reverted to their raw <select> state before the
 * row is appended so the MutationObserver in base.js re-wraps them.
 */
(function () {
  'use strict';

  function docSel(sel) {
    return sel ? document.querySelector(sel) : null;
  }
  function num(el) {
    var v = el ? String(el.value).replace(/,/g, '') : '';
    return v ? (parseFloat(v) || 0) : 0;
  }
  function fmtMoney(n) {
    return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function formatAmountInput(el) {
    var full = el.value;
    var start = el.selectionStart === null ? full.length : el.selectionStart;
    var digitsBefore = (full.slice(0, start).match(/\d/g) || []).length;
    var dotIndex = full.indexOf('.');
    var afterDot = dotIndex !== -1 && start > dotIndex;
    var raw = full.replace(/[^\d.]/g, '');
    var dot = raw.indexOf('.');
    var whole = (dot === -1 ? raw : raw.slice(0, dot)).replace(/^0+(?=\d)/, '');
    var frac = dot === -1 ? '' : raw.slice(dot + 1).replace(/\D/g, '').slice(0, 2);
    var text = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    if (dot !== -1) text += '.' + frac;
    el.value = text;
    var pos = 0, seen = 0;
    while (pos < text.length && seen < digitsBefore) {
      if (/\d/.test(text.charAt(pos))) seen++;
      pos++;
    }
    if (afterDot) {
      var fd = text.indexOf('.');
      if (fd !== -1 && pos <= fd) pos = fd + 1;
    }
    if (el.setSelectionRange) el.setSelectionRange(pos, pos);
  }
  function isAmountInput(el) {
    return !!(el && el.matches && el.matches('.amount-dr, .amount-cr, .amount-debit, .amount-credit'));
  }

  function resetSearchable(select) {
    select.removeAttribute('data-search-enhanced');
    var wrap = select.closest('.searchable-wrap');
    if (wrap) wrap.replaceWith(select);
    select.classList.add('hidden');
  }

  function cloneRow(grid, resetSelects) {
    var src = grid.querySelector('tr');
    var row = src.cloneNode(true);
    row.querySelectorAll('input').forEach(function (i) { i.value = ''; });
    if (resetSelects) {
      row.querySelectorAll('select').forEach(function (s) { s.selectedIndex = 0; });
    }
    row.querySelectorAll('[data-remove-row]').forEach(function (b) { b.remove(); });
    row.querySelectorAll('select[data-searchable]').forEach(resetSearchable);
    var no = row.querySelector('.line-no');
    if (no) no.textContent = grid.querySelectorAll('tr').length + 1;
    grid.appendChild(row);
    return row;
  }

  function recalcJe(grid) {
    var d = 0, c = 0;
    grid.querySelectorAll('tr').forEach(function (tr) {
      d += num(tr.querySelector('.amount-debit'));
      c += num(tr.querySelector('.amount-credit'));
    });
    var td = docSel(grid.dataset.totalDebit);
    var tc = docSel(grid.dataset.totalCredit);
    if (td) td.textContent = fmtMoney(d);
    if (tc) tc.textContent = fmtMoney(c);
    var hint = docSel(grid.dataset.hint);
    if (hint) {
      if (d === c) {
        hint.textContent = 'Balanced';
        hint.className = grid.dataset.hintOk || 'text-sm text-emerald-600 font-medium';
      } else {
        hint.textContent = 'Difference: ' + fmtMoney(Math.abs(d - c));
        hint.className = grid.dataset.hintBad || 'text-sm text-red-600 font-medium';
      }
    }
  }

  function recalcRfp(grid) {
    var dr = 0, cr = 0;
    grid.querySelectorAll('tr').forEach(function (tr) {
      dr += num(tr.querySelector('.amount-dr'));
      cr += num(tr.querySelector('.amount-cr'));
    });
    var td = docSel(grid.dataset.totalDr);
    var tc = docSel(grid.dataset.totalCr);
    if (td) td.textContent = fmtMoney(dr);
    if (tc) tc.textContent = fmtMoney(cr);
    var hint = docSel(grid.dataset.hint);
    if (hint) {
      if (dr !== cr) {
        hint.textContent = 'Debits and credits do not balance (Dr ' + fmtMoney(dr) + ' vs Cr ' + fmtMoney(cr) + ').';
        hint.className = grid.dataset.hintBad || 'mt-2 text-xs text-red-700 font-medium';
      } else {
        hint.textContent = 'Debits and credits balance.';
        hint.className = grid.dataset.hintOk || 'mt-2 text-xs text-emerald-700';
      }
    }
  }

  function recalcPcv(grid) {
    var t = 0;
    grid.querySelectorAll('tr').forEach(function (tr) {
      t += num(tr.querySelector('.amount-dr')) + num(tr.querySelector('.amount-cr'));
    });
    var total = docSel(grid.dataset.total);
    if (total) total.textContent = fmtMoney(t);
  }

  function initGrid(grid) {
    if (grid.dataset.lineGridBound) return;
    grid.dataset.lineGridBound = '1';
    var variant = grid.dataset.lineGrid;
    var recalc = { je: recalcJe, rfp: recalcRfp, pcv: recalcPcv }[variant];
    var resetSelects = variant === 'rfp' || variant === 'je';
    if (!recalc) return;

    var addBtn = grid.closest('table').querySelector('[data-add-row]');
    if (addBtn) addBtn.addEventListener('click', function () {
      cloneRow(grid, resetSelects);
      recalc(grid);
    });

    grid.addEventListener('input', function (e) {
      if (isAmountInput(e.target)) formatAmountInput(e.target);
      recalc(grid);
    });
    grid.addEventListener('change', function (e) {
      if (isAmountInput(e.target)) formatAmountInput(e.target);
      recalc(grid);
    });
    grid.addEventListener('click', function (e) {
      var btn = e.target.closest ? e.target.closest('[data-remove-row]') : null;
      if (btn) {
        btn.closest('tr').remove();
        recalc(grid);
      }
    });
    grid.querySelectorAll('input.amount-dr, input.amount-cr, input.amount-debit, input.amount-credit')
        .forEach(formatAmountInput);
    recalc(grid);
  }

  function initAll(root) {
    var nodes = (root || document).querySelectorAll('tbody[data-line-grid]');
    for (var i = 0; i < nodes.length; i++) initGrid(nodes[i]);
  }

  initAll(document);

  // Re-wire grids that arrive through HTMX swaps. Nodes already initialised
  // (marked data-line-grid-bound) are skipped to avoid double binding.
  document.addEventListener('htmx:afterSwap', function (e) {
    initAll(e.detail.target);
  });
})();