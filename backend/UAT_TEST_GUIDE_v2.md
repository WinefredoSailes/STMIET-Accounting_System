# UAT Test Guide — Version 2

**Purpose:** Weekly regression & smoke-test checklist for the accounting system. Run after any template, view, service, or flag change.

---

## Quick Run

```powershell
cd D:\ACCOUNTING-SYSTEM\backend
& "D:\ACCOUNTING-SYSTEM\backend\.venv\Scripts\python.exe" -m pytest --nomigrations -q
```

**Target:** All 341 tests green. If any fail, investigate the specific test and the change that triggered it.

---

## Test Categories & Expectations

### 1. Approvals & Inbox (`apps/ui/tests.py::TestMyApprovals`)

| Test | What it covers | Expected |
|---|---|---|
| `test_cv_and_cash_short_queues` | CV → approved → clear chain; RFP full-approval chain → CONSO batch → cash-short worksheet | CV appears on approvals page; after `approve()` status = "approved"; after `clear()` status = "cleared"; cash-short approve works |
| `test_user_without_role_has_empty_inbox` | Staff without an actual step role sees empty state | Page renders 200; "Your queue is clear" message shown |
| `test_head_approves_all_rfps_during_uat` | `COO_REVIEW_ENABLED = False` (default): head approves every RFP one-click | No CNR gate; RFP advances through all steps ending with CONSO auto-assign |
| `test_coo_approves_above_100k_when_flag_on` | `COO_REVIEW_ENABLED = True` + RFP > ₱100k: COO/CNR required | RFP stalls at checked step until COO signs; then auto-assign CONSO |
| `test_cnr_gate_threshold` | CNR escalation at ₱100k boundary | Exactly ₱100,000 → COO required; ₱99,999 → head only |

### 2. Print Forms (`cv_print.html`, `rfp_print.html`)

| Feature | Check |
|---|---|
| Distribution table has **no spacer rows** (blank bordered lines) | Table height matches actual line count; form fits ≤ half A4 |
| Logo `stmiet-trans-logo.png` appears top-left in both forms | Verify rendered HTML has `<img src>`. |
| Section headers: CV pale green `#e2efda`; RFP peach `#fce4d6` | Inspect `bg-[#e2efda]` / `bg-[#fce4d6]` cells. |
| Auto-print on load: `window.print()` timeout 350ms | Page opens → print dialog appears (or check dev tools for the timeout). |
| `@media print` hides sidebar/header/chrome | Print preview: only the form table visible, no sidebars. |
| Signature row: 5 columns with correct labels | Prepared By / Requested By / Checked By / Approved By / Payment Received By. Missing values = blank, no layout breakage. |
| Footer: Print Name/Sign/Date ×3, then "Finance & Acctg. Head / Sign and Date", "COO", "Signature Over Printed Name/Date" | Visual match against VOUCHER-FORMS-CASH-AND-CHECK-10.xlsx reference. |

### 3. RFP Print Specifics

| Feature | Check |
|---|---|
| Header: logo + peach `#fce4d6` band | |
| Payee info table: NAME / POSITION/CONTACT NO / VENDOR NO / DEPARTMENT/ADDRESS / DATE OF REQUEST / AP NO | |
| Chart of Accounts: Dr/Cr rows + TOTAL + VAT 0.00 + NET INVOICE | |
| 3-column signature: Requested By / Recommending Approver or Checker / Approval=Accounting Mgr + Finance Mgr | |

### 4. RFP Form Header (create/revise)

| Change | Expected |
|---|---|
| Header grid: Payee (65%) / Date of Request (18%) / Cost Center / Ref (17%) | No standalone "Segment" field at header level. |
| Hidden `segment` field + sync JS from first distribution line's `line_segment` dropdown | `request.POST["segment"]` always contains a value (first line's segment). |
| Per-line Segment dropdowns in Distribution Charges table remain untouched | UI-only; data model/validation unchanged. |

### 5. COO / CONSO Flags (`config/settings/base.py`)

| Flag | Default | Effect |
|---|---|---|
| `COO_REVIEW_ENABLED` | `False` | UAT: head approves everything. Go-live: flip env true; COO/CNR required above ₱100k. |
| `CONSO_AUTO_ASSIGN` | `False` | UAT: manual CONSO batching. Flip true: fully-approved RFPs auto-place into newest open batch (CONSO-{YYYY}-{SEQ:02d}); total_amount recalculated (prior sum + new RFP, **double-count bug fixed**). |

### 6. CV Lifecycle

| Stage | State | Fields |
|---|---|---|
| `created` | Initial submission | `created_by` set; no `approved_by/approved_at` |
| `approved` | Head clicks "Approve" | `approved_by` = head user; `approved_at` set; **no** `signed_by/released_by` (migration 0009 removed them) |
| `cleared` | Head clicks "Clear" | `status = "cleared"`; JE posted to GL; no signed/released fields. |

**Migration:** `ap/migrations/0009_checkvoucher_approved_remove_signed_released.py` already applied to dev DB.

### 7. RFP Approval Chain (`RFPService.approve_head`, `approve_cnr`)

| Path | Outcome |
|---|---|
| `approve_head` (one-click fast-path) | Advances through remaining steps; breaks at `fin_approved` if `pending_final_check`; ends with `CONSOService.auto_assign`; stops at `acctg_approved` for revised RFPs without finance_notes. |
| `approve_cnr` | Also calls `auto_assign` after CNR gate. |
| `auto_assign` | Flag-gated; newest open batch (order `-conso_date, -batch_no`) or creates via `CONSO-{YYYY}-{SEQ:02d}`; `prior = sum(batch.rfps.all())` computed **before** `rfp.conso = batch` (fixes double-count). |

### 8. Settings & Seeds

- **Seed** (`seed_demo.py`): roles staff "Che Abellanosa", alywin "Alywin Aidan D. Baje", coo "Clyde N. Rebollos".
- `_approve_chain` / `_cv_chain` are flag-aware.
- Run `python manage.py seed_demo` to reset demo data.

---

## Current Setup Status (as of this session)

| Item | Status |
|---|---|
| **Tests** | 341/341 passing (`--nomigrations`) |
| **Flags** | `COO_REVIEW_ENABLED = False`, `CONSO_AUTO_ASSIGN = False` (both env.bool) |
| **Print forms** | CV + RFP rewritten: logo, colored headers, auto-print, `@media print` chrome hiding, spacer rows removed, signature rows `h-12` |
| **RFP form header** | Refactored: 3-col grid Payee/Date/Ref; hidden segment + sync JS; no header Segment dropdown |
| **Approvals list** | Actions column removed from `/approvals/` table |
| **CONSO auto-assign** | Double-count bug fixed: `prior = sum(batch.rfps.all())` computed before attaching new RFP |
| **CV lifecycle** | `signed_by/released_by` removed; `approved_by/approved_at` used; migration 0009 applied |
| **Tailwind CSS** | Rebuilt (`npm run build`) to include `grid-cols-12` / `md:grid-cols-12` |
| **Git** | All changes committed on `main`; working tree clean |

---

## How to Add a New UAT Check

1. **Identify the area** changed (template, view, service, flag, model).
2. **Open `apps/ui/tests.py`** and locate the relevant `TestMyApprovals` or new test class.
3. **Add or edit assertions** to verify the new behavior (page contains expected text, status codes, DB state).
4. **Run `pytest --nomigrations -q`** to confirm green.
5. **If UI-related**, manually verify the rendered HTML (view source, print preview).
6. **Commit** with a clear message; push if appropriate.

---

## Daily / Weekly Workflow

```powershell
# 1. Activate venv
. .venv\Scripts\Activate.ps1

# 2. (Optional) reset demo data
py manage.py seed_demo

# 3. Run full test suite
& python -m pytest --nomigrations -q

# 4. If any fail, investigate the specific test + change.
#    – UI changes: check rendered HTML, print preview.
#    – Service/flag changes: check CONSO totals, approval thresholds.

# 5. Commit & push if all green.
```