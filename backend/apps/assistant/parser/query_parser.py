from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class ParsedQuery:
    raw: str
    keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    search_terms: list[str] = field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    intent: str = "lookup"
    top_n: int | None = None
    sort_amount: bool = False
    status: str | None = None
    modules: list[str] = field(default_factory=list)


class QueryParser:
    STOP_WORDS = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "can", "shall",
        "i", "you", "he", "she", "it", "we", "they", "me", "him",
        "her", "us", "them", "my", "your", "his", "its", "our",
        "their", "this", "that", "these", "those",
        "and", "or", "but", "if", "then", "so", "because",
        "of", "at", "by", "for", "with", "about", "into", "through",
        "during", "before", "after", "above", "below", "to", "from",
        "in", "on", "out", "off", "over", "under", "again",
        "show", "find", "search", "list", "get", "give", "tell",
        "what", "which", "who", "whom", "whose", "where", "when",
        "how", "much", "many", "any", "all", "some", "no",
        "not", "only", "own", "same", "than", "too", "very",
        "just", "now", "also", "here", "there", "up", "down",
        "as", "sa", "ug", "og", "ang", "mga", "nga", "na", "ni",
        "kay", "kang", "para", "pang", "sila", "siya", "nako",
        "nimo", "namo", "nato", "mo", "ko", "ta", "na",
        "unsa", "kinsa", "asa", "pila", "unsay", "kani", "ana",
        "palihug", "pwede", "mao", "anaa", "wala", "dili", "si",
        "ang", "sa", "og", "nga", "na", "ni", "kay", "para",
    }

    INTENT_KEYWORDS = {
        "lookup": ["show", "find", "search", "list", "get", "give", "tell",
                    "unsa", "kinsa", "asa", "pila", "palihug", "pwede"],
        "summary": ["total", "sum", "summary", "overview", "report",
                    "pila", "total", "ka"],
        "compare": ["compare", "versus", "vs", "difference",
                    "banding", "sama"],
        "trend": ["trend", "over time", "history", "growth",
                  "usaban", "history"],
    }

    # Words that identify a MODULE or an ACTION/aggregation but are NOT a
    # specific record name. A query made only of these is a BROWSE request
    # (list everything in the matched module), not a name filter.
    GENERIC_TERMS = {
        # module nouns
        "supplier", "suppliers", "vendor", "vendors", "payee", "rfp", "rfps",
        "purchase", "order", "orders", "po", "pos", "conso", "advance",
        "advances", "voucher", "vouchers", "cv", "cvs", "check", "checks",
        "payment", "payments", "conso",
        "customer", "customers", "client", "clients", "buyer", "buyers",
        "invoice", "invoices", "sales", "si", "receipt", "receipts",
        "deposit", "deposits", "journal", "journals", "je", "jes", "entry",
        "entries", "transaction", "transactions", "gl", "general", "ledger",
        "posting", "bank", "banks", "transfer", "transfers", "pcf", "petty",
        "reconciliation", "recon", "cash", "cycle", "cycles", "short",
        "collectibles", "asset", "assets", "equipment", "vehicle", "vehicles",
         "depreciation", "fleet", "fuel", "payroll", "pay", "salary",
         "compensation", "tax", "taxes", "vat", "wht", "withholding", "bir",
         "fixed", "fully", "current", "currently", "financial", "ftv",
         "batch", "batches", "conso", "advance", "advances",
        "inventory", "stock", "item", "items", "approval", "approvals",
        "workflow", "request", "requests", "refund", "refunds", "billing",
        "bill", "bills", "report", "reports", "statement", "statements",
        "income", "expense", "coa", "account", "accounts", "chart",
        "segment", "segments", "company", "companies",
        # actions / aggregation / UI filler
        "data", "record", "records", "table", "view", "page", "menu",
        "display", "where", "when", "whom", "whose", "many", "much",
        "top", "highest", "biggest", "most", "least", "rank", "ranking",
        "average", "amount", "total", "sum", "summary", "overview", "count",
        "balance", "list", "all", "any", "some", "get", "show", "find",
        "search", "tell", "give", "how", "what", "which", "who", "last",
        "this", "next", "week", "month", "year", "quarter", "today",
        "yesterday", "status", "pending", "approved", "submitted", "draft",
        "paid", "unpaid", "open", "closed", "posted",
    }

    STATUS_WORDS = {
        "pending": "pending",
        "submitted": "submitted",
        "approved": "approved",
        "draft": "draft",
        "posted": "posted",
        "open": "open",
        "unpaid": "unpaid",
        "overdue": "open",
        "rejected": "rejected",
        "liquidated": "liquidated",
        "reviewed": "reviewed",
    }

    # Multi-word cues that mean "waiting on approval" regardless of the
    # single status word present.
    STATUS_PHRASES = {
        r"needs?\s+approval": "pending",
        r"to\s+approve": "pending",
        r"awaiting\s+approval": "pending",
        r"pending\s+approval": "pending",
        r"not\s+(?:yet\s+)?approved": "pending",
        r"not\s+(?:yet\s+)?posted": "pending",
        r"not\s+yet\s+(?:approved|posted)": "pending",
    }

    # Filler/conversational words that must never be treated as a record name.
    NON_DATA_WORDS = {
        "need", "neede", "needs", "want", "wants", "please", "recently",
        "recent", "latest", "newest", "processed", "forgotten", "forgot",
        "forget", "remember", "recall", "order", "ordered", "orderd", "buy",
        "bought", "purchase", "purchased", "got", "receive", "received",
        "spend", "spent", "made", "like", "kind", "sort", "very", "just",
        "earlier", "earliest", "previously", "ago", "later", "beforehand",
        "process", "processes", "processing", "handled", "handles",
        "enter", "entered", "encode", "encoded", "prepare", "prepared",
        "still", "already", "yet", "thing", "things", "stuff", "item",
        "detail", "details", "content", "contents", "info", "information",
        "there", "here", "which", "whose", "whom", "many", "much", "count",
        "number", "list", "lists", "any", "every", "each", "about", "regarding",
        "user", "users", "person", "people", "username", "login",
        "entire", "whole", "remaining", "outstanding", "available",
        "gibayaran", "bayad", "bayaran", "karon", "una", "sayo", "subay",
        "kanus-a", "kanusa", "suod", "naingon", "ingon", "pinaka-",
    }

    def parse(self, raw: str) -> ParsedQuery:
        text = raw.strip()
        lower = text.lower()

        keywords = self._extract_keywords(lower)
        entities = self._extract_entities(text)
        date_from, date_to = self._extract_date_range(lower)
        intent = self._detect_intent(lower)
        top_n = self._detect_top_n(lower)
        if top_n is None and self._is_recency(lower):
            top_n = 5
        search_terms = self._extract_search_terms(entities, keywords, text, top_n)
        sort_amount = self._detect_sort_amount(lower)
        status = self._detect_status(lower)

        return ParsedQuery(
            raw=raw,
            keywords=keywords,
            entities=entities,
            date_from=date_from,
            date_to=date_to,
            intent=intent,
            search_terms=search_terms,
            top_n=top_n,
            sort_amount=sort_amount,
            status=status,
        )

    def _extract_search_terms(self, entities, keywords, text, top_n) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()

        def add(token: str) -> None:
            low = token.lower().strip("-/")
            if not low or low in seen:
                return
            seen.add(low)
            terms.append(token)

        # Document codes: hyphen/slash groups (CV-2026-0009, 2026-00018) and
        # digit runs that are not a year and not the "top N" quantity.
        for code in re.findall(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)+", text):
            add(code)
        for run in re.findall(r"(?<!\d)\d{1,}(?!\d)", text):
            if re.fullmatch(r"(19|20)\d\d", run):
                continue
            if top_n is not None and run == str(top_n):
                continue
            add(run)

        # Descriptive words (names, items) — never pure digits or id-like
        # tokens such as pcf2 / ftv10 (their digit run is already captured).
        for token in list(entities) + list(keywords):
            low = token.lower()
            if token.isdigit() or re.fullmatch(r"[A-Za-z]+\d+", token):
                continue
            if low in self.GENERIC_TERMS or low in self.STOP_WORDS or low in self.NON_DATA_WORDS:
                continue
            add(token)
        return terms[:8]

    def _detect_top_n(self, text: str) -> int | None:
        m = re.search(r"\btop\s*(\d+)\b", text)
        if m:
            return int(m.group(1))
        if re.search(r"\b(top|highest|biggest|most)\b", text):
            return 5
        return None

    def _is_recency(self, text: str) -> bool:
        return bool(re.search(r"\b(latest|newest|recent|recently|processed|last)\b", text))

    def _detect_sort_amount(self, text: str) -> bool:
        amount_words = {
            "top", "highest", "biggest", "most", "total", "amount", "sum",
            "balance", "worth", "spent", "value", "cost", "largest", "pila",
        }
        return bool(amount_words & set(re.findall(r"[a-z]+", text)))

    def _detect_status(self, text: str) -> str | None:
        for pattern, mapped in self.STATUS_PHRASES.items():
            if re.search(pattern, text):
                return mapped
        for word, mapped in self.STATUS_WORDS.items():
            if re.search(rf"\b{word}\b", text):
                return mapped
        return None

    def _extract_keywords(self, text: str) -> list[str]:
        words = re.findall(r"[a-z0-9]+", text)
        return [w for w in words if w not in self.STOP_WORDS and len(w) > 1]

    def _extract_entities(self, text: str) -> list[str]:
        entities = []
        patterns = [
            r'"([^"]+)"',
            r"'([^']+)'",
            r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b",
            r"\b([A-Z]{2,}(?:\s+[A-Z]{2,})*)\b",
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text)
            entities.extend(m for m in matches if len(m) > 1)

        remaining = re.sub(r"[\"']", "", text)
        remaining = re.sub(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", "", remaining)
        remaining = re.sub(r"\b[A-Z]{2,}(?:\s+[A-Z]{2,})*\b", "", remaining)

        words = re.findall(r"[a-zA-Z]+", remaining)
        for word in words:
            if len(word) > 3 and word.lower() not in self.STOP_WORDS:
                if word not in entities:
                    entities.append(word)

        return entities[:10]

    def _extract_date_range(self, text: str) -> tuple[date | None, date | None]:
        today = date.today()

        if re.search(r"\b(today|ngadto|karon)\b", text):
            return today, today

        if re.search(r"\b(yesterday|kahapon)\b", text):
            y = today - timedelta(days=1)
            return y, y

        if re.search(r"\b(recently|recent|last 30 days|past 30 days|bag-o)\b", text):
            return today - timedelta(days=30), today

        if re.search(r"\blast 7 days\b|\bpast week\b", text):
            return today - timedelta(days=7), today

        if "last month" in text or "last bulan" in text or "miaging bulan" in text:
            first_of_month = today.replace(day=1)
            last_month_end = first_of_month - timedelta(days=1)
            last_month_start = last_month_end.replace(day=1)
            return last_month_start, last_month_end

        if "this month" in text or "karon nga bulan" in text:
            return today.replace(day=1), today

        if "last week" in text or "last semana" in text:
            days_since_monday = today.weekday()
            last_monday = today - timedelta(days=days_since_monday + 7)
            last_sunday = last_monday + timedelta(days=6)
            return last_monday, last_sunday

        if "this week" in text or "karon nga semana" in text:
            days_since_monday = today.weekday()
            monday = today - timedelta(days=days_since_monday)
            return monday, today

        if "last year" in text or "last tuig" in text:
            return today.replace(year=today.year - 1, month=1, day=1), \
                   today.replace(year=today.year - 1, month=12, day=31)

        if "this year" in text or "karon nga tuig" in text:
            return today.replace(month=1, day=1), today

        if "last quarter" in text or "last kwarter" in text:
            current_quarter = (today.month - 1) // 3
            if current_quarter == 0:
                return today.replace(year=today.year - 1, month=10, day=1), \
                       today.replace(year=today.year - 1, month=12, day=31)
            else:
                start_month = (current_quarter - 1) * 3 + 1
                end_month = start_month + 2
                return today.replace(month=start_month, day=1), \
                       today.replace(month=end_month, day=1) + timedelta(days=31)

        if "this quarter" in text or "karon nga kwarter" in text:
            current_quarter = (today.month - 1) // 3
            start_month = current_quarter * 3 + 1
            return today.replace(month=start_month, day=1), today

        year_match = re.search(r"\b(20\d{2})\b", text)
        if year_match:
            year = int(year_match.group(1))
            return date(year, 1, 1), date(year, 12, 31)

        return None, None

    def _detect_intent(self, text: str) -> str:
        for intent, keywords in self.INTENT_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return intent
        return "lookup"
