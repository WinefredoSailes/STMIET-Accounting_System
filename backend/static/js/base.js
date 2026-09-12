/*
 * base.js — STMIET Accounting shared UI behavior.
 * Loaded by ui/base.html on every page.
 *
 * NOTE: functions are intentionally global (not wrapped in an IIFE or module)
 * because inline handlers in templates call them directly:
 *   - toggleSidebar()  -> base.html  onClick handlers
 *   - enhanceSearchable()/openSearchable()/... -> DOM state the rfp_form
 *     line-grid clone logic relies on
 */

// ---- HTMX wiring: inject CSRF on every request, block swaps on errors ----
document.addEventListener('htmx:configRequest', function (e) {
  var meta = document.querySelector('meta[name="csrf-token"]');
  if (meta) e.detail.headers['X-CSRFToken'] = meta.getAttribute('content');
});
document.addEventListener('htmx:beforeSwap', function (e) {
  if (e.detail.xhr.status >= 400) e.detail.shouldSwap = false;
});

// ---- Toast notification handler (triggered by HX-Trigger: showToast) ----
document.body.addEventListener('showToast', function (e) {
  if (!e.detail) return;
  var d = document.createElement('div');
  d.className = 'fixed top-4 right-4 z-50 max-w-sm rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 shadow-lg';
  d.textContent = typeof e.detail === 'string' ? e.detail : (e.detail.message || '');
  document.body.appendChild(d);
  setTimeout(function () { d.remove(); }, 4200);
});

// ---- Sidebar toggle (mobile + desktop close) ----
function toggleSidebar(force) {
  var sb = document.getElementById('sidebar');
  var bd = document.getElementById('sb-backdrop');
  if (!sb) return;
  var open = typeof force === 'boolean' ? force : !sb.classList.contains('translate-x-0');
  sb.classList.toggle('translate-x-0', open);
  sb.classList.toggle('-translate-x-full', !open);
  if (bd) bd.classList.toggle('hidden', !open);
}
var sbNav = document.getElementById('sidebar-nav');
if (sbNav) {
  sbNav.addEventListener('click', function () {
    if (window.innerWidth < 1024) toggleSidebar(false);
  });
}

// ---- Searchable combobox: turns any <select data-searchable> into a
// filterable dropdown panel while keeping the native select (name/value)
// for form submission. The panel is rendered as a child of <body> and
// positioned with fixed coordinates, so opening it can never shift the
// table rows/columns it belongs to. Delegated listeners keep dynamically
// cloned "add line" rows working. ----
var sbCounter = 0;

function openSearchable(wrap) {
  var panel = buildPanel(wrap);
  positionPanel(wrap, panel);
  panel.classList.remove('hidden');
  var query = panel.querySelector('.searchable-query');
  query.value = '';
  if (searchableMode(panel) === 'async') {
    applyAsyncFilter(wrap, panel, '');
  } else {
    applyFilter(panel);
  }
  query.focus();
  wrap.querySelector('.searchable-trigger').classList.add('border-indigo-500');
}

function closeSearchable(wrap) {
  var panel = document.getElementById('sb-panel-' + wrap.dataset.sbId);
  if (panel) panel.remove();
  wrap.querySelector('.searchable-trigger').classList.remove('border-indigo-500');
}

function buildPanel(wrap) {
  var old = document.getElementById('sb-panel-' + wrap.dataset.sbId);
  if (old) old.remove();
  var panel = document.createElement('div');
  panel.id = 'sb-panel-' + wrap.dataset.sbId;
  panel.className = 'searchable-panel hidden z-50 rounded-lg border border-slate-200 bg-white shadow-lg overflow-hidden';
  panel.style.position = 'fixed';
  panel.sbWrap = wrap;

  var searchRow = document.createElement('div');
  searchRow.className = 'flex items-center gap-2 border-b border-slate-200 px-3 py-2';
  var query = document.createElement('input');
  query.type = 'text';
  query.className = 'searchable-query w-full text-sm focus:outline-none';
  query.placeholder = wrap.querySelector('select').dataset.searchPlaceholder || 'Search by code or title…';
  query.autocomplete = 'off';
  query.sbWrap = wrap;
  searchRow.appendChild(query);
  panel.appendChild(searchRow);

  var list = document.createElement('div');
  list.className = 'searchable-list max-h-56 overflow-y-auto py-1';
  list.dataset.mode = wrap.querySelector('select').dataset.searchUrl ? 'async' : 'local';
  panel.appendChild(list);
  document.body.appendChild(panel);
  renderLocalItems(panel);
  return panel;
}

// ---- Local mode (default): all options are already in the <select>. ----
function renderLocalItems(panel) {
  var list = panel.querySelector('.searchable-list');
  list.innerHTML = '';
  var select = panel.sbWrap.querySelector('select');
  for (var i = 0; i < select.options.length; i++) {
    var opt = select.options[i];
    if (opt.value === '' && !opt.selected) continue; // hide the placeholder when empty
    var item = searchableItem(panel.sbWrap, opt.value, opt.textContent);
    list.appendChild(item);
  }
}

// ---- Async mode: options are fetched from data-search-url as the user
// types, matching the current query against both code and name. Selected
// values are merged into the native <select> so form submission keeps
// working while the picker exposes a fresh server-side result set. ----
function searchableItem(wrap, value, text, code) {
  var item = document.createElement('div');
  item.className = 'searchable-item flex items-baseline gap-2 px-3 py-1.5 text-sm cursor-pointer hover:bg-indigo-50';
  item.dataset.value = value;
  item.title = text;  // full name on hover for long/truncated titles
  item.sbWrap = wrap;
  var codeEl = document.createElement('span');
  codeEl.className = 'font-mono text-xs text-slate-500';
  codeEl.textContent = code || value;
  var title = document.createElement('span');
  title.className = 'text-slate-700 truncate';
  // Async results carry text like "61100 — Cost of Sales"; strip the code
  // prefix when it is duplicated so the title reads as the name only.
  var prefix = (code || value) + ' — ';
  title.textContent = (text.indexOf(prefix) === 0) ? text.slice(prefix.length) : text;
  item.appendChild(codeEl);
  item.appendChild(title);
  return item;
}

function renderAsyncItems(panel, results, selectedValue, selectedText) {
  var list = panel.querySelector('.searchable-list');
  panel.sbWrap._abort = null;
  list.innerHTML = '';
  var select = panel.sbWrap.querySelector('select');
  // Preserve placeholder/empty options (e.g. "— none —" on optional
  // fields) across async rebuilds so they stay selectable.
  var blanks = [];
  select.querySelectorAll('option[value=""]').forEach(function (o) { blanks.push(o); });
  select.innerHTML = '';
  blanks.forEach(function (o) { select.appendChild(o); });
  if (selectedValue) {
    var keep = document.createElement('option');
    keep.value = selectedValue;
    keep.textContent = selectedText;
    select.appendChild(keep);
  }
  results.forEach(function (r) {
    var opt = document.createElement('option');
    opt.value = r.value;
    opt.textContent = r.text;
    select.appendChild(opt);
    list.appendChild(searchableItem(panel.sbWrap, r.value, r.text, r.code));
  });
  // Restore the pre-search selection so closing the panel without picking
  // (e.g. Escape) never wipes a filled row.
  if (selectedValue) select.value = selectedValue;
  if (!results.length) {
    var empty = document.createElement('div');
    empty.className = 'px-3 py-4 text-center text-xs text-slate-400';
    empty.textContent = 'No matches';
    list.appendChild(empty);
  }
}

function applyAsyncFilter(wrap, panel, query) {
  var url = new URL(wrap.querySelector('select').dataset.searchUrl, window.location.origin);
  url.searchParams.set('q', query);
  var selected = wrap.querySelector('select').value;
  if (selected) url.searchParams.set('selected', selected);
  var selectedText = wrap.querySelector('.searchable-label').textContent;

  if (wrap._abort) wrap._abort.abort();
  var ctrl = new AbortController();
  wrap._abort = ctrl;
  var listEl = panel.querySelector('.searchable-list');
  listEl.innerHTML = '';
  var loading = document.createElement('div');
  loading.className = 'px-3 py-4 text-center text-xs text-slate-400';
  loading.textContent = 'Searching…';
  listEl.appendChild(loading);

  // Pickers declare which identifier they submit via data-search-value
  // ("code" for RFP/PCV lines, "id" for JE/CV/AR/asset/bank forms).
  var valueField = wrap.querySelector('select').dataset.searchValue || 'code';
  var req = fetch(url, { signal: ctrl.signal, headers: { 'X-Requested-With': 'XMLHttpRequest' } });
  req.then(function (resp) { return resp.json(); })
     .then(function (results) {
       if (wrap._abort !== ctrl) return; // stale response
       var normalized = (results || []).map(function (r) {
         var v = (valueField === 'id') ? r.id : r.code;
         return { value: String(v), code: String(r.code), text: String(r.text || r.code) };
       });
       renderAsyncItems(panel, normalized, selected, selectedText);
     })
     .catch(function () { /* aborted or network error — keep prior state */ });
}

function searchableMode(panel) {
  var list = panel ? panel.querySelector('.searchable-list') : null;
  return list ? list.dataset.mode : 'local';
}

function positionPanel(wrap, panel) {
  var rect = wrap.querySelector('.searchable-trigger').getBoundingClientRect();
  panel.style.top = (rect.bottom + 4) + 'px';
  panel.style.left = rect.left + 'px';
  panel.style.width = rect.width + 'px';
  // Cap very wide triggers (e.g. account pickers spanning a wide cell) so the
  // dropdown never runs off-screen; long option titles truncate + hover shows
  // the full text via the item tooltip.
  panel.style.maxWidth = Math.max(320, Math.min(window.innerWidth - 24, 480)) + 'px';
}

function positionOpenPanels() {
  var panels = document.querySelectorAll('.searchable-panel:not(.hidden)');
  for (var i = 0; i < panels.length; i++) {
    positionPanel(panels[i].sbWrap, panels[i]);
  }
}
document.addEventListener('scroll', positionOpenPanels, true);
window.addEventListener('resize', positionOpenPanels);

function applyFilter(panel) {
  var q = panel.querySelector('.searchable-query').value.trim().toLowerCase();
  var items = panel.querySelectorAll('.searchable-item');
  var first = null;
  for (var i = 0; i < items.length; i++) {
    var match = items[i].textContent.toLowerCase().indexOf(q) !== -1;
    items[i].hidden = !match;
    items[i].classList.remove('bg-indigo-50');
    if (match && first === null) first = items[i];
  }
  if (first) first.classList.add('bg-indigo-50');
}

function selectItem(wrap, item) {
  if (!item || item.hidden) return;
  var select = wrap.querySelector('select');
  select.value = item.dataset.value;
  select.dispatchEvent(new Event('change', { bubbles: true }));
  var label = wrap.querySelector('.searchable-label');
  var chosen = select.selectedOptions.length ? select.selectedOptions[0].textContent : '— select —';
  label.textContent = chosen;
  label.classList.toggle('text-slate-700', !!select.value);
  label.classList.toggle('text-slate-400', !select.value);
  closeSearchable(wrap);
  wrap.querySelector('.searchable-trigger').focus();
}

function activeItem(panel) {
  var items = panel.querySelectorAll('.searchable-item:not([hidden])');
  for (var i = 0; i < items.length; i++) {
    if (items[i].classList.contains('bg-indigo-50')) return items[i];
  }
  return items.length ? items[0] : null;
}

function moveActive(panel, dir) {
  var items = Array.prototype.slice.call(panel.querySelectorAll('.searchable-item:not([hidden])'));
  if (!items.length) return;
  var cur = activeItem(panel);
  var idx = Math.max(0, items.indexOf(cur));
  var next = items[Math.min(items.length - 1, idx + dir)];
  for (var i = 0; i < items.length; i++) items[i].classList.remove('bg-indigo-50');
  next.classList.add('bg-indigo-50');
  next.scrollIntoView({ block: 'nearest' });
}

function enhanceSearchable(root) {
  var list = (root || document).querySelectorAll('select[data-searchable]');
  for (var i = 0; i < list.length; i++) {
    var select = list[i];
    if (select.dataset.searchEnhanced) continue;
    select.dataset.searchEnhanced = '1';

    var wrap = document.createElement('div');
    wrap.className = 'searchable-wrap relative';
    wrap.dataset.sbId = ++sbCounter;

    var compact = select.hasAttribute('data-search-compact');
    var trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'searchable-trigger w-full rounded-md border border-slate-300 bg-white text-left flex items-center justify-between gap-2 hover:border-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500' +
      (compact ? ' px-2 py-1.5 text-xs' : ' px-3 py-2 text-sm');
    var label = document.createElement('span');
    label.className = 'searchable-label truncate';
    var chosen = select.selectedOptions.length ? select.selectedOptions[0].textContent : '— select —';
    label.textContent = chosen;
    label.classList.toggle('text-slate-700', !!select.value);
    label.classList.toggle('text-slate-400', !select.value);
    trigger.appendChild(label);
    var chevron = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    chevron.setAttribute('class', 'h-4 w-4 text-slate-400 shrink-0');
    chevron.setAttribute('viewBox', '0 0 20 20');
    chevron.setAttribute('fill', 'currentColor');
    var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('fill-rule', 'evenodd');
    path.setAttribute('d', 'M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z');
    path.setAttribute('clip-rule', 'evenodd');
    chevron.appendChild(path);
    trigger.appendChild(chevron);

    wrap.appendChild(trigger);
    select.classList.add('hidden');
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
  }
}

document.addEventListener('click', function (e) {
  // Items live inside their panel, so item hits MUST be handled before the
  // panel check — otherwise every click on a result is swallowed and the
  // picker would be unusable with the mouse (keyboard Enter still worked).
  var item = e.target.closest ? e.target.closest('.searchable-item') : null;
  if (item) {
    selectItem(item.sbWrap, item);
    return;
  }
  if (e.target.closest('.searchable-panel')) return;
  var wrap = e.target.closest ? e.target.closest('.searchable-wrap') : null;
  var panels = document.querySelectorAll('.searchable-panel:not(.hidden)');
  if (wrap) {
    for (var i = 0; i < panels.length; i++) {
      if (wrap.dataset.sbId !== panels[i].sbWrap.dataset.sbId) panels[i].remove();
    }
    if (e.target.closest('.searchable-trigger')) {
      var panel = document.getElementById('sb-panel-' + wrap.dataset.sbId);
      if (!panel || panel.classList.contains('hidden')) openSearchable(wrap);
      else closeSearchable(wrap);
    }
  } else {
    for (var j = 0; j < panels.length; j++) panels[j].remove();
  }
});

document.addEventListener('input', function (e) {
  if (e.target.classList && e.target.classList.contains('searchable-query')) {
    var panel = e.target.closest('.searchable-panel');
    if (searchableMode(panel) === 'async') applyAsyncFilter(panel.sbWrap, panel, e.target.value.trim());
    else applyFilter(panel);
  }
});

document.addEventListener('keydown', function (e) {
  if (!e.target.classList) return;
  if (e.target.classList.contains('searchable-trigger')) {
    if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
      e.preventDefault();
      openSearchable(e.target.closest('.searchable-wrap'));
    }
  } else if (e.target.classList.contains('searchable-query')) {
    var wrap = e.target.sbWrap;
    var panel = e.target.closest('.searchable-panel');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      moveActive(panel, 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      moveActive(panel, -1);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      var active = activeItem(panel);
      if (active) selectItem(wrap, active);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      closeSearchable(wrap);
      wrap.querySelector('.searchable-trigger').focus();
    }
  }
});

enhanceSearchable(document);

// ---- Auto-growing textareas: any <textarea data-autogrow> keeps its height
// at the content height (one line when empty) instead of a fixed scroll box,
// matching the JE line-description behavior. The tooltip mirrors the value so
// long text stays hover-readable in tight rows. enhanceAutogrow re-runs on
// every DOM mutation (row clones, htmx swaps) through the observer below. ----
function resizeAutogrow(ta) {
  ta.style.height = 'auto';
  ta.style.height = ta.scrollHeight + 'px';
  ta.title = ta.value;
}
function autogrowField(ta) {
  if (!ta || ta.dataset.autogrown) return;
  ta.dataset.autogrown = '1';
  ta.style.resize = 'none';
  ta.style.overflow = 'hidden';
  ta.addEventListener('input', function () { resizeAutogrow(ta); });
  resizeAutogrow(ta);
}
function enhanceAutogrow(root) {
  var list = (root || document).querySelectorAll('textarea[data-autogrow]');
  for (var i = 0; i < list.length; i++) autogrowField(list[i]);
}
enhanceAutogrow(document);
var searchObserver = new MutationObserver(function () {
  enhanceSearchable(document);
  enhanceAutogrow(document);
});
searchObserver.observe(document.body, { childList: true, subtree: true });

// ---- Report format dropdown (ui/partials/report_toolbar.html): on change,
// reload the current URL with ?format=<ext> preserving the base action. ----
function tryFormatRedirect(select) {
  var form = select.closest('form');
  var base = form ? form.action : window.location.pathname;
  var url = base + (base.indexOf('?') === -1 ? '?' : '&') + 'format=' + encodeURIComponent(select.value);
  window.location.href = url;
}
document.addEventListener('change', function (e) {
  if (e.target.matches && e.target.matches('select[data-format-redirect]')) {
    tryFormatRedirect(e.target);
  } else if (e.target.matches && e.target.matches('select[data-submit-on-change]')) {
    var form = e.target.closest('form');
    if (form) form.submit();
  }
});

// ---- Print templates (cv_print, statement_print, etc.): after printing from
// a dedicated print window, close it. Global so templates don't each inline
// `window.onafterprint`. ----
window.onafterprint = function () {
  window.close();
};