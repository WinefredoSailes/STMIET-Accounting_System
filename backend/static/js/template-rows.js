// Dynamic sub-rows cloned from a <template> (supplier contacts). Container
// declares data-template-rows="<template id>"; the trigger button declares
// data-add-template-row; each row declares data-template-row and its remove
// button data-remove-template-row. Re-binds on htmx:afterSwap.
(function () {
  function bindRowSource(container) {
    var tplId = container.getAttribute('data-template-rows');
    if (!tplId) return;
    var tpl = document.getElementById(tplId);
    if (!tpl) return;
    var addBtn = container.parentElement.querySelector('[data-add-template-row]');
    if (addBtn) {
      addBtn.addEventListener('click', function () {
        container.appendChild(tpl.content.cloneNode(true));
      });
    }
    container.addEventListener('click', function (e) {
      var btn = e.target.closest && e.target.closest('[data-remove-template-row]');
      if (btn) {
        var row = btn.closest('[data-template-row]');
        (row || btn.parentElement).remove();
      }
    });
  }

  function init(scope) {
    (scope || document).querySelectorAll('[data-template-rows]').forEach(bindRowSource);
  }

  init(document);
  document.addEventListener('htmx:afterSwap', function (e) {
    var elt = e.detail && e.detail.elt;
    if (elt) init(elt);
  });
})();