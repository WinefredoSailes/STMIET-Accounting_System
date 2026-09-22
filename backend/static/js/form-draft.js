/*
 * form-draft.js — client-side draft autosave for create forms (Back/Cancel
 * must never lose entries). Opt-in via `data-autosave` on the <form>
 * (rendered only on the non-editing branch of each template); `data-autosave-
 * user` scopes the key per login and `data-autosave-scope="query"` keeps a
 * draft per query string (CV picks its line data from ?rfp=<id>).
 *
 * Lifecycle (all storage access is try/catch so private-mode Safari simply
 * loses autosave, never the form):
 *   load  -> snapshot the pristine server-rendered state, then restore from
 *            localStorage ONLY if the draft is valid/fresh and the form is
 *            still pristine (idempotent: bfcache-restored pages are dirty).
 *   input -> debounced save; flushed on pagehide/visibilitychange (covers a
 *            fast Back press) and on submit.
 *   submit -> a sessionStorage marker records the form path. base.js (which
 *            loads after this core) clears the draft on the NEXT page load
 *            only when that load is a different path (= save succeeded);
 *            same-path re-render (= validation error) keeps the draft.
 *
 * Pure logic lives in form-draft-core.js (unit-tested with `node --test`).
 * Loaded from base.html AFTER {% block extra_js %} so line grids and the
 * per-screen inline scripts are already bound and receive the events this
 * module dispatches.
 */
(function () {
  'use strict';

  var core = window.StmiDraftCore;
  if (!core) return;

  var GRID_SELECTOR = 'tbody[data-line-grid], tbody[data-po-grid]';
  var FIELDS_SELECTOR = 'input[name], select[name], textarea[name], select[id]:not([name])';

  function lsGet(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) { try { window.localStorage.setItem(k, v); return true; } catch (e) { return false; } }
  function lsRemove(k) { try { window.localStorage.removeItem(k); } catch (e) { } }
  function ssSet(k, v) { try { window.sessionStorage.setItem(k, v); } catch (e) { } }

  function str(v) { return v === null || v === undefined ? '' : String(v); }
  function attr(s) { return String(s).replace(/"/g, '\\"'); }
  function inGrid(el) { return !!(el.closest && el.closest(GRID_SELECTOR)); }
  function selectedOption(el) {
    return el.selectedIndex >= 0 ? el.options[el.selectedIndex] : null;
  }

  // ---- capture (DOM -> state) -------------------------------------------

  function fieldItem(el) {
    var t = (el.type || '').toLowerCase();
    if (t === 'checkbox' || t === 'radio') {
      return { name: el.name, value: str(el.value), checked: !!el.checked };
    }
    if (el.tagName === 'SELECT') {
      var opt = selectedOption(el);
      var item = { name: el.name, value: str(el.value), text: opt ? (opt.textContent || '').trim() : '' };
      var row = el.closest ? el.closest('tr') : null;
      var coa = row ? row.querySelector('.coa-display') : null;
      if (coa) item.coa = (coa.textContent || '').trim();
      return item;
    }
    return { name: el.name, value: str(el.value) };
  }

  function capture(form) {
    var headers = [];
    form.querySelectorAll(FIELDS_SELECTOR).forEach(function (el) {
      if (el.name === 'csrfmiddlewaretoken' || el.disabled || inGrid(el)) return;
      var item = fieldItem(el);
      // Unnamed display-only pickers (JE/Billing party comboboxes) are keyed
      // by '#<id>' so restore can rehydrate the visible widget, not just the
      // hidden input its change listener writes.
      if (!item.name) {
        if (!el.id) return;
        item.name = '#' + el.id;
      }
      headers.push(item);
    });
    var grids = [];
    form.querySelectorAll(GRID_SELECTOR).forEach(function (tbody) {
      var rows = [];
      tbody.querySelectorAll('tr').forEach(function (tr) {
        if (rows.length >= core.MAX_ROWS) return;
        var cells = [];
        tr.querySelectorAll('input[name], select[name], textarea[name]').forEach(function (el) {
          if (el.name === 'csrfmiddlewaretoken') return;
          cells.push(fieldItem(el));
        });
        rows.push(cells);
      });
      grids.push(rows);
    });
    return { headers: headers, grids: grids };
  }

  // ---- apply (state -> DOM) ---------------------------------------------

  function hasOption(el, val) {
    for (var i = 0; i < el.options.length; i++) {
      if (el.options[i].value === val) return true;
    }
    return false;
  }

  function materializeOption(el, item) {
    var val = str(item.value);
    var opt = null;
    for (var i = 0; i < el.options.length; i++) {
      if (el.options[i].value === val) { opt = el.options[i]; break; }
    }
    if (!opt && val !== '') {
      opt = document.createElement('option');
      opt.value = val;
      el.appendChild(opt);
    }
    if (opt) {
      var text = item.text || val;
      if (text) opt.textContent = text;
      opt.selected = true;
    }
  }

  function refreshSearchableLabel(el) {
    var wrap = el.closest ? el.closest('.searchable-wrap') : null;
    if (!wrap) return;
    var label = wrap.querySelector('.searchable-label');
    if (!label) return;
    var opt = selectedOption(el);
    label.textContent = opt ? (opt.textContent || '').trim() : '— select —';
  }

  function setItem(el, item, dispatch) {
    var t = (el.type || '').toLowerCase();
    if (t === 'checkbox' || t === 'radio') {
      if (el.checked !== !!item.checked) {
        el.checked = !!item.checked;
        if (dispatch) el.dispatchEvent(new Event('change', { bubbles: true }));
      }
      return;
    }
    if (el.tagName === 'SELECT') {
      var want = str(item.value);
      var have = str(el.value);
      if (want === have) {
        // Never dispatch when the value is unchanged: the CV rfp picker's
        // inline onchange navigates to ?rfp=, which would loop on reload.
        if (want !== '' && !hasOption(el, want)) materializeOption(el, item);
        refreshSearchableLabel(el);
        return;
      }
      materializeOption(el, item);
      el.value = want;
      if (str(el.value) !== want) return;
      refreshSearchableLabel(el);
      if (dispatch) el.dispatchEvent(new Event('change', { bubbles: true }));
      return;
    }
    var next = str(item.value);
    if (el.value === next) return;
    el.value = next;
    if (el.tagName === 'TEXTAREA' && window.resizeAutogrow) window.resizeAutogrow(el);
    if (dispatch) el.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function findHeaderEl(form, name) {
    if (name.charAt(0) === '#') return form.querySelector('[id="' + attr(name.slice(1)) + '"]');
    var els = form.querySelectorAll('[name="' + attr(name) + '"]');
    for (var i = 0; i < els.length; i++) {
      if (!inGrid(els[i])) return els[i];
    }
    return null;
  }

  function applyHeaders(form, items) {
    (items || []).forEach(function (item) {
      var el = findHeaderEl(form, item.name);
      // data-draft-static fields are page basis, not form data (the CV RFP
      // picker, keyed by ?rfp=): restore must never overwrite them, or the
      // change dispatch would navigate the page to the draft's RFP (and can
      // loop). They are still captured so a per-basis draft stays intact.
      if (el && !el.hasAttribute('data-draft-static')) setItem(el, item, true);
    });
  }

  function clearClone(row) {
    row.querySelectorAll('input, textarea').forEach(function (i) {
      var t = (i.type || '').toLowerCase();
      if (t === 'checkbox' || t === 'radio') { i.checked = false; return; }
      i.value = '';
      i.removeAttribute('title');
      if (i.tagName === 'TEXTAREA') { i.style.height = 'auto'; i.removeAttribute('data-autogrown'); }
    });
    // Mirror line-grid.js cloneRow: async pickers start blank and unwrapped
    // so the MutationObserver in base.js re-wraps them on the appended row.
    row.querySelectorAll('select[data-search-url]').forEach(function (s) {
      s.removeAttribute('data-search-enhanced');
      var wrap = s.closest('.searchable-wrap');
      if (wrap) wrap.replaceWith(s);
      var blank = s.querySelector('option[value=""]');
      s.innerHTML = '';
      if (blank) s.appendChild(blank);
      s.selectedIndex = 0;
      s.classList.add('hidden');
    });
  }

  function renumberGrid(tbody) {
    var i = 0;
    tbody.querySelectorAll('tr').forEach(function (tr) {
      i += 1;
      var no = tr.querySelector('.line-no') || tr.querySelector('.po-line-no');
      if (no) no.textContent = String(i);
    });
  }

  function applyGrid(tbody, rows) {
    if (!Array.isArray(rows) || rows.length === 0) return;
    var trs = tbody.querySelectorAll('tr');
    for (var i = trs.length - 1; i >= 1; i--) trs[i].remove();
    var first = tbody.querySelector('tr');
    if (!first) return;
    for (var r = 1; r < rows.length; r++) {
      var clone = first.cloneNode(true);
      clearClone(clone);
      tbody.appendChild(clone);
    }
    var all = tbody.querySelectorAll('tr');
    rows.forEach(function (cells, ri) {
      var tr = all[ri];
      if (!tr) return;
      cells.forEach(function (item) {
        var el = tr.querySelector('[name="' + attr(item.name) + '"]');
        if (el) setItem(el, item, false);
      });
    });
    renumberGrid(tbody);
    // One bubbled change+input per grid: re-runs the line-grid totals, the
    // PO recalc, and any per-screen display syncers listening on the tbody.
    tbody.dispatchEvent(new Event('change', { bubbles: true }));
    tbody.dispatchEvent(new Event('input', { bubbles: true }));
    // Fix account-code displays after the listeners ran (their option text
    // may have been rewritten to the plain name during the original pick).
    rows.forEach(function (cells, ri) {
      var tr = all[ri];
      if (!tr) return;
      cells.forEach(function (item) {
        if (item.coa === undefined) return;
        var span = tr.querySelector('.coa-display');
        if (span) span.textContent = item.coa;
      });
    });
  }

  function applyGrids(form, grids) {
    var bodies = form.querySelectorAll(GRID_SELECTOR);
    (grids || []).forEach(function (rows, gi) {
      if (bodies[gi]) applyGrid(bodies[gi], rows);
    });
    if (window.enhanceSearchable) window.enhanceSearchable(document);
    if (window.enhanceAutogrow) window.enhanceAutogrow(document);
  }

  // ---- banner ------------------------------------------------------------

  function showBanner(form, key) {
    var host = form.parentNode;
    if (!host) return;
    var bar = document.createElement('div');
    bar.className = 'mb-3 flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-900';
    var msg = document.createElement('span');
    msg.textContent = 'Your unsaved entries were restored from the last visit to this form.';
    var act = document.createElement('div');
    act.className = 'flex items-center gap-3';
    var keep = document.createElement('button');
    keep.type = 'button';
    keep.className = 'font-medium text-slate-600 underline hover:text-slate-900';
    keep.textContent = 'Keep';
    keep.addEventListener('click', function () { bar.remove(); });
    var discard = document.createElement('button');
    discard.type = 'button';
    discard.className = 'font-semibold text-red-700 underline hover:text-red-900';
    discard.textContent = 'Discard draft';
    discard.addEventListener('click', function () { lsRemove(key); window.location.reload(); });
    act.appendChild(keep);
    act.appendChild(discard);
    bar.appendChild(msg);
    bar.appendChild(act);
    host.insertBefore(bar, form);
  }

  // ---- wiring ------------------------------------------------------------

  function initForm(form) {
    var userId = form.getAttribute('data-autosave-user') || 'anon';
    var scopeQuery = (form.getAttribute('data-autosave-scope') || '') === 'query';
    var key = core.draftKey(userId, window.location.pathname, scopeQuery, window.location.search);

    var initial = capture(form);
    var timer = null;

    function saveNow() {
      var state = capture(form);
      // Everything back at the server-rendered defaults (e.g. the user
      // cleared what was restored): keep nothing behind.
      if (core.sameState(state, initial)) { lsRemove(key); return; }
      var draft = core.makeDraft(userId, window.location.pathname, state, Date.now());
      var json;
      try { json = JSON.stringify(draft); } catch (e) { return; }
      if (json.length > core.MAX_BYTES) return;
      lsSet(key, json);
    }
    function schedule() {
      if (timer !== null) return;
      timer = window.setTimeout(function () { timer = null; saveNow(); }, core.DEBOUNCE_MS);
    }
    function flush() {
      if (timer !== null) { window.clearTimeout(timer); timer = null; }
      saveNow();
    }

    // Restore (once, and only onto the pristine form — see core.shouldRestore).
    var raw = lsGet(key);
    var draft = null;
    if (raw) { try { draft = JSON.parse(raw); } catch (e) { draft = null; } }
    var valid = core.validateDraft(draft);
    if (raw && !valid) lsRemove(key);
    if (core.shouldRestore({
      alreadyRestored: form.dataset.draftRestored === '1',
      exists: !!raw && valid,
      valid: valid,
      fresh: core.isFresh(draft, Date.now()),
      pristine: core.sameState(capture(form), initial)
    })) {
      form.dataset.draftRestored = '1';
      // Broadcast a restore-in-progress flag so any inline listeners (e.g.
      // the CV ?rfp= picker's onchange navigation) ignore programmatic
      // change events fired while we repopulate the form.
      var prevRestoring = window.StmiDraftRestoring;
      window.StmiDraftRestoring = true;
      try {
        applyHeaders(form, draft.headers);
        applyGrids(form, draft.grids);
        showBanner(form, key);
      } finally {
        window.StmiDraftRestoring = prevRestoring;
      }
    }

    form.addEventListener('input', schedule);
    form.addEventListener('change', schedule);
    form.addEventListener('submit', function () {
      flush();
      ssSet(core.markerKeyFor(key), JSON.stringify({ key: key, path: window.location.pathname }));
    });
    // bfcache-friendly flush hooks only (pagehide/visibilitychange keep the
    // back-forward cache intact; unload/beforeunload would block it).
    window.addEventListener('pagehide', flush);
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'hidden') flush();
    });
  }

  var forms = document.querySelectorAll('form[data-autosave]');
  for (var i = 0; i < forms.length; i++) {
    if (forms[i].dataset.draftInit === '1') continue;
    forms[i].dataset.draftInit = '1';
    initForm(forms[i]);
  }
})();
