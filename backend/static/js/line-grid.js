/*
 * line-grid.js — generic line-item grids.
 * Supports the four line grids in the codebase:
 *   je       — debit/credit pair columns (.amount-debit / .amount-credit)
 *   rfp      — debit/credit pair columns (.amount-dr / .amount-cr)
 *   pcv      — expense rows (input[name="exp_amount"]) with total only
 *   transfer — transfer legs (input[name="line_amount"]) with total only
 *
 * The grid tbody declares behaviour via data attributes:
 *   data-line-grid="<variant>"
 *   variant je: data-total-debit / data-total-credit / data-hint
 *   variant rfp: data-total-dr / data-total-cr / data-hint
 *   variant pcv: data-total
 *   variant transfer: data-total
 * All selectors are CSS selectors resolved in document scope, the add button is
 * any [data-add-row] inside the grid's <table>, row removal is any
 * [data-remove-row] inside the tbody (one per row — every row, template or
 * cloned, keeps its own delete button). Rows may be reordered by dragging a
 * [data-drag-handle]; a row is draggable only while its handle is held so
 * typing in inputs is unaffected. Cloned rows keep cost-center selections
 * unless the variant sets resetSelects.
 *
 * Note: searchable clones are reverted to their raw <select> state before the
 * row is appended so the MutationObserver in base.js re-wraps them.
 *
 * Amount formatting (thousand separators) is centralized in amount-format.js:
 * every amount input carries data-amount and is formatted there. This file
 * only sums (via AmountFormat.parse) and renders totals (via AmountFormat.fmt).
 */
(function () {
  'use strict';

  function docSel(sel) {
    return sel ? document.querySelector(sel) : null;
  }
  function num(el) {
    return window.AmountFormat.parse(el ? el.value : '');
  }
  function fmtMoney(n) {
    return window.AmountFormat.fmt(n);
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
    row.querySelectorAll('input, textarea').forEach(function (i) { i.value = ''; i.removeAttribute('title'); if (i.tagName === 'TEXTAREA') { i.style.height = 'auto'; i.removeAttribute('data-autogrown'); } });
    // Async pickers (searchable + data-search-url) must start blank on cloned
    // rows: their options were fetched for the source row and the picked value
    // would silently duplicate otherwise.
    row.querySelectorAll('select[data-search-url]').forEach(function (s) {
      var blank = s.querySelector('option[value=""]');
      s.innerHTML = '';
      if (blank) s.appendChild(blank);
      s.selectedIndex = 0;
    });
    if (resetSelects) {
      row.querySelectorAll('select').forEach(function (s) { s.selectedIndex = 0; });
    }
    // Keep [data-remove-row] and [data-drag-handle] so every row — template or
    // freshly cloned — can delete and reorder itself.
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
    var sync = docSel(grid.dataset.totalSync);
    if (sync) sync.textContent = fmtMoney(t);
  }

  function recalcTransfer(grid) {
    var t = 0;
    grid.querySelectorAll('tr').forEach(function (tr) {
      t += num(tr.querySelector('[name="line_amount"]'));
    });
    var total = docSel(grid.dataset.total);
    if (total) total.textContent = fmtMoney(t);
  }

  function renumberLines(grid) {
    grid.querySelectorAll('tr').forEach(function (tr, i) {
      var no = tr.querySelector('.line-no');
      if (no) no.textContent = i + 1;
    });
  }

  function initGrid(grid) {
    if (grid.dataset.lineGridBound) return;
    grid.dataset.lineGridBound = '1';
    var variant = grid.dataset.lineGrid;
    var recalc = { je: recalcJe, rfp: recalcRfp, pcv: recalcPcv, transfer: recalcTransfer }[variant];
    var resetSelects = variant === 'rfp' || variant === 'je' || variant === 'transfer';
    if (!recalc) return;

    var addBtn = grid.closest('table').querySelector('[data-add-row]');
    if (addBtn) addBtn.addEventListener('click', function () {
      cloneRow(grid, resetSelects);
      recalc(grid);
    });

    grid.addEventListener('input', function () { recalc(grid); });
    grid.addEventListener('change', function () { recalc(grid); });
    grid.addEventListener('click', function (e) {
      var btn = e.target.closest ? e.target.closest('[data-remove-row]') : null;
      if (btn) {
        btn.closest('tr').remove();
        renumberLines(grid);
        recalc(grid);
      }
    });

    // Drag to reorder lines via a per-row [data-drag-handle]. Rows become
    // draggable only while their handle is pressed, so text selection inside
    // the inputs is never hijacked; drop inserts above/below the target by its
    // midpoint. Line numbers (`.line-no`) and totals are refreshed after.
    var dragging = null;
    grid.addEventListener('mousedown', function (e) {
      var handle = e.target.closest ? e.target.closest('[data-drag-handle]') : null;
      if (handle) handle.closest('tr').draggable = true;
    });
    // Release the handle without an actual drag: clear draggable so typing and
    // text selection inside the row's inputs behave normally afterwards.
    grid.addEventListener('mouseup', function (e) {
      if (e.target.closest && e.target.closest('[data-drag-handle]')) {
        grid.querySelectorAll('tr').forEach(function (tr) { tr.draggable = false; });
      }
    });
    grid.addEventListener('dragstart', function (e) {
      var tr = e.target.closest ? e.target.closest('tr') : null;
      if (!tr || !tr.querySelector('[data-drag-handle]')) return;
      dragging = tr;
      tr.style.opacity = '0.4';
      tr.style.userSelect = 'none';
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', 'row');
    });
    grid.addEventListener('dragover', function (e) {
      if (!dragging) return;
      e.preventDefault();
      var tr = e.target.closest ? e.target.closest('tr') : null;
      if (tr && tr !== dragging) tr.style.outline = '2px solid #6366f1';
    });
    grid.addEventListener('dragleave', function (e) {
      var tr = e.target.closest ? e.target.closest('tr') : null;
      if (tr) tr.style.outline = '';
    });
    grid.addEventListener('drop', function (e) {
      if (!dragging) return;
      e.preventDefault();
      var tr = e.target.closest ? e.target.closest('tr') : null;
      if (tr && tr !== dragging) {
        var rect = tr.getBoundingClientRect();
        if (e.clientY > rect.top + rect.height / 2) tr.parentNode.insertBefore(dragging, tr.nextSibling);
        else tr.parentNode.insertBefore(dragging, tr);
      }
    });
    grid.addEventListener('dragend', function () {
      if (!dragging) return;
      dragging.style.opacity = '';
      dragging.style.userSelect = '';
      dragging.draggable = false;
      grid.querySelectorAll('tr').forEach(function (tr) {
        tr.style.outline = '';
        tr.draggable = false;
      });
      dragging = null;
      renumberLines(grid);
      recalc(grid);
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