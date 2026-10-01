from __future__ import annotations

from .language_detector import LanguageDetector


RESPONSE_TEMPLATES = {
    "ceb": {
        "greeting": "Unsa imong pangutana? Pwede ka mag-type og keywords o pili sa suggestions.",
        "no_results": "Wala ko makita nga resulta. Sulayi pag-usab o pangutana sa lain nga paagi.",
        "no_access": "Wala ka access sa {module} module. Palihug kontaka ang admin.",
        "found_count": "Naa ko nadaghan {count} resulta:",
        "found_single": "Naa ko nadaghan 1 resulta:",
        "date_relaxed": "Wala ang anay sa naa nga petsa, so ipakita ko ang pinakabag-o nga mga record:",
        "suggestions": "Pwede nimo sulayi ni:",
        "error": "Naay error. Sulayi pag-usab.",
        "loading": "Nagpangutana...",
        "chat_hi": "Maayong adlaw! Unsay imong pangutana? Pwede ka mag-type og keywords o pili sa suggestions.",
        "chat_how": "Okay ra ko, salamat sa pagpangutana! Pangutana lang unsay gusto nimong mahibaw-an sa mga records.",
        "chat_thanks": "Way sapayan! Naay lain pa akong matabang nimo?",
        "chat_who": "Ako ang Smart Search Assistant. Makapangita ko og records ug makatubag sa pangutana mahitungod sa suppliers, customers, payments, journal entries, cash, advances, inventory, ug financial reports. Sulayi ko ug pangutana!",
        "chat_date": "Karon kay {date}.",
        "chat_time": "Ang oras karon kay {time}.",
        "chat_weather": "Dili ko pwedeng maka-check sa weather karon.",
        "module_names": {
            "ap": "Accounts Payable",
            "ar": "Accounts Receivable",
            "posting": "Journal Entries",
            "cash": "Cash & Bank",
            "assets": "Fixed Assets",
            "billing": "Billing",
            "fleet": "Fleet",
            "payroll": "Payroll",
            "tax": "Tax",
            "inventory": "Inventory",
            "workflow": "Approvals",
            "reporting": "Reports",
            "foundation": "Foundation",
        },
    },
    "tag": {
        "greeting": "Ano ang tanong mo? Pwedeng mag-type ng keywords o pumili sa suggestions.",
        "no_results": "Walang nahanap na resulta. Subukan ulit o magtanong sa ibang paraan.",
        "no_access": "Wala kang access sa {module} module. Makipag-ugnayan sa admin.",
        "found_count": "May nahanap akong {count} resulta:",
        "found_single": "May nahanap akong 1 resulta:",
        "date_relaxed": "Walang laman ang saklaw ng petsa, so ipinapakita ko ang pinakabagong mga record:",
        "suggestions": "Maaari mong subukan ang mga ito:",
        "error": "May error. Subukan ulit.",
        "loading": "Nagtatanong...",
        "chat_hi": "Magandang araw! Ano ang tanong mo? Pwedeng mag-type ng keywords o pumili sa suggestions.",
        "chat_how": "Okay lang ako, salamat sa pagtatanong! Magtanong ka lang kung ano ang gusto mong malaman sa mga records.",
        "chat_thanks": "Walang anuman! May iba pa ba akong maitutulong sa iyo?",
        "chat_who": "Ako ang Smart Search Assistant. Nakakahanap ako ng records at nakakasagot ng mga tanong tungkol sa suppliers, customers, payments, journal entries, cash, advances, inventory, at financial reports. Subukan mo akong tanungin!",
        "chat_date": "Ngayon ay {date}.",
        "chat_time": "Ang kasalukuyang oras ay {time}.",
        "chat_weather": "Hindi ko ma-check ang live weather mula dito.",
        "module_names": {
            "ap": "Accounts Payable",
            "ar": "Accounts Receivable",
            "posting": "Journal Entries",
            "cash": "Cash & Bank",
            "assets": "Fixed Assets",
            "billing": "Billing",
            "fleet": "Fleet",
            "payroll": "Payroll",
            "tax": "Tax",
            "inventory": "Inventory",
            "workflow": "Approvals",
            "reporting": "Reports",
            "foundation": "Foundation",
        },
    },
    "en": {
        "greeting": "What would you like to know? Type keywords or pick a suggestion below.",
        "no_results": "No results found. Try rephrasing or asking differently.",
        "no_access": "You don't have access to the {module} module. Please contact admin.",
        "found_count": "Found {count} results:",
        "found_single": "Found 1 result:",
        "date_relaxed": "Nothing in that date range, so here are the most recent records:",
        "suggestions": "You can also try:",
        "error": "An error occurred. Please try again.",
        "loading": "Searching...",
        "chat_hi": "Hello! What would you like to know? Type keywords or pick a suggestion below.",
        "chat_how": "I'm doing great, thank you! Ask me anything about the accounting records — suppliers, payments, reports, and more.",
        "chat_thanks": "You're welcome! Anything else I can look up for you?",
        "chat_who": "I'm your Smart Search Assistant. I can look up records and answer questions about suppliers, customers, payments, journal entries, cash, advances, inventory, and financial reports. Try asking me a question!",
        "chat_date": "Today is {date}.",
        "chat_time": "The current time is {time}.",
        "chat_weather": "I can't check the live weather from here.",
        "module_names": {
            "ap": "Accounts Payable",
            "ar": "Accounts Receivable",
            "posting": "Journal Entries",
            "cash": "Cash & Bank",
            "assets": "Fixed Assets",
            "billing": "Billing",
            "fleet": "Fleet",
            "payroll": "Payroll",
            "tax": "Tax",
            "inventory": "Inventory",
            "workflow": "Approvals",
            "reporting": "Reports",
            "foundation": "Foundation",
        },
    },
}

SUGGESTIONS = {
    "ceb": [
        "Top 5 suppliers by amount",
        "Unsay pending CVs?",
        "Bank balance summary",
        "Unpaid invoices",
        "Journal entries last week",
    ],
    "tag": [
        "Top 5 suppliers by amount",
        "Ano ang pending CVs?",
        "Bank balance summary",
        "Unpaid invoices",
        "Journal entries last week",
    ],
    "en": [
        "Top 5 suppliers by amount",
        "What are the pending CVs?",
        "Bank balance summary",
        "Unpaid invoices",
        "Journal entries last week",
    ],
}


class ResponseFormatter:
    def __init__(self):
        self.language_detector = LanguageDetector()

    def format_response(
        self,
        results: list[dict],
        language: str | None = None,
        query_text: str = "",
        date_relaxed: bool = False,
        answer: dict | None = None,
    ) -> dict:
        if language is None:
            language = self.language_detector.detect(query_text)

        templates = RESPONSE_TEMPLATES.get(language, RESPONSE_TEMPLATES["en"])

        # Computed answer: it replaces the record sections entirely; the
        # widget renders the answer card, and the text is the summary
        # (denials are localized against the module label).
        if answer:
            if answer.get("kind") == "denied":
                text = templates["no_access"].format(module=answer.get("module") or answer.get("title") or "")
            else:
                text = answer.get("summary") or ""
                if answer.get("note"):
                    text = f"{text}\n\n{answer['note']}"
            return {
                "text": text,
                "results": [],
                "answer_block": answer,
                "suggestions": SUGGESTIONS.get(language, SUGGESTIONS["en"]),
                "language": language,
                "date_relaxed": False,
            }

        if not results:
            suggestions = self._get_contextual_suggestions(query_text, language)
            return {
                "text": templates["no_results"],
                "results": [],
                "suggestions": suggestions,
                "language": language,
                "date_relaxed": False,
            }

        total_count = sum(r.get("count", len(r.get("items", []))) for r in results)
        if total_count == 1:
            header = templates["found_single"]
        else:
            header = templates["found_count"].format(count=total_count)

        if date_relaxed:
            header = templates["date_relaxed"] + "\n" + header

        sections = []
        for result_group in results:
            module = result_group.get("module", "")
            label = result_group.get("label") or templates["module_names"].get(module, module)
            items = result_group.get("items", [])
            if not items:
                continue
            sections.append({
                "module": module,
                "module_name": label,
                "count": result_group.get("count", len(items)),
                "items": items,
            })

        return {
            "text": header,
            "results": sections,
            "suggestions": SUGGESTIONS.get(language, SUGGESTIONS["en"]),
            "language": language,
            "date_relaxed": date_relaxed,
        }

    def _get_contextual_suggestions(self, query_text: str, language: str) -> list[str]:
        query_lower = query_text.lower()
        suggestions = []

        if any(kw in query_lower for kw in ["supplier", "vendor", "payee"]):
            suggestions.extend([
                "Top 5 suppliers by amount",
                "Show all suppliers",
                "Supplier with most POs",
            ])
        elif any(kw in query_lower for kw in ["customer", "client", "buyer"]):
            suggestions.extend([
                "Top 5 customers by amount",
                "Show all customers",
                "Customer with most invoices",
            ])
        elif any(kw in query_lower for kw in ["payment", "check", "cv", "voucher"]):
            suggestions.extend([
                "Pending CVs",
                "Recent payments",
                "Total payments this month",
            ])
        elif any(kw in query_lower for kw in ["invoice", "receipt", "collection"]):
            suggestions.extend([
                "Unpaid invoices",
                "Recent receipts",
                "Total collections this month",
            ])
        elif any(kw in query_lower for kw in ["bank", "transfer", "cash"]):
            suggestions.extend([
                "Bank balance summary",
                "Recent transfers",
                "Cash position",
            ])
        elif any(kw in query_lower for kw in ["journal", "entry", "transaction", "je"]):
            suggestions.extend([
                "Recent journal entries",
                "Entries last week",
                "Entries this month",
            ])
        elif any(kw in query_lower for kw in ["asset", "equipment", "vehicle"]):
            suggestions.extend([
                "All assets",
                "Assets by category",
                "Recent asset additions",
            ])
        elif any(kw in query_lower for kw in ["tax", "vat", "withholding"]):
            suggestions.extend([
                "VAT summary",
                "WHT certificates",
                "Tax calendar",
            ])
        else:
            suggestions = SUGGESTIONS.get(language, SUGGESTIONS["en"])

        return suggestions[:5]

    def format_error(self, error_message: str, language: str = "en") -> dict:
        templates = RESPONSE_TEMPLATES.get(language, RESPONSE_TEMPLATES["en"])
        return {
            "text": templates["error"],
            "results": [],
            "suggestions": SUGGESTIONS.get(language, SUGGESTIONS["en"]),
            "language": language,
        }

    def get_greeting(self, language: str = "en") -> dict:
        templates = RESPONSE_TEMPLATES.get(language, RESPONSE_TEMPLATES["en"])
        return {
            "text": templates["greeting"],
            "results": [],
            "suggestions": SUGGESTIONS.get(language, SUGGESTIONS["en"]),
            "language": language,
        }
