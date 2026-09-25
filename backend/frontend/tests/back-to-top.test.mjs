/*
 * back-to-top.test.mjs — loads the REAL base.js back-to-top section in a
 * DOM stub: proves it is load-safe without the button, audits the pure
 * show/hide decision, and drives the live scroll/click handlers.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const CORE_SRC = readFileSync(new URL('../../static/js/confirm-core.js', import.meta.url), 'utf8');
const BASE_SRC = readFileSync(new URL('../../static/js/base.js', import.meta.url), 'utf8');

function elStub(classes) {
  const set = new Set(classes);
  const node = {
    classes: set,
    classList: {
      add: (...c) => c.forEach((x) => set.add(x)),
      remove: (...c) => c.forEach((x) => set.delete(x)),
      toggle: (c, on) => (on === undefined ? (set.has(c) ? set.delete(c) : set.add(c)) : (on ? set.add(c) : set.delete(c))),
      contains: (c) => set.has(c),
    },
    handlers: {},
    addEventListener(t, fn) { this.handlers[t] = fn; },
  };
  return node;
}

function loadBase({ withButton = false } = {}) {
  const noop = () => {};
  const winHandlers = {};
  const btn = withButton ? elStub(['hidden']) : null;
  const sandbox = {
    console: { log: noop, warn: noop, error: noop },
    setTimeout: () => 0, clearTimeout: noop,
    URL, AbortController: class { constructor() { this.signal = {}; } },
    MutationObserver: class { observe() {} },
    WeakSet, Event: class { constructor(t) { this.type = t; } },
    location: { origin: 'http://t', pathname: '/' },
    scrollY: 0,
    scrollTo: null,
    matchMedia: () => ({ matches: false }),
    addEventListener(t, fn) { (winHandlers[t] = winHandlers[t] || []).push(fn); },
    removeEventListener: noop,
    document: {
      body: { addEventListener: noop, appendChild: noop },
      activeElement: null,
      documentElement: { scrollTop: 0 },
      createElement: () => elStub([]),
      getElementById: (id) => (id === 'back-to-top' ? btn : null),
      addEventListener: noop,
      removeEventListener: noop,
      querySelector: () => null,
      querySelectorAll: () => [],
    },
  };
  sandbox.window = sandbox;
  const ctx = vm.createContext(sandbox);
  vm.runInContext(CORE_SRC, ctx, { filename: 'confirm-core.js' });
  vm.runInContext(BASE_SRC, ctx, { filename: 'base.js' });
  return { sandbox, btn, winHandlers };
}

test('loads safely on pages without the button element', () => {
  const { sandbox } = loadBase();
  assert.equal(typeof sandbox.backToTopShouldShow, 'function');
});

test('pure decision: hidden until past the first screenful', () => {
  const { sandbox } = loadBase();
  assert.equal(sandbox.backToTopShouldShow(0), false);
  assert.equal(sandbox.backToTopShouldShow(480), false, 'at threshold stays hidden');
  assert.equal(sandbox.backToTopShouldShow(481), true);
  assert.equal(sandbox.backToTopShouldShow(9999), true);
});

test('scroll shows/hides the button; click scrolls home', () => {
  const { sandbox, btn, winHandlers } = loadBase({ withButton: true });
  const scrollFns = winHandlers.scroll || [];
  assert.ok(scrollFns.length, 'scroll listener registered');
  sandbox.scrollY = 900;
  scrollFns.forEach((fn) => fn());
  assert.equal(btn.classes.has('hidden'), false, 'hidden removed');
  assert.equal(btn.classes.has('flex'), true, 'display flex added');

  sandbox.scrollY = 10;
  scrollFns.forEach((fn) => fn());
  assert.equal(btn.classes.has('hidden'), true, 're-hidden on scroll up');

  let scrolled = null;
  sandbox.scrollTo = (opts) => { scrolled = opts; };
  btn.handlers.click();
  // plain assert.deepEqual still trips on the vm's foreign prototype:
  assert.equal(scrolled.top, 0);
  assert.equal(scrolled.behavior, 'smooth');
});
