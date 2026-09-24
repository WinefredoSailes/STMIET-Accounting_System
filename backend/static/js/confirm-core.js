/*
 * confirm-core.js — pure decision logic for the universal action confirmation
 * (no DOM access; the DOM glue lives in base.js).
 *
 * Rule set (mirrored by test_confirm_ui.py for the templates it tags):
 *   1. GET forms never confirm; forms flagged data-confirm-off never confirm.
 *   2. An explicit data-confirm text always wins.
 *   3. A form that carries its own note/reason/comment textarea IS the
 *      confirmation step (reject-with-note, reversal-request modals) — never
 *      stack a second dialog on top of it.
 *   4. Otherwise the submit button's first word decides: every state-changing
 *      verb confirms (approve, reject, submit, post, save, create, add,
 *      issue, record, close, void, ...). Pure reads and auth controls
 *      (Apply/Filter/Search/Export/Run/Generate/Sign in) submit straight
 *      through, so report filters stay friction-free.
 */
(function (root) {
  'use strict';

  var VERB_MESSAGES = {
    approve: 'Are you sure you want to approve this? It will be signed under your name and move to the next step.',
    check: 'Are you sure you want to mark this as checked? Your verification signs this step and moves it to the next approver.',
    reject: 'Are you sure you want to reject this? The person who raised it will have to fix and resubmit.',
    return: 'Are you sure you want to return this? The preparer will see your note and must resubmit.',
    submit: 'Are you sure you want to submit this for approval?',
    revise: 'Are you sure you want to resubmit this? It re-enters the approval queue.',
    post: 'Are you sure you want to post this? Posted entries can no longer be edited — they must be reversed.',
    reverse: 'Are you sure you want to reverse this? A correcting reversing entry will be posted.',
    clear: 'Are you sure you want to clear this? The item will be marked as cleared.',
    close: 'Are you sure you want to close this? It cannot be taken back without reopening.',
    reopen: 'Are you sure you want to reopen this?',
    void: 'Are you sure you want to void this? The record stays on the register as voided.',
    delete: 'Are you sure you want to delete this? This cannot be undone.',
    cancel: 'Are you sure you want to cancel this?',
    lock: 'Are you sure you want to lock this?',
    unlock: 'Are you sure you want to unlock this?',
    deactivate: 'Are you sure? The account will stop working immediately and its holder will be signed out.',
    activate: 'Activate this account again?',
    reconcile: 'Are you sure you want to mark this line as reconciled against the bank statement?',
    save: 'Are you sure you want to save this? The information goes in exactly as entered.',
    create: 'Are you sure you want to create this? The record is saved exactly as entered.',
    update: 'Are you sure you want to save these changes?',
    add: 'Are you sure you want to add this?',
    issue: 'Are you sure you want to issue this? It enters the register and cannot simply be unsent.',
    record: 'Are you sure you want to record this? The entry goes on the books as filled in.',
    request: 'Are you sure you want to send this request?',
    mark: 'Are you sure you want to mark this?',
  };

  function firstWord(label) {
    return String(label || '').trim().split(/\s+/)[0].toLowerCase().replace(/[^a-z]/g, '');
  }

  // info: { method, label, confirm, hasNoteField, disabled }
  function messageFor(info) {
    if (!info || info.disabled) return null;
    if ((info.method || 'get') !== 'post') return null;
    if (info.confirm) return info.confirm;
    if (info.hasNoteField) return null;
    var msg = VERB_MESSAGES[firstWord(info.label)];
    return msg || null;
  }

  root.StmiConfirmCore = { VERB_MESSAGES: VERB_MESSAGES, firstWord: firstWord, messageFor: messageFor };
})(typeof window !== 'undefined' ? window : globalThis);
