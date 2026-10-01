from apps.assistant.parser.intent_router import IntentRouter


class TestIntentRouter:
    def setup_method(self):
        self.router = IntentRouter()

    def test_route_supplier_to_ap(self):
        matches = self.router.route(["supplier", "payment"], "lookup")
        assert any(m.module == "ap" for m in matches)

    def test_route_customer_to_ar(self):
        matches = self.router.route(["customer", "invoice"], "lookup")
        assert any(m.module == "ar" for m in matches)

    def test_route_journal_to_posting(self):
        matches = self.router.route(["journal", "entry"], "lookup")
        assert any(m.module == "posting" for m in matches)

    def test_route_bank_to_cash(self):
        matches = self.router.route(["bank", "transfer"], "lookup")
        assert any(m.module == "cash" for m in matches)

    def test_route_multi_intent(self):
        matches = self.router.route(["supplier", "customer"], "lookup")
        modules = [m.module for m in matches]
        assert "ap" in modules
        assert "ar" in modules

    def test_route_unknown_defaults_to_posting(self):
        matches = self.router.route(["xyz"], "lookup")
        assert matches[0].module == "posting"

    def test_route_asset_to_assets(self):
        matches = self.router.route(["asset", "equipment"], "lookup")
        assert any(m.module == "assets" for m in matches)

    def test_route_tax_keywords(self):
        matches = self.router.route(["vat", "tax"], "lookup")
        assert any(m.module == "tax" for m in matches)
