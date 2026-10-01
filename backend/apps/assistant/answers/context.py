"""Query context + entity resolution for computed answers.

Everything here is read-only. Resolution is deliberately forgiving: it tries
exact code -> case-insensitive name contains -> none. When an entity cannot be
resolved, catalog questions that need it simply do not fire and the assistant
falls back to the normal record search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from apps.posting.models import GL_EFFECTIVE_STATUSES, JournalEntry

from .base import ResolvedPeriod


def _month_window(d: date) -> ResolvedPeriod:
    from datetime import timedelta

    first = d.replace(day=1)
    last = (
        date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)
    ) - timedelta(days=1)
    return ResolvedPeriod(first, last, is_default=False)


def _explicit_period(lower: str) -> ResolvedPeriod | None:
    """A period the question names explicitly (month, quarter, year).

    Explicit requests are honored literally — the latest-activity fallback is
    only for questions that name no period at all.
    """
    from datetime import timedelta

    today = date.today()
    for name, num in _MONTHS.items():
        if re.search(rf"\b{name}\w*\s+(\d{{4}})\b", lower):
            year = int(re.search(rf"\b{name}\w*\s+(\d{{4}})\b", lower).group(1))
            return _month_window(date(year, num, 1))
    if re.search(r"\b(this month|karon nga bulan|karon ni nga bulan)\b", lower):
        return _month_window(today)
    if re.search(r"\b(last month|miaging bulan)\b", lower):
        first = today.replace(day=1)
        prev_end = first - timedelta(days=1)
        return _month_window(prev_end)
    if re.search(r"\b(this quarter|karon nga kwarter)\b", lower):
        q = (today.month - 1) // 3
        return _month_window(date(today.year, q * 3 + 1, 1)) if q * 3 + 1 <= 12 else ResolvedPeriod(date(today.year, 10, 1), date(today.year, 12, 31))
    if re.search(r"\b(last quarter|last kwarter)\b", lower):
        q = (today.month - 1) // 3
        start_m = q * 3 - 2
        year = today.year - 1 if start_m < 1 else today.year
        if start_m < 1:
            start_m += 12
        return ResolvedPeriod(date(year, start_m, 1), _month_window(date(year, start_m + 2, 1)).end)
    if re.search(r"\b(this year|karon nga tuig)\b", lower):
        return ResolvedPeriod(date(today.year, 1, 1), date(today.year, 12, 31))
    if re.search(r"\b(last year|last tuig)\b", lower):
        return ResolvedPeriod(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31))
    return None


def latest_activity_period(companies) -> ResolvedPeriod | None:
    """The newest calendar month containing any effective GL posting.

    Dev data can lag the system clock (September vs October), so reports
    default to the newest month that actually has posted activity instead of
    the literal current month. The substitution is disclosed in the answer's
    note (mirrors the search-side date relaxation).
    """
    if not companies:
        return None
    last = (
        JournalEntry.objects.filter(
            company__in=companies, status__in=GL_EFFECTIVE_STATUSES
        )
        .order_by("-transaction_date")
        .values_list("transaction_date", flat=True)
        .first()
    )
    if last is None:
        return None
    window = _month_window(last)
    return ResolvedPeriod(window.start, window.end, is_default=True)


_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_as_of(raw: str) -> date | None:
    """An explicit "as of <date>" (or bare ISO date) in the question."""
    text = raw.lower().strip()
    m = re.search(r"\bas of\b[^\d]*?(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(
        r"\bas of\b[^\d]*?(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?,\s*(\d{4})",
        text,
    )
    if m:
        return date(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2)))
    m = re.search(
        r"\bas of\b[^\d]*?(" + "|".join(_MONTHS) + r")\s+(\d{4})", text
    )
    if m:
        return date(int(m.group(2)), _MONTHS[m.group(1)], 1)
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _term_contains(model, field_name: str, term: str):
    return model.objects.filter(**{f"{field_name}__icontains": term}).first()


@dataclass
class Entities:
    supplier: object = None
    customer: object = None
    account: object = None
    bank: object = None
    po: object = None
    rfp: object = None
    cv: object = None
    je: object = None
    advance: object = None
    party_text: str | None = None
    item_text: str | None = None
    as_of: date | None = None
    period: ResolvedPeriod | None = None
    period_note: str = ""

    def resolved(self, key: str) -> bool:
        if key == "none":
            return True
        if key == "supplier":
            return self.supplier is not None
        if key == "customer":
            return self.customer is not None
        if key == "account":
            return self.account is not None
        if key == "bank":
            return self.bank is not None
        if key == "po":
            return self.po is not None
        if key == "rfp":
            return self.rfp is not None
        if key == "cv":
            return self.cv is not None
        if key == "je":
            return self.je is not None
        if key == "advance":
            return self.advance is not None
        if key == "party":
            return self.party_text is not None or self.advance is not None
        if key == "item_text":
            return self.item_text is not None
        if key == "doc":
            return any(getattr(self, k) is not None for k in ("po", "rfp", "cv", "je"))
        return False


@dataclass
class QContext:
    user: object
    raw: str
    lower: str
    terms: list = field(default_factory=list)
    companies: list = field(default_factory=list)
    entities: Entities = field(default_factory=Entities)
    entry: object = None

    def terms_norm(self) -> list[str]:
        return [t.lower().strip("-/") for t in self.terms]


def resolve_entities(user, parsed, raw: str, lower: str, companies: list) -> Entities:
    """Resolve every entity type the catalog asks about (best effort)."""
    from apps.ap.models import AdvanceToEmployee, CheckVoucher, POLine, PurchaseOrder, RFPDocument, Supplier
    from apps.ar.models import Customer
    from apps.cash.models import BankAccount
    from apps.foundation.models import Account
    from apps.posting.models import JournalEntry

    ents = Entities(as_of=parse_as_of(raw))
    terms = [t for t in parsed.entities + parsed.search_terms if t]
    codes = [t for t in terms if re.fullmatch(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)+", t)]
    bare = [t for t in terms if t.isdigit()]

    # -- journal entries / document codes --------------------------------
    for term in codes:
        if not ents.je:
            ents.je = _term_contains(JournalEntry, "entry_no", term)
        if not ents.rfp:
            ents.rfp = _term_contains(RFPDocument, "ap_number", term)
        if not ents.cv:
            ents.cv = _term_contains(CheckVoucher, "cv_number", term)
        if not ents.po:
            ents.po = _term_contains(PurchaseOrder, "po_number", term)
    for term in terms:
        # Standalone codes without separators (RFP "A1001", JE "JE20260001").
        if re.fullmatch(r"[A-Za-z]+\d+", term):
            if not ents.rfp:
                ents.rfp = _term_contains(RFPDocument, "ap_number", term)
            if not ents.je:
                ents.je = _term_contains(JournalEntry, "entry_no", term)
    for digit in bare:
        if len(digit) >= 4:
            if not ents.je:
                ents.je = JournalEntry.objects.filter(entry_no__icontains=digit).first()
            if not ents.rfp:
                ents.rfp = RFPDocument.objects.filter(ap_number__icontains=digit).first()
            if not ents.cv:
                ents.cv = CheckVoucher.objects.filter(cv_number__icontains=digit).first()
            if not ents.po:
                ents.po = PurchaseOrder.objects.filter(po_number__icontains=digit).first()

    # -- general ledger account (5-digit picks or name) -------------------
    for digit in bare:
        if len(digit) == 5:
            ents.account = Account.objects.filter(code=digit).first()
            if ents.account:
                break
    # Name-based: e.g. "the cash on hand account" (parser already filtered
    # generic words, so this only fires on real account-name tokens).
    if ents.account is None:
        for term in terms:
            if len(term) < 3 or re.fullmatch(r"[A-Za-z]+\d+", term):
                continue
            acc = Account.objects.filter(name__icontains=term).first()
            if acc is not None:
                ents.account = acc
                break

    # -- item text (free-text, matches POLine descriptions) ---------------
    for term in terms:
        if POLine.objects.filter(description__icontains=term).exists():
            ents.item_text = term
            break

    # -- supplier / customer / bank / advance party ------------------------
    for term in terms:
        low = term.lower()
        if low in ("who", "what", "which", "when", "where", "how", "why", "much", "many"):
            continue
        if ents.supplier is None:
            ents.supplier = (
                Supplier.objects.filter(code__icontains=term).first()
                or Supplier.objects.filter(name__icontains=term).first()
            )
        if ents.customer is None:
            ents.customer = (
                Customer.objects.filter(code__icontains=term).first()
                or Customer.objects.filter(name__icontains=term).first()
            )
        if ents.bank is None:
            qs = BankAccount.objects.filter(is_active=True)
            ents.bank = (
                qs.filter(name__icontains=term).first()
                or qs.filter(code__icontains=term).first()
                or qs.filter(account_number__icontains=term).first()
            )
        if ents.advance is None and AdvanceToEmployee.objects.filter(
            employee_name__icontains=term
        ).exists():
            ents.advance = AdvanceToEmployee.objects.filter(
                employee_name__icontains=term
            ).first()
        if ents.party_text is None and low not in ("employee", "employees", "officer", "officers"):
            ents.party_text = term if not re.fullmatch(r"[A-Za-z]+\d+", term) else None

    # -- report period -----------------------------------------------------
    as_of = ents.as_of
    explicit = _explicit_period(lower)
    if as_of is not None:
        ents.period = _month_window(as_of)
        ents.period_note = ""
    elif explicit is not None:
        ents.period = explicit
        ents.period_note = ""
    else:
        p = latest_activity_period(companies)
        if p is not None:
            ents.period = p
            ents.period_note = (
                f"Showing {p.label()}, the latest month with posted activity."
            )

    return ents