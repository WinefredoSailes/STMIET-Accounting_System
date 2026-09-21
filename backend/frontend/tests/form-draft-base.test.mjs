/*
 * form-draft-base.test.mjs — exercises the REAL base.js marker-reconciliation
 * loop (processDraftMarkers) in a vm sandbox with stubbed window/document and
 * in-memory storage, covering the clear-vs-keep race matrix:
 *   success navigation  -> draft cleared
 *   validation re-render-> draft kept
 *   login page          -> nothing consumed
 *   garbage marker      -> dropped silently
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const CORE_SRC = readFileSync(new URL('../../static/js/form-draft-core.js', import.meta.url), 'utf8');
const BASE_SRC = readFileSync(new URL('../../static/js/base.js', import.meta.url), 'utf8');

function memoryStorage(entries) {
  const map = new Map(Object.entries(entries || {}));
  const api = {
    _map: map,
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => { map.set(String(k), String(v)); },
    removeItem: (k) => { map.delete(k); },
  };
  Object.defineProperty(api, 'length', { get: () => map.size });
  Object.defineProperty(api, 'key', { value: (i) => Array.from(map.keys())[i] ?? null });
  return api;
}

function runBase({ pathname, hasPasswordField = false, sessionEntries = {}, localEntries = {} }) {
  const noop = () => {};
  const removedKeys = [];
  const localStorage = memoryStorage(localEntries);
  const origRemove = localStorage.removeItem;
  localStorage.removeItem = (k) => { removedKeys.push(k); origRemove(k); };
  const sessionStorage = memoryStorage(sessionEntries);
  const sandbox = {
    console: { log: noop, warn: noop, error: noop },
    setTimeout: () => 0, clearTimeout: noop,
    URL, AbortController: class { constructor() { this.signal = {}; } },
    MutationObserver: class { observe() {} },
    document: {
      querySelector: (sel) => (sel.indexOf('password') !== -1 && hasPasswordField ? {} : null),
      querySelectorAll: () => [],
      getElementById: () => null,
      addEventListener: noop,
      body: { addEventListener: noop, appendChild: noop },
    },
  };
  sandbox.window = {
    addEventListener: noop,
    removeEventListener: noop,
    innerWidth: 1280,
    location: { pathname, origin: 'http://test' },
    sessionStorage,
    localStorage,
    fetch: () => Promise.resolve({ json: () => Promise.resolve([]) }),
  };
  const ctx = vm.createContext(sandbox);
  vm.runInContext(CORE_SRC, ctx, { filename: 'form-draft-core.js' });
  // In browsers globalThis === window, so core's assignment is visible on
  // window; mirror that here.
  sandbox.window.StmiDraftCore = sandbox.StmiDraftCore;
  vm.runInContext(BASE_SRC, ctx, { filename: 'base.js' });
  return { sandbox, removedKeys, sessionStorage, localStorage };
}

test('base.js loads in the stub env and exposes processDraftMarkers', () => {
  const { sandbox } = runBase({ pathname: '/' });
  assert.equal(typeof sandbox.processDraftMarkers, 'function');
});

test('success navigation (detail page) clears the draft and the marker', () => {
  const { sandbox, removedKeys, sessionStorage } = runBase({
    pathname: '/ap/rfps/42/',
    sessionEntries: {
      'stmiet-draft-submit:stmiet-draft:3:/ap/rfps/new/':
        JSON.stringify({ key: 'stmiet-draft:3:/ap/rfps/new/', path: '/ap/rfps/new/' }),
    },
    localEntries: { 'stmiet-draft:3:/ap/rfps/new/': '{"v":1}' },
  });
  sandbox.processDraftMarkers();
  assert.deepEqual(removedKeys, ['stmiet-draft:3:/ap/rfps/new/']);
  assert.equal(sessionStorage.length, 0, 'marker consumed');
});

test('validation re-render (same path) keeps the draft, consumes the marker', () => {
  const { sandbox, removedKeys, sessionStorage } = runBase({
    pathname: '/ap/rfps/new/',
    sessionEntries: {
      'stmiet-draft-submit:stmiet-draft:3:/ap/rfps/new/':
        JSON.stringify({ key: 'stmiet-draft:3:/ap/rfps/new/', path: '/ap/rfps/new/' }),
    },
    localEntries: { 'stmiet-draft:3:/ap/rfps/new/': '{"v":1}' },
  });
  sandbox.processDraftMarkers();
  assert.deepEqual(removedKeys, [], 'draft must survive the error re-render for restore');
  assert.equal(sessionStorage.length, 0, 'marker consumed so a later unrelated nav does not clear it');
});

test('login screens never consume markers (session-expiry redirect must not wipe the draft)', () => {
  const { sandbox, removedKeys, sessionStorage } = runBase({
    pathname: '/login/',
    hasPasswordField: true,
    sessionEntries: {
      'stmiet-draft-submit:stmiet-draft:3:/ap/rfps/new/':
        JSON.stringify({ key: 'stmiet-draft:3:/ap/rfps/new/', path: '/ap/rfps/new/' }),
    },
    localEntries: { 'stmiet-draft:3:/ap/rfps/new/': '{"v":1}' },
  });
  sandbox.processDraftMarkers();
  assert.deepEqual(removedKeys, []);
  assert.equal(sessionStorage.length, 1, 'marker survives for the form re-render after login');
});

test('malformed markers are dropped without touching drafts', () => {
  const { sandbox, removedKeys, sessionStorage } = runBase({
    pathname: '/somewhere/',
    sessionEntries: {
      'stmiet-draft-submit:garbage': 'not json',
      'stmiet-draft-submit:partial': JSON.stringify({ path: '/x/' }),
    },
    localEntries: { 'stmiet-draft:3:/ap/rfps/new/': '{"v":1}' },
  });
  sandbox.processDraftMarkers();
  assert.deepEqual(removedKeys, []);
  assert.equal(sessionStorage.length, 0, 'junk markers cleaned');
});

test('non-marker storage entries are never inspected or removed', () => {
  const { sandbox, sessionStorage } = runBase({
    pathname: '/x/',
    sessionEntries: { 'unrelated-tab-data': 'keep me', 'other:stmiet-draft-submit:fake': '{}' },
  });
  sandbox.processDraftMarkers();
  assert.equal(sessionStorage.getItem('unrelated-tab-data'), 'keep me');
  assert.equal(sessionStorage.length, 2);
});

test('double execution is idempotent (markers already consumed)', () => {
  const { sandbox, removedKeys, sessionStorage } = runBase({
    pathname: '/ap/rfps/42/',
    sessionEntries: {
      'stmiet-draft-submit:stmiet-draft:3:/ap/rfps/new/':
        JSON.stringify({ key: 'stmiet-draft:3:/ap/rfps/new/', path: '/ap/rfps/new/' }),
    },
    localEntries: { 'stmiet-draft:3:/ap/rfps/new/': '{"v":1}' },
  });
  sandbox.processDraftMarkers();
  sandbox.processDraftMarkers();
  assert.deepEqual(removedKeys, ['stmiet-draft:3:/ap/rfps/new/'], 'cleared exactly once');
  assert.equal(sessionStorage.length, 0);
});
