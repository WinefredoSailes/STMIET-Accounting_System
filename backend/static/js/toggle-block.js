/*
 * toggle-block.js — show/hide a collapsible action block.
 * Used by ap/rfp_detail.html and ap/cv_detail.html ("Reject with note").
 *
 * A button marked [data-toggle-target="#<id>"] toggles the 'hidden' class on
 * the targeted element when clicked. Multiple independent pairs per page work.
 */
(function () {
  'use strict';

  function init(btn) {
    if (btn.dataset.toggleBound) return;
    btn.dataset.toggleBound = '1';
    var target = btn.dataset.toggleTarget ? document.querySelector(btn.dataset.toggleTarget) : null;
    if (!target) return;
    btn.addEventListener('click', function () {
      target.classList.toggle('hidden');
    });
  }

  function initAll(root) {
    var btns = (root || document).querySelectorAll('[data-toggle-target]');
    for (var i = 0; i < btns.length; i++) init(btns[i]);
  }

  initAll(document);
  document.addEventListener('htmx:afterSwap', function (e) {
    initAll(e.detail.target);
  });
})();