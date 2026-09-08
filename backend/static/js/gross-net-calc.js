/*
 * gross-net-calc.js — check-voucher gross → net auto-calc.
 * Used by ap/cv_form.html and ap/cv_revise_form.html.
 *
 * A container marked [data-net-calc] (a <fieldset>) hosts:
 *   #id_gross_amount (number input)
 *   #id_withheld_tax  (number input)
 *   #id_net_amount    (display element, textContent is updated)
 * Replaces the former per-template inline net() function + oninput handlers.
 */
(function () {
  'use strict';

  function bind(rootEl) {
    var gross = rootEl.querySelector('#id_gross_amount');
    var tax = rootEl.querySelector('#id_withheld_tax');
    var net = rootEl.querySelector('#id_net_amount');
    if (!gross || !tax || !net) return;

    function recalc() {
      var g = parseFloat(gross.value) || 0;
      var t = parseFloat(tax.value) || 0;
      net.textContent = (g - t).toFixed(2);
    }
    gross.addEventListener('input', recalc);
    tax.addEventListener('input', recalc);
    recalc();
  }

  function bindAll(root) {
    var nodes = (root || document).querySelectorAll('[data-net-calc]');
    for (var i = 0; i < nodes.length; i++) bind(nodes[i]);
  }

  bindAll(document);
  document.addEventListener('htmx:afterSwap', function (e) {
    bindAll(e.detail.target);
  });
})();