from apps.assistant.formatter.language_detector import LanguageDetector


class TestLanguageDetector:
    def setup_method(self):
        self.detector = LanguageDetector()

    def test_detect_english(self):
        assert self.detector.detect("show me the suppliers") == "en"

    def test_detect_cebuano(self):
        assert self.detector.detect("kinsa ang supplier sa item X") == "ceb"

    def test_detect_tagalog(self):
        assert self.detector.detect("sino ang supplier ng item X") == "tag"

    def test_detect_mixed_defaults_to_english(self):
        result = self.detector.detect("show suppliers")
        assert result == "en"

    def test_detect_cebuano_with_english_words(self):
        result = self.detector.detect("pila ang total payments")
        assert result == "ceb"
