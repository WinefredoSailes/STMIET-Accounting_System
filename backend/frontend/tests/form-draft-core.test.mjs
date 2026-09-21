/*
 * form-draft-core.test.mjs — race & idempotency suite for the draft-autosave
 * decision logic (backend/static/js/form-draft-core.js), run with Node's
 * built-in test runner: `node --test tests/` (or `npm test` in backend/frontend).
 *
 * The module is DOM-free by design; the live DOM wiring (form-draft.js /
 * base.js) composes these decisions, so covering them here covers the
 * double-restore, stale-draft, validation-error and success-clear races.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

await import(new URL('../../static/js/form-draft-core.js', import.meta.url).href);
const core = globalThis.StmiDraftCore;
assert.ok(core, 'form-draft-core.js must register globalThis.StmiDraftCore');

const DAY = 24 * 60 * 60 * 1000;

function stateFixture() {
  return {
    headers: [
      { name: 'rfp_date', value: '2026-09-21' },
      { name: 'payee', value: '7', text: 'SUP-07 — Limdon', },
      { name: 'segment', value: '3' },
    ],
    grids: [[
      [
        { name: 'line_account', value: '61100', text: '61100 — Cost of Sales' },
        { name: 'line_segment', value: '3', text: 'DHPP' },
        { name: 'line_description', value: 'fuel haul' },
        { name: 'line_cost_center', value: 'OS' },
        { name: 'line_debit', value: '1,500.00' },
        { name: 'line_credit', value: '' },
      ],
      [
        { name: 'line_account', value: '20000', text: '20000 — A/Payables' },
        { name: 'line_segment', value: '3', text: 'DHPP' },
        { name: 'line_description', value: '' },
        { name: 'line_cost_center', value: '' },
        { name: 'line_debit', value: '' },
        { name: 'line_credit', value: '1,500.00' },
      ],
    ]],
  };
}

function draftFixture(overrides) {
  const s = stateFixture();
  return Object.assign(
    core.makeDraft(3, '/ap/rfps/new/', s, Date.now()),
    { headers: s.headers, grids: s.grids },
    overrides || {},
  );
}

test('draft key: deterministic, per-user and per-path isolated', () => {
  const k = core.draftKey(3, '/ap/rfps/new/');
  assert.equal(k, core.draftKey(3, '/ap/rfps/new/'));
  assert.ok(k.startsWith(core.DRAFT_PREFIX));
  assert.notEqual(k, core.draftKey(4, '/ap/rfps/new/'), 'another user must not share the draft');
  assert.notEqual(k, core.draftKey(3, '/journal/new/'), 'another form must not share the draft');
  assert.equal(core.draftKey(null, '/journal/new/'), core.draftKey(undefined, '/journal/new/'));
  assert.ok(core.draftKey('', '/x/').includes(':anon:'));
});

test('draft key: query scoping keeps CV basis picks separate', () => {
  const bare = core.draftKey(1, '/ap/cv/new/', false, '');
  const withRfp = core.draftKey(1, '/ap/cv/new/', true, '?rfp=7');
  const withOtherRfp = core.draftKey(1, '/ap/cv/new/', true, '?rfp=9');
  assert.notEqual(withRfp, withOtherRfp, 'drafts for different basis RFPs must not collide');
  assert.notEqual(withRfp, bare);
  // Without query scoping the same path shares one key regardless of search.
  assert.equal(core.draftKey(1, '/ap/cv/new/', false, '?rfp=7'), core.draftKey(1, '/ap/cv/new/'));
});

test('marker keys live in their own namespace, never equal to draft keys', () => {
  const k = core.draftKey(3, '/ap/rfps/new/');
  const mk = core.markerKeyFor(k);
  assert.ok(mk.startsWith(core.SUBMIT_PREFIX));
  assert.notEqual(mk, k);
  assert.notEqual(mk, core.SUBMIT_PREFIX, 'marker key must carry the draft key');
});

test('validateDraft accepts well-formed drafts', () => {
  assert.equal(core.validateDraft(draftFixture()), true);
  const sparse = core.makeDraft(1, '/p/', { headers: [{ name: 'a', value: '' }], grids: [[[], [{ name: 'b', value: 'x', checked: false, text: 't', coa: 'c' }]]] }, 1);
  assert.equal(core.validateDraft(sparse), true);
});

test('validateDraft rejects tampered / malformed payloads (no crash on restore)', () => {
  const good = draftFixture();
  const broken = [
    null,
    undefined,
    'a string',
    42,
    [],
    {},
    Object.assign({}, good, { v: 99 }),
    Object.assign({}, good, { updatedAt: 'nope' }),
    Object.assign({}, good, { updatedAt: NaN }),
    Object.assign({}, good, { headers: null }),
    Object.assign({}, good, { headers: [{ value: 'x' }] }),
    Object.assign({}, good, { headers: [{ name: 'a', value: 5 }] }),
    Object.assign({}, good, { headers: [{ name: 'a', value: 'x', text: 1 }] }),
    Object.assign({}, good, { headers: [{ name: 'a', value: 'x', checked: 'yes' }] }),
    Object.assign({}, good, { grids: [null] }),
    Object.assign({}, good, { grids: [[null]] }),
    Object.assign({}, good, { grids: [[[{ name: 'a', value: {} }]]] }),
  ];
  for (const b of broken) assert.equal(core.validateDraft(b), false, 'must reject ' + JSON.stringify(b));
});

test('isFresh: staleness window both directions (clock skew tolerated)', () => {
  const now = Date.now();
  assert.equal(core.isFresh(draftFixture({ updatedAt: now }), now), true);
  assert.equal(core.isFresh(draftFixture({ updatedAt: now - core.STALE_MS }), now), true);
  assert.equal(core.isFresh(draftFixture({ updatedAt: now - core.STALE_MS - 1 }), now), false);
  assert.equal(core.isFresh(draftFixture({ updatedAt: now + DAY }), now), true);
  assert.equal(core.isFresh(draftFixture({ updatedAt: now + 8 * DAY }), now), false);
  assert.equal(core.isFresh(draftFixture({ updatedAt: NaN }), now), false);
  assert.equal(core.isFresh(draftFixture(), NaN), false);
  assert.equal(core.isFresh({ v: 999 }, now), false);
});

test('isFresh: an 8-day-old draft is never restored onto a fresh form', () => {
  const now = Date.now();
  const old = draftFixture({ updatedAt: now - 8 * DAY });
  assert.equal(core.shouldRestore({
    alreadyRestored: false, exists: true, valid: true,
    fresh: core.isFresh(old, now), pristine: true,
  }), false);
});

test('sameState: value/text/checked/coa/row-count/order all significant', () => {
  const a = stateFixture();
  const clone = JSON.parse(JSON.stringify(a));
  assert.equal(core.sameState(a, clone), true);
  clone.headers[0].value = '2026-01-01';
  assert.equal(core.sameState(a, clone), false, 'header edit');
  clone.headers[0].value = a.headers[0].value;
  clone.grids[0][1][5].value = '99';
  assert.equal(core.sameState(a, clone), false, 'grid cell edit');
  clone.grids[0][1][5].value = '1,500.00';
  const moved = JSON.parse(JSON.stringify(a));
  moved.grids[0].reverse();
  assert.equal(core.sameState(a, moved), false, 'drag-reordered rows differ from the template');
  const dropped = JSON.parse(JSON.stringify(a));
  dropped.grids[0].pop();
  assert.equal(core.sameState(a, dropped), false, 'removed row changes the grid');
  const checked = [{ name: 'x', value: 'on', checked: true }];
  const unchecked = [{ name: 'x', value: 'on', checked: false }];
  assert.equal(core.sameState(checked, unchecked), false);
  const withCoa = [{ name: 'a', value: '1', coa: '61100' }];
  const noCoa = [{ name: 'a', value: '1' }];
  assert.equal(core.sameState(withCoa, noCoa), false, 'account-code display is part of the row state');
  const explicitUndef = [{ name: 'a', value: '1', coa: undefined }];
  assert.equal(core.sameState(noCoa, explicitUndef), true, 'missing key equals explicit undefined');
});

test('shouldRestore: full truth table — every gate must pass exactly once', () => {
  const pass = { alreadyRestored: false, exists: true, valid: true, fresh: true, pristine: true };
  assert.equal(core.shouldRestore(pass), true);
  for (const gate of Object.keys(pass)) {
    const flipped = Object.assign({}, pass);
    flipped[gate] = gate === 'alreadyRestored';
    assert.equal(core.shouldRestore(flipped), false, gate + ' must gate restore');
  }
  assert.equal(core.shouldRestore(null), false);
});

test('idempotency: a second restore attempt against the same page is refused', () => {
  const base = { exists: true, valid: true, fresh: true, pristine: true };
  // First pass (fresh page load): restore allowed.
  assert.equal(core.shouldRestore(Object.assign({ alreadyRestored: false }, base)), true);
  // After restore the glue marks the form; any re-entry (re-run of init)
  // must refuse, so cloned rows are never appended twice.
  assert.equal(core.shouldRestore(Object.assign({ alreadyRestored: true }, base)), false);
  // bfcache return path: DOM is dirty (user entries present) so even
  // without the flag the pristine gate refuses a duplicate restore.
  assert.equal(core.shouldRestore(Object.assign({}, base, { alreadyRestored: false, pristine: false })), false);
});

test('markerAction: success navigation clears, validation re-render keeps', () => {
  // POST failed -> same URL re-rendered: consume marker, keep draft.
  let a = core.markerAction('/ap/rfps/new/', '/ap/rfps/new/', false);
  assert.deepEqual(a, { clearDraft: false, removeMarker: true });
  // POST succeeded -> redirected to the detail page: clear the draft.
  a = core.markerAction('/ap/rfps/new/', '/ap/rfps/42/', false);
  assert.deepEqual(a, { clearDraft: true, removeMarker: true });
  // Session expired -> login page: touch nothing (draft AND marker survive
  // the login round-trip; the form re-render then consumes the marker).
  a = core.markerAction('/ap/rfps/new/', '/login/', true);
  assert.deepEqual(a, { clearDraft: false, removeMarker: false });
});

test('round-trip: captured state survives JSON and compares equal', () => {
  const s = stateFixture();
  const d = core.makeDraft(7, '/journal/new/', s, 123456789);
  assert.equal(d.v, core.VERSION);
  assert.equal(d.userId, '7');
  assert.equal(d.path, '/journal/new/');
  assert.equal(d.updatedAt, 123456789);
  const revived = JSON.parse(JSON.stringify(d));
  assert.equal(core.validateDraft(revived), true);
  assert.equal(core.sameState({ headers: revived.headers, grids: revived.grids }, s), true);
});

test('scenario: fast Back press (before debounce) still yields a restorable draft', () => {
  const now = Date.now();
  // pagehide/visibilitychange flush writes the draft synchronously at
  // now; the user lands on the list at now+5ms and returns to a freshly
  // fetched (pristine) form.
  const flushed = core.makeDraft(3, '/ap/rfps/new/', stateFixture(), now);
  const stored = JSON.parse(JSON.stringify(flushed));
  const later = now + 5;
  assert.equal(core.shouldRestore({
    alreadyRestored: false,
    exists: true,
    valid: core.validateDraft(stored),
    fresh: core.isFresh(stored, later),
    pristine: true,
  }), true);
});

test('scenario: abandoned draft outlives an unrelated navigation (no marker)', () => {
  // Without a submit marker nothing is cleared: leaving via the in-page
  // "back" link or the browser Back keeps the draft for the next visit.
  const key = core.draftKey(3, '/ap/rfps/new/');
  const marker = core.markerKeyFor(key);
  assert.ok(!key.startsWith(core.SUBMIT_PREFIX), 'a draft key is never treated as a marker');
  assert.ok(marker.startsWith(core.SUBMIT_PREFIX));
});

test('MAX_ROWS and MAX_BYTES guard pathological drafts', () => {
  assert.ok(core.MAX_ROWS >= 50, 'row cap generous but finite');
  assert.ok(core.MAX_BYTES >= 64 * 1024, 'byte cap within localStorage limits');
  assert.equal(core.DEBOUNCE_MS >= 100 && core.DEBOUNCE_MS <= 1000, true);
});
