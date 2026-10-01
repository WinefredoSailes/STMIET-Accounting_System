"""Question catalog — the single source of truth for the 100-question program.

One row per question (A1..K100). ``phrases`` are the distinctive wordings that
fire the question; ``requires`` is a list of AND-ed requirements where each
item is a pipe-separated OR list of entity keys (``none`` always passes, and a
``word:<token>`` requirement passes when the token appears in the query). Only
entries with ``status == "ready"`` participate in routing; the rest exist here
as the spec, drive the matrix test, and ship with a ``handler=None``.

``needs-stub`` entries route to ``stubs.not_tracked`` (kept for future gaps);
Phase 3b capture fields make B18/B19/B24/G62/H71 real answers now.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CatalogEntry:
    qid: str
    category: str
    question: str
    phrases: tuple[str, ...]
    requires: tuple[str, ...] = ()
    handler: str | None = None
    screen: str = ""
    status: str = "ready"  # ready | projection | needs-stub | pending-external | write-deferred
    stub_kind: str = ""
    module: str = ""


#: (qid, question, phrases, requires, handler, screen, status)
def _e(qid, category, question, phrases, requires, handler, screen, status="ready", stub_kind="", module=None):
    return CatalogEntry(
        qid=qid, category=category, question=question,
        phrases=tuple(phrases), requires=tuple(requires),
        handler=handler, screen=screen, status=status,
        stub_kind=stub_kind, module=module or category.lower(),
    )


CATALOG: list[CatalogEntry] = [
    # ------------------------------------------------------------------ A
    _e("A1", "A", "Who is the supplier of this item?", ["who is the supplier", "supplier of this item", "which supplier supplies"], ("item_text",), "purchase_items.item_suppliers", "po_list"),
    _e("A2", "A", "Who did we purchase this item from?", ["who did we purchase", "who did we buy", "bought this item from", "purchase this item from"], ("item_text",), "purchase_items.item_suppliers", "po_list"),
    _e("A4", "A", "When did we purchase this item?", ["when did we purchase this item", "when did we buy this item", "when was this item purchased", "when was the item purchased"], ("item_text",), "purchase_items.item_history", "po_list"),
    _e("A5", "A", "When did we pay the supplier?", ["when did we pay", "when was the supplier paid", "when was payment made", "payment date of"], ("supplier",), "ap.supplier_payments", "cv_list"),
    _e("A6", "A", "How many units did we purchase?", ["how many units", "how many pieces", "quantity purchased", "units purchased", "units did we buy"], ("item_text",), "purchase_items.item_units", "po_list"),
    _e("A7", "A", "What was the unit cost?", ["unit cost", "unit price", "cost per unit", "price per unit"], ("item_text",), "purchase_items.item_prices", "po_list"),
    _e("A9", "A", "Latest price we paid for this item?", ["latest price", "most recent price", "last price we paid", "newest price"], ("item_text",), "purchase_items.item_prices", "po_list"),
    _e("A10", "A", "Previous price we paid for this item?", ["previous price", "price before", "earlier price"], ("item_text",), "purchase_items.item_prices", "po_list"),
    _e("A8", "A", "What was the total purchase cost?", ["total purchase cost", "total cost of this item", "total cost of the item", "how much did we spend on this item", "spent on this item"], ("item_text",), "purchase_items.item_totals_handler", "po_list"),
    _e("A3", "A", "How much did we pay for this item?", ["pay for this item", "paid for this item", "paid for the item", "cost us for this item"], ("item_text",), "purchase_items.item_paid", "po_list"),
    _e("A11", "A", "What suppliers have we purchased this item from?", ["suppliers have we purchased", "suppliers did we buy", "suppliers of this item"], ("item_text",), "purchase_items.item_suppliers", "po_list"),
    _e("A12", "A", "What items have we purchased from this supplier?", ["items have we purchased from", "items did we buy from", "what items from"], ("supplier",), "purchase_items.supplier_items_handler", "po_list"),
    _e("A13", "A", "Complete purchase history of this item", ["purchase history of this item", "what is the history of this item", "purchase history"], ("item_text",), "purchase_items.item_history", "po_list"),
    _e("A14", "A", "All payments made to this supplier", ["all payments made", "payments made to this supplier", "payments to this supplier"], ("supplier",), "ap.supplier_payments", "ap_ledger"),
    _e("A15", "A", "Is this purchase fully paid?", ["fully paid", "full payment", "complete payment", "fully settled"], ("po|rfp",), "purchase.fully_paid", "ap_aging"),

    # ------------------------------------------------------------------ B
    _e("B16", "B", "What Purchase Request relates to this purchase?", ["purchase request", "pr number", "pr no", "pr of this", "requisition"], ("po|rfp",), "purchase.pr_numbers", "po_list"),
    _e("B17", "B", "What Purchase Order relates to this purchase?", ["what purchase order", "po related", "po for this", "purchase order for this", "which purchase order"], ("po|rfp",), "purchase.po_of", "po_list"),
    _e("B18", "B", "What Receiving Report / Delivery Receipt relates to this purchase?", ["receiving report", "delivery receipt", "rr for this", "dr for this", "goods receipt"], ("po|rfp",), "purchase.rr_of", "po_list"),
    _e("B19", "B", "What Supplier Invoice relates to this purchase?", ["supplier invoice", "invoice from the supplier", "supplier's invoice", "si for this purchase"], ("po|rfp",), "purchase.supplier_invoice_of", "rfp_list"),
    _e("B20", "B", "What RFP relates to this purchase?", ["what rfp", "rfp related", "rfp for this", "which rfp"], ("po|rfp",), "purchase.rfp_of", "rfp_list"),
    _e("B21", "B", "What Check Voucher relates to this purchase?", ["what cv", "cv related", "check voucher for this", "what check voucher", "voucher for this purchase"], ("po|rfp",), "purchase.cv_of", "cv_list"),
    _e("B22", "B", "What check was issued for this purchase?", ["what check", "check issued for this", "check for this purchase", "check number of"], ("po|rfp",), "purchase.check_of", "cv_list"),
    _e("B23", "B", "What Journal Entry was recorded for this purchase?", ["je was recorded for this", "je recorded for this purchase", "journal entry was recorded for this purchase"], ("po|rfp",), "journal.lookup", "je_list"),
    _e("B24", "B", "Can I view the supporting documents?", ["supporting documents", "view the attachment", "attachments of this purchase"], ("po|rfp|je",), "purchase.supporting_docs", "po_list"),

    # ------------------------------------------------------------------ C
    _e("C25", "C", "How much do we currently owe this supplier?", ["owe", "supplier balance", "balance with this supplier", "balance of this supplier", "current balance with", "outstanding balance with"], ("supplier",), "ap.supplier_balance", "ap_aging"),
    _e("C26", "C", "What invoices are still unpaid?", ["unpaid invoices", "unpaid rfps", "open payables", "unpaid payables"], ("supplier|word:rfp|word:payable|word:ap",), "ap.open_payables", "ap_aging"),
    _e("C27", "C", "Which supplier payables are overdue?", ["overdue", "past due", "delayed payment", "late payment"], ("word:payable|word:supplier|word:ap|word:rfp|word:owe",), "ap.company_aging", "ap_aging"),
    _e("C28", "C", "What payments have been made to this supplier?", ["payments made", "payments to this", "payments to", "paid this supplier", "payments have been made"], ("supplier",), "ap.supplier_payments", "ap_ledger"),
    _e("C29", "C", "What is the supplier's transaction history?", ["transaction history", "history of this supplier", "supplier ledger", "ledger of this supplier", "full history"], ("supplier",), "ap.supplier_ledger", "ap_ledger"),
    _e("C30", "C", "What is the aging of this supplier's payable?", ["aging of this supplier", "supplier aging", "aging for this supplier", "how long has this supplier"], ("supplier",), "ap.supplier_aging", "ap_aging"),

    # ------------------------------------------------------------------ D
    _e("D31", "D", "How much does this customer owe us?", ["customer balance", "owe us", "does this customer owe", "balance for this customer", "customer owes", "outstanding balance of"], ("customer",), "ar.customer_balance", "ar_aging"),
    _e("D32", "D", "Which invoices are still unpaid?", ["unpaid invoices", "unpaid receipts", "open invoices", "are still unpaid", "still unpaid"], ("customer|none",), "ar.unpaid_invoices", "si_list"),
    _e("D33", "D", "When was the customer's last payment?", ["last payment", "latest payment", "most recent payment", "when did the customer pay"], ("customer",), "ar.last_payment", "receipt_list"),
    _e("D34", "D", "What payments has this customer made?", ["payments made by", "payments from", "paid by this customer", "has this customer paid", "customer payments", "payments has"], ("customer",), "ar.customer_payments", "receipt_list"),
    _e("D35", "D", "Which receivables are overdue?", ["overdue", "past due"], ("word:receivable|word:customer|word:ar|word:invoice|none",), "ar.overdue", "ar_aging"),
    _e("D36", "D", "What is the customer's AR aging?", ["aging", "how old"], ("customer",), "ar.customer_aging", "ar_aging"),
    _e("D37", "D", "Customer's complete transaction history", ["transaction history", "customer ledger", "history of this customer", "ledger of this customer", "full history"], ("customer",), "ar.customer_ledger", "ar_ledger"),

    # ------------------------------------------------------------------ E
    _e("E38", "E", "Current balance of this account?", ["balance of this account", "balance of the account", "current balance of", "balance of the said account"], ("account",), "ledger.balance", "ledger_index"),
    _e("E39", "E", "Balance as of a specific date?", ["balance as of", "as of", "balance on"], ("account",), "ledger.balance_as_of", "ledger_index"),
    _e("E40", "E", "Why did this account balance increase?", ["why did", "went up", "increase"], ("account", "word:balance|word:account"), "ledger.movement_reason", "ledger_index"),
    _e("E41", "E", "Why did this account balance decrease?", ["why did", "went down", "decrease", "decline"], ("account", "word:balance|word:account"), "ledger.movement_reason", "ledger_index"),
    _e("E42", "E", "What transactions make up this balance?", ["make up this balance", "composed of", "composition", "what transactions", "breakdown"], ("account",), "ledger.composition", "ledger_index"),
    _e("E43", "E", "Debit and credit movements of this account", ["debit and credit", "debit movements", "credit movements", "movements of this account", "movement of this account"], ("account",), "ledger.debit_credit", "ledger_index"),
    _e("E44", "E", "What is the beginning balance?", ["beginning balance", "opening balance", "beginning of the period", "opening of the period", "balance at the start"], ("account",), "ledger.beginning_balance", "ledger_index"),
    _e("E45", "E", "What is the ending balance?", ["ending balance", "closing balance", "end of the period", "balance at the end"], ("account",), "ledger.ending_balance", "ledger_index"),

    # ------------------------------------------------------------------ F
    _e("F46", "F", "Current balance of this bank account?", ["bank balance", "balance of this bank", "balance of the bank", "how much is in this bank"], ("bank",), "cash.bank_balance", "bank_list"),
    _e("F47", "F", "How much cash do we currently have?", ["total cash", "cash position", "how much cash", "total money", "cash balance", "all the cash"], (),
      "cash.total_cash", "bank_list"),
    _e("F48", "F", "Payments made from this bank account?", ["payments from this bank", "payments made from", "withdrawn from", "paid out of this bank", "payments from the bank"], ("bank",), "cash.bank_payments", "bank_list"),
    _e("F49", "F", "Deposits made to this bank account?", ["deposits", "deposited", "deposit to this bank", "deposits to this bank", "money into this bank"], ("bank",), "cash.bank_deposits", "bank_list"),
    _e("F50", "F", "What checks are still outstanding?", ["outstanding checks", "outstanding cheque", "not yet encashed", "uncleared checks", "checks not yet", "are still outstanding"], (),
      "cash.outstanding_checks", "bank_list"),
    _e("F51", "F", "Which checks have already cleared?", ["cleared checks", "checks cleared", "which checks have cleared", "have already cleared", "checks have cleared"], (), "cash.cleared_checks", "bank_list"),
    _e("F52", "F", "Which transactions are unreconciled?", ["unreconciled", "not reconciled", "no recon", "unmatched transactions"], (),
      "cash.unreconciled", "recon_list"),
    _e("F53", "F", "Difference between book and bank balance?", ["book vs bank", "book and bank", "book-versus", "difference between book", "bank statement vs"], (),
      "cash.book_vs_bank", "recon_list"),
    _e("F54", "F", "Show all transfers between bank accounts", ["transfers between", "inter-account", "fund transfer", "transfer between banks", "ftv"], (),
      "cash.transfers", "transfers"),

    # ------------------------------------------------------------------ G
    _e("G55", "G", "Who requested this payment?", ["who requested", "requested by", "who prepared this payment", "who made the request"], ("doc",), "payment.requested_by", "rfp_list"),
    _e("G56", "G", "Who approved this payment?", ["who approved", "approved by", "who signed off", "who authorized"], ("doc", "word:payment|word:rfp|word:cv|word:check|word:disbursement|word:voucher"), "payment.approved_by", "rfp_list"),
    _e("G57", "G", "What RFP is related to this payment?", ["what rfp", "rfp related", "rfp for this payment", "which rfp"], ("cv|je",), "payment.rfp_of", "rfp_list"),
    _e("G58", "G", "What CV was created from this RFP?", ["what cv", "cv created", "check voucher was created", "voucher for this rfp"], ("rfp|po",), "purchase.cv_of", "cv_list"),
    _e("G59", "G", "What check was issued?", ["what check", "check issued", "which check", "check number"], ("doc", "word:payment|word:rfp|word:cv|word:check|word:voucher"), "purchase.check_of", "cv_list"),
    _e("G60", "G", "Has the check been encashed/cleared?", ["encashed", "check cleared", "check encashed", "cleared yet", "already cleared", "credited to the supplier"], ("doc", "word:check|word:cv|word:encash|word:payment|word:cleared"), "payment.check_status", "cv_list"),
    _e("G61", "G", "What journal entry was created?", ["journal entry was created", "je was created", "entry was created for this"], ("doc", "word:payment|word:rfp|word:cv|none"), "journal.lookup", "je_list"),
    _e("G62", "G", "What supporting documents are attached?", ["supporting documents", "attached documents"], ("doc",), "purchase.supporting_docs", "rfp_list"),
    _e("G63", "G", "Who created and approved the transaction?", ["who created and approved", "created and approved", "who prepared and approved"], ("doc",), "payment.actors", "rfp_list"),
    _e("G64", "G", "Current status of the payment?", ["current status", "status of this payment", "status of the payment", "what is the status", "payment status"], ("doc",), "payment.status", "cv_list"),

    # ------------------------------------------------------------------ H
    _e("H65", "H", "What JE was recorded for this transaction?", ["je for this", "journal entry for this", "je recorded for", "je recorded", "je of this", "entry recorded for", "journal entry recorded", "was recorded for"], ("doc",), "journal.lookup", "je_list"),
    _e("H66", "H", "What accounts were debited?", ["accounts were debited", "what was debited", "debited accounts", "debit side of"], ("doc",), "journal.debits", "je_list"),
    _e("H67", "H", "What accounts were credited?", ["accounts were credited", "what was credited", "credited accounts", "credit side of"], ("doc",), "journal.credits", "je_list"),
    _e("H68", "H", "What is the reference of the JE?", ["reference of the je", "reference of the journal", "je reference", "journal reference", "reference number of the entry", "ref number of"], ("doc",), "journal.reference", "je_list"),
    _e("H69", "H", "Who prepared the journal entry?", ["who prepared", "prepared by", "who encoded", "who made the entry"], ("doc", "word:je|word:journal|word:entry|none"), "journal.preparer", "je_list"),
    _e("H70", "H", "Who approved the journal entry?", ["approved the je", "approved the journal", "approved the entry", "approved by"], ("doc", "word:je|word:journal|word:entry|none"), "journal.approver", "je_list"),
    _e("H71", "H", "Can I view the supporting document?", ["supporting document", "attachment of the je", "source file"], ("doc",), "journal.supporting_doc", "je_list"),
    _e("H72", "H", "Can I prepare a draft JE for this transaction?", ["prepare a draft", "draft je", "draft journal entry", "make a draft"], (), None, "je_list", "write-deferred"),

    # ------------------------------------------------------------------ I
    _e("I78", "I", "Which employees have outstanding cash advances?", ["employee advances", "employees have", "advance to employee", "advances of employees", "cash advances", "employee's advances"], (),
      "advances.employee_list", "advances"),
    _e("I79", "I", "Which officers have outstanding advances?", ["officer advances", "officers have", "advance to officer", "advances of officers", "officer's advances"], (),
      "advances.officer_list", "advances"),
    _e("I74", "I", "Which parties have outstanding advances?", ["which parties have outstanding", "who has outstanding advances", "list of outstanding advances", "parties with advances"], (),
      "advances.outstanding_list", "advances"),
    _e("I73", "I", "How much do we have in outstanding advances?", ["outstanding advances", "total advances", "advances outstanding", "how much in advances"], (),
      "advances.total", "advances"),
    _e("I75", "I", "How long has each advance been outstanding?", ["how long", "how old", "age of the advance", "days outstanding"], ("advance|party|none",), "advances.age", "advances"),
    _e("I76", "I", "Has this advance already been liquidated?", ["already been liquidated", "has this advance been liquidated", "already liquidated", "was liquidated", "liquidated yet", "paid back", "repaid", "closed the advance"], ("advance|party|none",), "advances.liquidated", "advances"),
    _e("I77", "I", "What transaction liquidated the advance?", ["what transaction", "what rfp liquidated", "liquidation reference", "liquidating transaction"], ("advance|party|none",), "advances.liquidating_txn", "advances"),
    _e("I80", "I", "Complete history of this advance", ["history of this advance", "advance history", "history of the advance", "history of the loan"], ("advance|party|none",), "advances.history", "advances"),

    # ------------------------------------------------------------------ J
    _e("J81", "J", "How many units of this item are available?", ["units available", "available stock", "on hand", "in stock", "available units"], ("item_text",), None, "inventory", "pending-external"),
    _e("J82", "J", "What is the current inventory cost?", ["inventory cost", "cost of inventory", "stock cost", "value of inventory"], ("item_text",), "inventory.inventory_cost", "po_list"),
    _e("J83", "J", "Who supplied this item?", ["who supplied", "supplied this item", "supplier of the item"], ("item_text",), "purchase_items.item_suppliers", "po_list"),
    _e("J84", "J", "When was this item purchased?", ["when was this item purchased", "when was the item bought", "purchase date of the item"], ("item_text",), "purchase_items.item_history", "po_list"),
    _e("J85", "J", "What was the purchase price?", ["purchase price", "buying price", "price we bought"], ("item_text",), "purchase_items.item_prices", "po_list"),
    _e("J86", "J", "What is the movement of this item?", ["movement of this item", "item movement", "stock movement", "transactions of this item"], ("item_text",), "inventory.item_movement", "po_list"),
    _e("J87", "J", "What items are below minimum stock?", ["below minimum", "below min", "minimum stock", "reorder level"], (), None, "inventory", "pending-external"),
    _e("J88", "J", "What items have no movement?", ["no movement", "no transactions", "inactive items", "never moved"], ("item_text|none",), "inventory.no_movement", "po_list"),
    _e("J89", "J", "Complete inventory history of this item", ["inventory history", "history of this item", "item history"], ("item_text",), "inventory.inventory_history", "po_list"),

    # ------------------------------------------------------------------ K
    _e("K90", "K", "What is our current net income?", ["net income", "net profit", "profit or loss", "profit and loss", "bottom line"], (), "reports.net_income", "statement"),
    _e("K91", "K", "What are our total revenues?", ["total revenue", "total revenues", "total sales", "gross sales", "gross revenue"], (), "reports.revenue", "statement"),
    _e("K92", "K", "What are our total expenses?", ["total expenses", "total expense", "total operating expenses", "expenses this month", "total costs"], (), "reports.expenses", "statement"),
    _e("K93", "K", "What is our total receivable?", ["total receivable", "receivable total", "total accounts receivable", "total balance of receivable", "how much is receivable"], (), "reports.total_receivable", "trial_balance"),
    _e("K94", "K", "What is our total payable?", ["total payable", "payable total", "total accounts payable", "total balance of payable", "how much is payable"], (), "reports.total_payable", "trial_balance"),
    _e("K95", "K", "What is our total cash balance?", ["total cash balance"], (), "cash.total_cash", "trial_balance"),
    _e("K96", "K", "Show the Trial Balance", ["trial balance"], (), "reports.trial_balance", "trial_balance"),
    _e("K97", "K", "Show the Income Statement", ["income statement", "statement of income", "profit and loss statement"], (), "reports.income_statement", "statement"),
    _e("K98", "K", "Show the Balance Sheet", ["balance sheet", "statement of financial position", "sfp"], (), "reports.balance_sheet", "statement"),
    _e("K99", "K", "Show the Cash Flow Statement", ["cash flow"], (), "reports.cash_flow", "cash_flow"),
    _e("K100", "K", "Compare this month with previous month", ["compare", "versus last", "vs last"], ("word:month|word:period|word:quarter|word:year|word:previous",), "reports.compare_periods", "statement"),
]

CATALOG_BY_ID: dict[str, CatalogEntry] = {e.qid: e for e in CATALOG}

# Short category letter -> module used for SearchLog / module label.
CATEGORY_MODULES = {
    "A": "ap", "B": "ap", "C": "ap", "D": "ar", "E": "posting",
    "F": "cash", "G": "ap", "H": "posting", "I": "ap", "J": "inventory",
    "K": "reporting",
}


def _entry_matches(entry: CatalogEntry, lower: str, entities) -> bool:
    if not any(p in lower for p in entry.phrases):
        return False
    for req in entry.requires:
        resolved = False
        for alt in req.split("|"):
            if alt.startswith("word:"):
                if alt[5:] in lower:
                    resolved = True
                    break
            elif entities.resolved(alt):
                resolved = True
                break
        if not resolved:
            return False
    return True


def match(lower: str, entities, statuses=("ready", "needs-stub")):
    """First catalog entry whose phrases + entity requirements match.

    Catalog order is the priority order: write the more specific questions
    first (they do, per category). Returns None when nothing fires so the
    caller can fall back to the record search untouched.
    """
    for entry in CATALOG:
        if entry.status not in statuses:
            continue
        if entry.handler is None:
            continue
        if _entry_matches(entry, lower, entities):
            return entry
    return None