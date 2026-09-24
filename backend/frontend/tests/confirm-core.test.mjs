/*
 * confirm-core.test.mjs — decision rules for the universal action-confirm
 * guard: which POSTs ask "are you sure?" (explicit text, workflow verbs)
 * and which submit straight through (saves, filters, note-forms, GETs).
 */

import test from 'node:test';
import assert from 'node:assert/strict';

await import(new URL('../../static/js/confirm-core.js', import.meta.url).href);
const { messageFor, firstWord } = globalThis.StmiConfirmCore;

function info(over) {
  return Object.assign({ method: 'post', label: '', confirm: null, hasNoteField: false, disabled: false }, over);
}

test('explicit data-confirm text always wins', () => {
  const msg = messageFor(info({ confirm: 'Post the whole batch to GL?', label: 'Post batch' }));
  assert.equal(msg, 'Post the whole batch to GL?');
});

test('workflow + create/save verbs auto-confirm on the button first word', () => {
  for (const label of [
    'Approve', 'Approve reversal', 'Approve (CNR — above ₱100k)', 'Check', 'Approve check',
    'Submit for checking', 'Submit for approval', 'Post', 'Post to General Journal',
    'Post batch (all members to GL)', 'Close PO (no further billings)', 'Close period',
    'Reject', 'Return RFP to preparer', 'Void', 'Delete', 'Deactivate', 'Reconcile',
    // create / save / edit actions (unified on request):
    'Save changes', 'Save draft', 'Create RFP (prepared)', 'Create billing (draft)',
    'Add', 'Issue check voucher — JE posts when cleared', 'Record Deposit',
    'Record disposal', 'Record fuel', 'Request replenishment', 'Revise & resubmit',
    'Mark cleared & post to GL', 'Mark done', 'Save notes',
  ]) {
    const msg = messageFor(info({ label }));
    assert.ok(msg, label + ' must confirm');
    assert.ok(msg.toLowerCase().indexOf('sure') !== -1, label + ' asks "are you sure"');
  }
});

test('read-only controls (filters, exports, auth) never confirm', () => {
  for (const label of [
    'Apply', 'Apply Filter', 'Filter', 'Search', 'Export', 'Extract', 'Generate',
    'Refresh', 'Run', 'Sign in', 'Sign out', '',
  ]) {
    assert.equal(messageFor(info({ label })), null, label + ' must NOT confirm');
  }
});

test('a form carrying its own note/reason textarea IS the confirmation', () => {
  assert.equal(messageFor(info({ label: 'Return RFP to preparer', hasNoteField: true })), null);
  assert.equal(messageFor(info({ label: 'Reject', hasNoteField: true })), null);
  // explicit text still overrides (e.g. one shared button, conditional copy)
  assert.ok(messageFor(info({ label: 'x', hasNoteField: true, confirm: 'Resubmit?' })), 'explicit wins over note-form rule');
});

test('GET forms and disabled forms never confirm', () => {
  assert.equal(messageFor(info({ label: 'Approve', method: 'get' })), null);
  assert.equal(messageFor(info({ label: 'Approve', disabled: true })), null);
});

test('data-confirm-off escape hatch is honored (base.js passes disabled)', () => {
  assert.equal(messageFor(info({ label: 'Approve', confirm: 'Approve?', disabled: true })), null);
});

test('missing/empty label with no explicit text never confirms', () => {
  assert.equal(messageFor(info({ label: '' })), null);
  assert.equal(messageFor(info({})), null);
  assert.equal(messageFor(null), null);
});
