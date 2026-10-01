from __future__ import annotations

import re

CEBUANO_MARKERS = [
    "kinsa", "unsa", "asa", "pila", "unsay", "nasa", "kani", "ana",
    "mga", "naa", "wala", "palihug", "pwede", "mugawas", "nindot",
    "maayo", "dili", "si", "ang", "sa", "og", "nga", "na", "ni",
    "kay", "para", "sila", "siya", "nako", "nimo", "namo", "nato",
    "mo", "ko", "ta", "karon", "kagahapon", "bag-o", "dako", "gamay",
    "maayong", "buntag", "hapon", "gabii", "semana", "bulan", "tuig",
    "kwan", "unsaon", "asa", "diin", "ngano", "kanus-a", "kusta",
    "kanus-a", "pila", "ka", "na", "ba", "pa", "na", "man", "jud",
    "gyud", "kaayo", "daghan", "wala", "dili", "mao", "kana", "kini",
    "ilang", "iya", "amo", "inyong", "among", "kang", "kang", "sa",
    "kang", "ni", "kang", "sa", "kang", "ni", "kang", "sa", "kang",
]

TAGALOG_MARKERS = [
    "sino", "ano", "saan", "gaano", "ano-ano", "nasaan", "mga",
    "mayroon", "wala", "pakiusap", "maaari", "ang", "ng", "sa",
    "ni", "kay", "para", "sila", "siya", "ako", "ikaw", "ko", "mo",
    "namin", "ninyo", "amin", "inyo", "niya", "kanila", "amin",
    "ngayon", "kahapon", "bago", "malaki", "maliit", "magandang",
    "umaga", "hapon", "gabi", "linggo", "buwan", "taon", "ano",
    "saan", "kailan", "bakit", "paano", "ilano", "meron", "wala",
    "po", "ho", "ba", "na", "pa", "man", "lang", "lamang", "mga",
    "dito", "doon", "diyan", "narito", "nasa", "nandiyan", "naroon",
]

ENGLISH_MARKERS = [
    "who", "what", "where", "when", "how", "which", "show", "find",
    "search", "list", "total", "amount", "payment", "supplier",
    "customer", "invoice", "receipt", "journal", "entry", "bank",
    "transfer", "asset", "report", "statement", "balance", "tax",
    "vat", "withholding", "payroll", "inventory", "billing", "approval",
    "pending", "approved", "rejected", "last", "this", "next",
    "month", "week", "year", "quarter", "today", "yesterday",
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "shall", "of", "at",
    "by", "for", "with", "about", "into", "through", "during",
    "before", "after", "above", "below", "to", "from", "in", "on",
]


class LanguageDetector:
    def detect(self, text: str) -> str:
        text_lower = text.lower()
        words = re.findall(r"[a-z]+", text_lower)

        ceb_score = sum(1 for w in words if w in CEBUANO_MARKERS)
        tag_score = sum(1 for w in words if w in TAGALOG_MARKERS)
        eng_score = sum(1 for w in words if w in ENGLISH_MARKERS)

        if ceb_score > tag_score and ceb_score > eng_score:
            return "ceb"
        elif tag_score > ceb_score and tag_score > eng_score:
            return "tag"
        return "en"
