"""Small-talk pre-scan (Phase 5).

Runs BEFORE the catalog and the record search: a message that is *only*
small talk ("hi", "how are you", "thanks", "who are you", today's date or
time, the weather) gets a polite localized reply instead of an empty search.
Whole-message patterns guarantee "hi, any reference from Limdon?" still
searches — grep each pattern with ``re.fullmatch`` on the lowered text.
"""

from __future__ import annotations

import re

from django.utils import timezone

from .base import Answer

# (template key, full-match patterns) — first key hit wins.
_PATTERNS = [
    ("chat_hi", [
        r"^(hi|hello|hey|yo|hai|hoy|good\s+(morning|afternoon|evening|day|night))\s*[!.]*$",
        r"^(maayong\s+(buntag|udto|hapon|gabii))\s*[!.]*$",
        r"^kamusta\s*[!.]*$",
    ]),
    ("chat_how", [
        r"^how\s+are\s+you(\s+doing)?\s*[?!.]*$",
        r"^(kumusta|kamusta|musta)\s+ka\s*[?]*$",
    ]),
    ("chat_thanks", [
        r"^(thank\s+you(\s+very\s+much)?|thanks(\s+a\s+lot)?|salamat(\s+kaayo)?|thanks\s+kaayo)\s*[!.]*$",
    ]),
    ("chat_who", [
        r"^(who\s+are\s+you|what\s+can\s+you\s+do|what\s+do\s+you\s+do)\s*[?]*$",
        r"^(unsa\s+ka|unsay\s+(imo|imong)\s+mabuhat|kay\s+kinsa\s+ka)\s*[?]*$",
    ]),
    ("chat_date", [
        r"^what(?:'s| is)\s+(the\s+)?(date|today(?:'s\s+date)?)\s*[?]*$",
        r"^what\s+day\s+is\s+it\s*[?]*$",
        r"^(unsa\s+(?:ang|karon)\s+petsa|anong\s+petsa|petsa\s+karon)\s*[?]*$",
    ]),
    ("chat_time", [
        r"^what(?:'s| is)\s+the\s+time\s*[?]*$",
        r"^what\s+time\s+is\s+it\s*[?]*$",
    ]),
    ("chat_weather", [
        r".*\b(weather|forecast)\b.*$",
    ]),
]


def _chat_key(raw: str):
    text = (raw or "").strip().lower()
    for key, patterns in _PATTERNS:
        for pattern in patterns:
            if re.fullmatch(pattern, text):
                return key
    return None


def conversation_answer(raw: str) -> Answer | None:
    """A chat reply for pure small talk, or None to let the normal pipeline run."""
    key = _chat_key(raw)
    if key is None:
        return None
    from ..formatter.language_detector import LanguageDetector
    from ..formatter.response_formatter import RESPONSE_TEMPLATES

    language = LanguageDetector().detect(raw)
    templates = RESPONSE_TEMPLATES.get(language, RESPONSE_TEMPLATES["en"])
    if key == "chat_date":
        value = templates[key].format(date=timezone.localdate().strftime("%B %d, %Y"))
    elif key == "chat_time":
        value = templates[key].format(time=timezone.localtime().strftime("%I:%M %p"))
    else:
        value = templates[key]
    return Answer(qid="CHAT", title="", summary=value, module="assistant")