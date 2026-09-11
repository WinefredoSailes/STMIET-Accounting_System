/*
 * amount-format.js — live thousand-separator formatting for money inputs.
 * Any <input data-amount> is formatted as the user types: digits group by
 * thousands, one decimal point, max 2 decimals, no negatives. The caret is
 * preserved, including just right of a freshly typed decimal point.
 * Canonical home of formatAmountInput; line-grid.js and gross-net-calc.js
 * consume window.AmountFormat. Loaded in base.html before page scripts.
 */
(function () {
  'use strict';

  function parseAmount(value) {
    var v = String(value === undefined || value === null ? '' : value).replace(/,/g, '');
    return v ? (parseFloat(v) || 0) : 0;
  }
  function fmtAmount(n) {
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
    return !!(el && el.matches && el.matches('input[data-amount]'));
  }
  function preformat(root) {
    (root || document).querySelectorAll('input[data-amount]').forEach(formatAmountInput);
  }

  window.AmountFormat = { parse: parseAmount, fmt: fmtAmount, format: formatAmountInput };

  document.addEventListener('input', function (e) {
    if (e.isComposing) return;
    if (isAmountInput(e.target)) formatAmountInput(e.target);
  });
  document.addEventListener('change', function (e) {
    if (e.isComposing) return;
    if (isAmountInput(e.target)) formatAmountInput(e.target);
  });
  preformat(document);
  document.addEventListener('htmx:afterSwap', function (e) { preformat(e.detail.target); });
})();
