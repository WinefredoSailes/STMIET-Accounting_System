/*
 * line-grid.js — generic line-item grids.
 * Supports the three line grids in the codebase:
 *   je  — debit/credit pair columns (.amount-debit / .amount-credit)
 *   rfp — per-line Dr/Cr side (.line-side) + amount (.line-amount)
 *   pcv — expense rows (input[name="exp_amount"]) with account-name preview
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
    return el ? (parseFloat(el.value) || 0) : 0;
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
    if (td) td.textContent = d.toFixed(2);
    if (tc) tc.textContent = c.toFixed(2);
    var hint = docSel(grid.dataset.hint);
    if (hint) {
      if (d === c) {
        hint.textContent = 'Balanced';
        hint.className = grid.dataset.hintOk || 'text-sm text-emerald-600 font-medium';
      } else {
        hint.textContent = 'Difference: ' + Math.abs(d - c).toFixed(2);
        hint.className = grid.dataset.hintBad || 'text-sm text-red-600 font-medium';
      }
    }
  }

  function recalcRfp(grid) {
    var dr = 0, cr = 0;
    grid.querySelectorAll('tr').forEach(function (tr) {
      var amt = num(tr.querySelector('.line-amount'));
      var side = tr.querySelector('.line-side');
      if (side && side.value === 'cr') cr += amt; else dr += amt;
    });
    var td = docSel(grid.dataset.totalDr);
    var tc = docSel(grid.dataset.totalCr);
    if (td) td.textContent = dr.toFixed(2);
    if (tc) tc.textContent = cr.toFixed(2);
    var hint = docSel(grid.dataset.hint);
    if (hint) {
      if (dr !== cr) {
        hint.textContent = 'Debits and credits do not balance (Dr ' + dr.toFixed(2) + ' vs Cr ' + cr.toFixed(2) + ').';
        hint.className = grid.dataset.hintBad || 'mt-2 text-xs text-red-700 font-medium';
      } else {
        hint.textContent = 'Debits and credits balance.';
        hint.className = grid.dataset.hintOk || 'mt-2 text-xs text-emerald-700';
      }
    }
  }

  function recalcPcv(grid) {
    var t = 0;
    grid.querySelectorAll('input[name="exp_amount"]').forEach(function (i) { t += num(i); });
    var total = docSel(grid.dataset.total);
    if (total) total.textContent = t.toFixed(2);
  }

  function initGrid(grid) {
    if (grid.dataset.lineGridBound) return;
    grid.dataset.lineGridBound = '1';
    var variant = grid.dataset.lineGrid;
    var recalc = { je: recalcJe, rfp: recalcRfp, pcv: recalcPcv }[variant];
    var resetSelects = variant === 'rfp';
    if (!recalc) return;

    var addBtn = grid.closest('table').querySelector('[data-add-row]');
    if (addBtn) addBtn.addEventListener('click', function () {
      cloneRow(grid, resetSelects);
      recalc(grid);
    });

    grid.addEventListener('input', function () { recalc(grid); });
    grid.addEventListener('change', function (e) {
      recalc(grid);
      if (e.target.matches && e.target.matches('select[name="exp_account"]')) {
        var opt = e.target.selectedOptions[0];
        var name = opt ? (opt.dataset.name || '') : '';
        var cell = e.target.closest('tr').querySelector('.gl-name');
        if (cell) cell.textContent = name;
      }
    });
    grid.addEventListener('click', function (e) {
      var btn = e.target.closest ? e.target.closest('[data-remove-row]') : null;
      if (btn) {
        btn.closest('tr').remove();
        recalc(grid);
      }
    });
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