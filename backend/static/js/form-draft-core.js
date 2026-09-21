/*
 * form-draft-core.js — pure decision logic for client-side form draft
 * autosave (no DOM access; the DOM glue lives in form-draft.js).
 *
 * The draft state shape produced/consumed here:
 *   {
 *     v: 1, userId: "3", path: "/ap/rfps/new/", updatedAt: <epoch ms>,
 *     headers: [ {name, value, text?, checked?, coa?} ],
 *     grids:   [ [ [ {name, value, text?, checked?, coa?}, ... ]  // cells of a row
 *                  , ... ] ]                                     // rows of a tbody
 *   }
 *
 * Loaded as a classic <script> before base.js (so base.js can process submit
 * markers) and imported directly by `node --test` for race/idempotency tests.
 */
(function (root) {
  'use strict';

  var DRAFT_PREFIX = 'stmiet-draft:';
  var SUBMIT_PREFIX = 'stmiet-draft-submit:';
  var VERSION = 1;
  var STALE_MS = 7 * 24 * 60 * 60 * 1000;
  var DEBOUNCE_MS = 400;
  var MAX_BYTES = 200 * 1024;
  var MAX_ROWS = 200;

  /* Draft storage key: per user (shared terminals must not cross-restore)
   * and per form path. CV opts into includeQuery so ?rfp=<id> pages keep a
   * draft per selected basis document and never clobber a fresh pick. */
  function draftKey(userId, pathname, includeQuery, search) {
    var path = String(pathname || '');
    if (includeQuery && search) path += String(search);
    var uid = (userId === null || userId === undefined || userId === '') ? 'anon' : String(userId);
    return DRAFT_PREFIX + uid + ':' + path;
  }

  function markerKeyFor(key) {
    return SUBMIT_PREFIX + key;
  }

  function makeDraft(userId, pathname, state, nowMs) {
    var uid = (userId === null || userId === undefined || userId === '') ? null : String(userId);
    return {
      v: VERSION,
      userId: uid,
      path: String(pathname || ''),
      updatedAt: nowMs,
      headers: state.headers,
      grids: state.grids
    };
  }

  function validItem(it) {
    if (!it || typeof it !== 'object' || Object.prototype.toString.call(it) === '[object Array]') return false;
    if (typeof it.name !== 'string') return false;
    if (it.value !== null && typeof it.value !== 'string') return false;
    if (it.text !== undefined && typeof it.text !== 'string') return false;
    if (it.checked !== undefined && typeof it.checked !== 'boolean') return false;
    if (it.coa !== undefined && typeof it.coa !== 'string') return false;
    return true;
  }

  /* Defense against tampered / half-written / older-schema payloads: a
   * malformed draft is rejected (and removed) instead of crashing restore. */
  function validateDraft(d) {
    if (!d || typeof d !== 'object' || Object.prototype.toString.call(d) === '[object Array]') return false;
    if (d.v !== VERSION) return false;
    if (typeof d.updatedAt !== 'number' || !isFinite(d.updatedAt)) return false;
    if (Object.prototype.toString.call(d.headers) !== '[object Array]') return false;
    if (Object.prototype.toString.call(d.grids) !== '[object Array]') return false;
    var i, g, r, grid, row;
    for (i = 0; i < d.headers.length; i++) if (!validItem(d.headers[i])) return false;
    for (g = 0; g < d.grids.length; g++) {
      grid = d.grids[g];
      if (Object.prototype.toString.call(grid) !== '[object Array]') return false;
      for (r = 0; r < grid.length; r++) {
        row = grid[r];
        if (Object.prototype.toString.call(row) !== '[object Array]') return false;
        for (i = 0; i < row.length; i++) if (!validItem(row[i])) return false;
      }
    }
    return true;
  }

  /* Future-dated updatedAt (clock skew) is tolerated up to the same window;
   * anything further than STALE_MS in either direction is not restored. */
  function isFresh(d, nowMs) {
    if (!validateDraft(d)) return false;
    if (typeof nowMs !== 'number' || !isFinite(nowMs)) return false;
    var age = nowMs - d.updatedAt;
    if (age < 0) age = -age;
    return age <= STALE_MS;
  }

  function definedKeys(o) {
    var out = [];
    for (var k in o) {
      if (Object.prototype.hasOwnProperty.call(o, k) && o[k] !== undefined) out.push(k);
    }
    return out;
  }

  function nilish(v) {
    return v === undefined || v === null;
  }

  /* Order-sensitive deep equality over the captured-state data model. The
   * capture builder emits deterministic document-order arrays, so inequality
   * here means the user (or a script) changed the form since the snapshot. */
  function deepEqual(a, b) {
    if (a === b) return true;
    if (nilish(a) || nilish(b)) return nilish(a) && nilish(b);
    if (typeof a !== 'object' || typeof b !== 'object') return false;
    var aArr = Object.prototype.toString.call(a) === '[object Array]';
    var bArr = Object.prototype.toString.call(b) === '[object Array]';
    if (aArr !== bArr) return false;
    if (aArr) {
      if (a.length !== b.length) return false;
      for (var i = 0; i < a.length; i++) if (!deepEqual(a[i], b[i])) return false;
      return true;
    }
    var ka = definedKeys(a), kb = definedKeys(b);
    if (ka.length !== kb.length) return false;
    var inB = {};
    for (var j = 0; j < kb.length; j++) inB[kb[j]] = true;
    for (var m = 0; m < ka.length; m++) {
      var key = ka[m];
      if (!inB[key]) return false;
      if (!deepEqual(a[key], b[key])) return false;
    }
    return true;
  }

  function sameState(a, b) {
    return deepEqual(a, b);
  }

  /* Restore happens exactly once per page: only when a stored draft exists,
   * parses cleanly, is fresh, and the live form is still the untouched
   * server-rendered state (pristine). The pristine gate is what makes
   * restore idempotent: a bfcache-restored page (already showing typed
   * entries and cloned rows) is dirty, so a second restore is a no-op
   * instead of duplicating rows. */
  function shouldRestore(o) {
    if (!o) return false;
    if (o.alreadyRestored) return false;
    return !!(o.exists && o.valid && o.fresh && o.pristine);
  }

  /* Submit-marker reconciliation, run on every page load (base.js):
   *  - login screens never consume markers (a session-expiry redirect away
   *    from the form must not be mistaken for a successful save);
   *  - marker path === current path: the form re-rendered itself after a
   *    failed POST (validation error) — keep the draft, drop the marker;
   *  - marker path !== current path: we navigated away after submitting,
   *    i.e. the save succeeded — drop the draft and the marker. */
  function markerAction(markerPath, currentPath, isLoginPage) {
    if (isLoginPage) return { clearDraft: false, removeMarker: false };
    if (markerPath === currentPath) return { clearDraft: false, removeMarker: true };
    return { clearDraft: true, removeMarker: true };
  }

  root.StmiDraftCore = {
    DRAFT_PREFIX: DRAFT_PREFIX,
    SUBMIT_PREFIX: SUBMIT_PREFIX,
    VERSION: VERSION,
    STALE_MS: STALE_MS,
    DEBOUNCE_MS: DEBOUNCE_MS,
    MAX_BYTES: MAX_BYTES,
    MAX_ROWS: MAX_ROWS,
    draftKey: draftKey,
    markerKeyFor: markerKeyFor,
    makeDraft: makeDraft,
    validateDraft: validateDraft,
    isFresh: isFresh,
    sameState: sameState,
    shouldRestore: shouldRestore,
    markerAction: markerAction
  };
})(typeof globalThis !== 'undefined' ? globalThis : window);
