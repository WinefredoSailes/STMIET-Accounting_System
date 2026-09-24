/*
 * confirm-base.test.mjs — runs the REAL base.js submit-guard/confirm wiring in
 * a vm sandbox with a hand-built DOM stub, and proves:
 *   - a workflow POST (Create RFP / Approve) is intercepted and blocked
 *     (e.preventDefault) with the shared confirm modal opened;
 *   - clicking "Yes, continue" re-submits the form (requestSubmit);
 *   - a non-action submit (Search/Filter) is NOT blocked;
 *   - a note/reason form is not stacked with a second confirm;
 *   - a hidden required searchable <select> surfaces its visible trigger
 *     (the "clicked Create, nothing happened" bug) instead of silently
 *     blocking the submit.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const CORE_SRC = readFileSync(new URL('../../static/js/confirm-core.js', import.meta.url), 'utf8');
const BASE_SRC = readFileSync(new URL('../../static/js/base.js', import.meta.url), 'utf8');

// ---- tiny DOM stub --------------------------------------------------------
function el(props) {
  const node = {
    tagName: 'DIV',
    children: [],
    dataset: {},
    style: {},
    textContent: '',
    value: '',
    name: '',
    id: '',
    attrs: {},
    hidden: false,
    offsetParent: {}, // visible by default
    _classes: new Set((props.className || '').split(/\s+/).filter(Boolean)),
    classList: {
      add(...c) { c.forEach((x) => node._classes.add(x)); },
      remove(...c) { c.forEach((x) => node._classes.delete(x)); },
      toggle(c, on) { if (on === undefined) on = !node._classes.has(c); on ? node._classes.add(c) : node._classes.delete(c); return on; },
      contains(c) { return node._classes.has(c); },
    },
    setAttribute(k, v) { node.attrs[k] = v; },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(node.attrs, k) ? node.attrs[k] : (k === 'class' ? node.className : null); },
    hasAttribute(k) { return Object.prototype.hasOwnProperty.call(node.attrs, k); },
    appendChild(c) { node.children.push(c); c.parentNode = node; return c; },
    replaceChild(c) { node.children = [c]; return c; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
    removeEventListener() {},
    focus() { node._focused = true; },
    matches() { return false; },
    closest(sel) { return node._closest ? node._closest(sel) : null; },
  };
  Object.assign(node, props);
  node.className = props.className || '';
  if (props.attrs) node.attrs = Object.assign({}, props.attrs);
  return node;
}

function makeSandbox() {
  const listeners = {};
  const created = [];
  const modalMsg = el({ id: 'action-confirm-msg' });
  const yesBtn = el({ attrs: {}, });
  const cancelBtn = el({});
  const noteWrap = el({ className: 'hidden' });
  const noteEl = el({ id: 'action-confirm-note' });
  const noteLabel = el({});
  noteWrap.querySelector = (s) => (s === 'label' ? noteLabel : null);
  const modal = el({ id: 'action-confirm', className: 'hidden' });
  modal.querySelector = (s) => (
    s === '#action-confirm-msg' ? modalMsg
      : s === '[data-confirm-yes]' ? yesBtn
        : s === '[data-confirm-cancel]' ? cancelBtn
          : s === '#action-confirm-note-wrap' ? noteWrap
            : s === '#action-confirm-note' ? noteEl : null
  );
  created.push(modal);

  const body = el({
    appendChild(c) { created.push(c); return c; },
    addEventListener() {},
    removeEventListener() {},
  });

  const sandbox = {
    console: { log() {}, warn() {}, error() {} },
    setTimeout: () => 0, clearTimeout() {},
    URL, AbortController: class { constructor() { this.signal = {}; } },
    MutationObserver: class { observe() {} },
    WeakSet: WeakSet,
    Event: class { constructor(t) { this.type = t; } },
    location: { origin: 'http://t', pathname: '/' },
    addEventListener() {}, removeEventListener() {},
    document: {
      body,
      activeElement: null,
      createElement(tag) { return el({ tagName: (tag || 'div').toUpperCase() }); },
      getElementById: (id) => (id === 'action-confirm' ? modal : null),
      addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
      removeEventListener() {},
      querySelector: () => null,
      querySelectorAll: () => [],
    },
  };
  const ctx = vm.createContext(sandbox);
  // Mimic the browser where window === globalThis, so `window.Foo` set by a
  // classic script is reachable as a bare global from the next script.
  vm.runInContext('globalThis.window = globalThis;', ctx);
  vm.runInContext(CORE_SRC, ctx, { filename: 'confirm-core.js' });
  vm.runInContext(BASE_SRC, ctx, { filename: 'base.js' });
  return { sandbox, listeners, modal, modalMsg, yesBtn, cancelBtn, noteWrap, noteEl, created };
}

function submitEvent(submitter, form) {
  return {
    type: 'submit',
    target: form,
    submitter,
    defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; },
  };
}

function makeForm(method, hasTextarea) {
  const form = el({ attrs: { method } });
  form.hasAttribute = (k) => k === 'method' || (method === 'post' && k === 'method');
  form.getAttribute = (k) => (k === 'method' ? method : null);
  form.querySelector = (sel) => {
    if (hasTextarea && sel.indexOf('textarea') !== -1) return { name: 'note' };
    return null;
  };
  form.requestSubmit = function (sub) { form._resubmittedWith = sub || null; form._native = 'requestSubmit'; };
  form.submit = function () { form._native = 'submit'; };
  return form;
}

function fire(listeners, type, ev) {
  (listeners[type] || []).forEach((fn) => fn(ev));
}

test('Create RFP submit is blocked and confirm modal opens', () => {
  const { sandbox, listeners, modal, modalMsg } = makeSandbox();
  const btn = el({ textContent: 'Create RFP (prepared)' });
  const form = makeForm('post', false);
  const ev = submitEvent(btn, form);
  fire(listeners, 'submit', ev);
  assert.equal(ev.defaultPrevented, true, 'submit blocked pending confirm');
  assert.equal(modal.classList.contains('hidden'), false, 'modal shown');
  assert.match(modalMsg.textContent, /create this/i);
  assert.equal(typeof sandbox.askConfirm, 'function');
});

test('confirming re-submits the same form', () => {
  const { listeners, yesBtn } = makeSandbox();
  const btn = el({ textContent: 'Approve' });
  const form = makeForm('post', false);
  const ev = submitEvent(btn, form);
  fire(listeners, 'submit', ev);
  assert.equal(ev.defaultPrevented, true);
  assert.equal(typeof yesBtn.onclick, 'function');
  yesBtn.onclick();
  assert.equal(form._native, 'requestSubmit', 're-submitted after confirm');
  assert.equal(form._resubmittedWith, btn, 'original submitter preserved');
});

test('read-only Filter submit is NOT blocked', () => {
  const { listeners, modal } = makeSandbox();
  const btn = el({ textContent: 'Apply Filter' });
  const form = makeForm('post', false);
  const ev = submitEvent(btn, form);
  fire(listeners, 'submit', ev);
  assert.equal(ev.defaultPrevented, false);
  assert.ok(modal.classList.contains('hidden'), 'modal stays closed');
});

test('reject-with-note form is not double-prompted', () => {
  const { listeners, modal } = makeSandbox();
  const btn = el({ textContent: 'Return RFP to preparer' });
  const form = makeForm('post', true); // has textarea[name=note]
  const ev = submitEvent(btn, form);
  fire(listeners, 'submit', ev);
  assert.equal(ev.defaultPrevented, false, 'note form IS the confirmation');
  assert.ok(modal.classList.contains('hidden'));
});

test('hidden required searchable select surfaces its trigger (nothing-happened fix)', () => {
  const { listeners, created } = makeSandbox();
  const trigger = el({ className: 'searchable-trigger' });
  const select = el({ tagName: 'SELECT', name: 'payee', id: 'id_payee', offsetParent: null });
  const wrap = el({});
  wrap.querySelector = (s) => (s === '.searchable-trigger' ? trigger : null);
  select.closest = (s) => (s === '.searchable-wrap' ? wrap : null);
  const ev = {
    type: 'invalid', target: select, defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; },
  };
  fire(listeners, 'invalid', ev);
  assert.equal(ev.defaultPrevented, true, 'own handler takes over from the silent native block');
  assert.ok(trigger.classList.contains('field-invalid'), 'trigger flagged red');
  assert.equal(trigger._focused, true, 'visible trigger focused');
  const hint = created.find((n) => n.id === 'hidden-invalid-hint');
  assert.ok(hint, 'hint element created');
});
