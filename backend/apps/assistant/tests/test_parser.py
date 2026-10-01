from datetime import date, timedelta

from apps.assistant.parser.query_parser import QueryParser, ParsedQuery


class TestQueryParser:
    def setup_method(self):
        self.parser = QueryParser()

    def test_parse_simple_query(self):
        result = self.parser.parse("show me suppliers")
        assert isinstance(result, ParsedQuery)
        assert result.raw == "show me suppliers"
        assert "suppliers" in result.keywords

    def test_parse_with_entities(self):
        result = self.parser.parse('find "ABC Corp" transactions')
        assert "ABC Corp" in result.entities

    def test_parse_date_range_last_month(self):
        result = self.parser.parse("show payments last month")
        assert result.date_from is not None
        assert result.date_to is not None
        assert result.date_from < result.date_to

    def test_parse_date_range_this_year(self):
        result = self.parser.parse("transactions this year")
        today = date.today()
        assert result.date_from == today.replace(month=1, day=1)
        assert result.date_to == today

    def test_parse_date_range_specific_year(self):
        result = self.parser.parse("show entries 2024")
        assert result.date_from == date(2024, 1, 1)
        assert result.date_to == date(2024, 12, 31)

    def test_detect_intent_lookup(self):
        result = self.parser.parse("show me suppliers")
        assert result.intent == "lookup"

    def test_detect_intent_summary(self):
        result = self.parser.parse("total payments to suppliers")
        assert result.intent == "summary"

    def test_extract_keywords_removes_stop_words(self):
        result = self.parser.parse("show me the suppliers")
        assert "show" not in result.keywords
        assert "me" not in result.keywords
        assert "the" not in result.keywords
        assert "suppliers" in result.keywords

    def test_parse_cebuano_query(self):
        result = self.parser.parse("kinsa ang supplier sa item X?")
        assert "supplier" in result.keywords
        assert "item" in result.keywords

    def test_parse_empty_entities(self):
        result = self.parser.parse("show all")
        assert result.entities == []

    def test_browse_query_has_no_search_terms(self):
        result = self.parser.parse("show me list of customers")
        assert result.search_terms == []

    def test_filler_words_are_not_search_terms(self):
        result = self.parser.parse(
            "who did I pay when I ordered tire recently, i forgot the supplier"
        )
        assert "tire" in result.search_terms
        for junk in {"paid", "recently", "forgot", "need", "who", "supplier"}:
            assert junk not in result.search_terms

    def test_top_n_and_amount_detected(self):
        result = self.parser.parse("top 5 fixed assets?")
        assert result.top_n == 5
        assert result.sort_amount is True
        assert "fixed" not in result.search_terms

    def test_status_detected(self):
        result = self.parser.parse("What are the pending CVs?")
        assert result.status == "pending"
        assert "pending" not in result.search_terms

    def test_recency_words_are_not_search_terms_and_trigger_top(self):
        result = self.parser.parse("what is the very recent check voucher that was processed?")
        assert result.search_terms == []
        assert result.top_n == 5

    def test_needs_approval_phrase_maps_to_pending(self):
        result = self.parser.parse("what is latest FTV that needs approval")
        assert result.status == "pending"
        for junk in {"needs", "approval", "latest", "ftv"}:
            assert junk not in result.search_terms

    def test_conso_and_filler_not_search_terms(self):
        result = self.parser.parse(
            "are there pending things in CONSO batches that are not yet approved or posted?"
        )
        assert result.status == "pending"
        for junk in {"things", "batches", "conso", "yet", "approved", "posted"}:
            assert junk not in result.search_terms

    def test_numeric_id_is_a_search_term(self):
        result = self.parser.parse("details of cv 12")
        assert "12" in result.search_terms
        assert "details" not in result.search_terms

    def test_document_code_is_a_search_term(self):
        result = self.parser.parse("find CV-2026-0009")
        assert any("2026-0009" in t for t in result.search_terms)

    def test_year_is_not_a_search_term(self):
        result = self.parser.parse("transactions 2025")
        assert "2025" not in result.search_terms
        assert result.date_from is not None and result.date_from.year == 2025

    def test_top_quantity_number_is_not_a_search_term(self):
        result = self.parser.parse("top 5 customers")
        assert result.top_n == 5
        assert "5" not in result.search_terms

    def test_process_verb_excluded_leaves_only_id(self):
        result = self.parser.parse("who processes the cv 11")
        assert "processes" not in result.search_terms
        assert "cv" not in result.search_terms
        assert "11" in result.search_terms

    def test_named_supplier_is_descriptive_term(self):
        result = self.parser.parse("which RFP was payable to cartrack")
        assert "cartrack" in result.search_terms
