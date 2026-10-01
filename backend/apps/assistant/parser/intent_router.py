from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IntentMatch:
    module: str
    executor: str
    confidence: float = 1.0


MODULE_KEYWORDS: dict[str, list[str]] = {
    "ap": [
        "supplier", "vendor", "payee", "cv", "check", "voucher",
        "rfp", "purchase", "order", "po", "conso", "advance",
        "supplier_list", "rfp_list", "po_list", "cv_list",
    ],
    "ar": [
        "customer", "client", "buyer", "invoice", "receipt",
        "deposit", "sales", "si", "acknowledgment",
        "customer_list", "si_list", "receipt_list",
    ],
    "posting": [
        "journal", "je", "entry", "transaction", "gl",
        "general", "ledger", "posting",
        "je_list", "general_journal",
    ],
    "cash": [
        "bank", "transfer", "pcf", "petty", "reconciliation",
        "cash", "cycle", "short", "collectibles", "ftv",
        "bank_list", "transfers", "pcf_list", "recon_list",
    ],
    "assets": [
        "asset", "equipment", "vehicle", "depreciation",
        "asset_list",
    ],
    "billing": [
        "billing", "intercompany", "stpc", "third-party",
        "billing_list",
    ],
    "fleet": [
        "vehicle", "fuel", "fleet",
        "fleet_fuel",
    ],
    "payroll": [
        "payroll", "salary", "compensation",
    ],
    "tax": [
        "tax", "vat", "withholding", "wht", "bir",
        "tax_dashboard", "tax_vat", "tax_wht",
    ],
    "inventory": [
        "inventory", "stock", "item",
    ],
    "workflow": [
        "approval", "pending", "workflow",
        "my_approvals",
    ],
    "reporting": [
        "report", "reports", "statement", "sheet",
        "trial", "financial",
    ],
    "foundation": [
        "account", "coa", "chart", "segment", "company",
        "coa_list",
    ],
}

AGGREGATE_KEYWORDS = ["top", "highest", "biggest", "summary", "total",
                       "rank", "most", "least", "average", "pila"]
COMPARE_KEYWORDS = ["compare", "versus", "vs", "difference", "banding"]


class IntentRouter:
    def route(self, keywords: list[str], intent: str) -> list[IntentMatch]:
        matches: dict[str, float] = {}

        for kw in keywords:
            kw_lower = kw.lower()
            for module, module_kws in MODULE_KEYWORDS.items():
                if kw_lower in module_kws:
                    matches[module] = matches.get(module, 0) + 1.0
                else:
                    for mkw in module_kws:
                        if kw_lower in mkw or mkw in kw_lower:
                            matches[module] = matches.get(module, 0) + 0.5

        if intent in ("summary", "compare"):
            for module in list(matches.keys()):
                matches[module] += 0.2

        if not matches:
            matches["posting"] = 0.3

        sorted_matches = sorted(matches.items(), key=lambda x: x[1], reverse=True)
        results = []
        for module, score in sorted_matches[:3]:
            executor_name = f"{module}_executor"
            results.append(IntentMatch(
                module=module,
                executor=executor_name,
                confidence=min(score, 1.0),
            ))
        return results
