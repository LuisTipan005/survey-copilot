"""
Unit tests for the AnswerMatcher 3-tier cascade.
Tests cover exact match, Jaccard token overlap, fuzzy matching,
and edge cases like empty inputs and prefix stripping.
"""
import pytest
import sys
import os

# Add the backend app to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.answer_matcher import AnswerMatcher


@pytest.fixture
def matcher():
    return AnswerMatcher()


class TestTier1ExactNormalized:
    """Tier 1: Exact match after normalization."""

    def test_exact_match(self, matcher):
        options = [
            "Un dispositivo que amplifica señales",
            "Un dispositivo que determina la mejor ruta para reenviar paquetes",
            "Un dispositivo que asigna direcciones IP",
        ]
        result = matcher.match("Un dispositivo que determina la mejor ruta para reenviar paquetes", options)
        assert result == 1

    def test_exact_match_case_insensitive(self, matcher):
        options = ["Transferencia de archivos sin cifrado", "Comunicación cifrada y segura"]
        result = matcher.match("transferencia de archivos sin cifrado", options)
        assert result == 0

    def test_exact_match_strips_prefix(self, matcher):
        """JS strips prefix but LLM might still include it — matcher should handle both."""
        options = ["Un dispositivo que amplifica señales", "Un dispositivo que reenvía paquetes"]
        # LLM returns with prefix that original doesn't have
        result = matcher.match("a. Un dispositivo que amplifica señales", options)
        assert result == 0

    def test_exact_match_with_extra_whitespace(self, matcher):
        options = ["service password-encryption"]
        result = matcher.match("  service   password-encryption  ", options)
        assert result == 0


class TestTier2JaccardTokenOverlap:
    """Tier 2: Token overlap when LLM paraphrases slightly."""

    def test_partial_quote(self, matcher):
        """LLM quotes most words but drops a few."""
        options = [
            "Un dispositivo que amplifica señales inalámbricas",
            "Un dispositivo que determina la mejor ruta para reenviar paquetes",
            "Un dispositivo que asigna direcciones IP a clientes",
        ]
        # LLM drops "para reenviar"
        result = matcher.match("Un dispositivo que determina la mejor ruta de paquetes", options)
        assert result == 1

    def test_reordered_words(self, matcher):
        """LLM reorders words but keeps the same meaning."""
        options = [
            "Transferencia de archivos sin cifrado",
            "Comunicación cifrada y segura",
            "Protocolo para navegación web",
        ]
        result = matcher.match("archivos transferencia sin cifrado", options)
        assert result == 0


class TestTier3FuzzySequence:
    """Tier 3: Fuzzy matching for minor character-level differences."""

    def test_minor_typo(self, matcher):
        options = ["service password-encryption", "enable secret X"]
        result = matcher.match("service pasword-encryption", options)
        assert result == 0

    def test_slight_truncation(self, matcher):
        options = [
            "La distancia administrativa más baja",
            "El código del protocolo como para OSPF",
        ]
        result = matcher.match("La distancia administrativa más", options)
        assert result == 0


class TestNoMatch:
    """Cases where no tier should match."""

    def test_completely_different(self, matcher):
        options = ["Transferencia de archivos", "Comunicación cifrada"]
        result = matcher.match("El precio del café en Colombia", options)
        assert result is None

    def test_empty_llm_text(self, matcher):
        options = ["Option A", "Option B"]
        result = matcher.match("", options)
        assert result is None

    def test_empty_options(self, matcher):
        result = matcher.match("Some text", [])
        assert result is None


class TestMatchMany:
    """Test batch matching."""

    def test_match_many_partial_success(self, matcher):
        options = [
            "Transferencia de archivos sin cifrado",
            "Comunicación cifrada y segura",
            "Protocolo para navegación web",
            "Transmisión de datos en texto plano",
        ]
        llm_texts = [
            "Comunicación cifrada y segura",          # exact → index 1
            "garbage text that won't match anything",  # fail
            "Transmisión de datos en texto plano",     # exact → index 3
        ]
        result = matcher.match_many(llm_texts, options)
        assert result == [1, 3]

    def test_match_many_all_succeed(self, matcher):
        options = ["Alpha", "Beta", "Gamma"]
        result = matcher.match_many(["Alpha", "Beta"], options)
        assert result == [0, 1]


class TestJSONExtraction:
    """Test the bracket-balanced JSON extractor in SurveyAnalyzer."""

    def test_clean_json(self):
        from app.services.survey_analyzer import SurveyAnalyzer
        raw = '{"selected": ["Option A"], "reasoning": "Because..."}'
        result = SurveyAnalyzer._extract_json_block(raw)
        assert result == raw

    def test_json_with_preamble(self):
        from app.services.survey_analyzer import SurveyAnalyzer
        raw = 'Based on my knowledge, the answer is: {"selected": ["Option A"], "reasoning": "Because..."} Hope this helps!'
        result = SurveyAnalyzer._extract_json_block(raw)
        assert result == '{"selected": ["Option A"], "reasoning": "Because..."}'

    def test_json_with_nested_braces(self):
        from app.services.survey_analyzer import SurveyAnalyzer
        raw = '{"selected": ["Option {A}"], "reasoning": "Uses {braces}"}'
        result = SurveyAnalyzer._extract_json_block(raw)
        assert result == raw

    def test_no_json(self):
        from app.services.survey_analyzer import SurveyAnalyzer
        raw = 'The answer is Option A, which is correct.'
        result = SurveyAnalyzer._extract_json_block(raw)
        assert result is None


class TestJSONRepair:
    """Test the JSON structural repair."""

    def test_trailing_comma(self):
        from app.services.survey_analyzer import SurveyAnalyzer
        broken = '{"selected": ["A",], "reasoning": "test",}'
        repaired = SurveyAnalyzer._repair_json(broken)
        import json
        data = json.loads(repaired)
        assert data["selected"] == ["A"]

    def test_single_quotes(self):
        from app.services.survey_analyzer import SurveyAnalyzer
        broken = "{'selected': ['A'], 'reasoning': 'test'}"
        repaired = SurveyAnalyzer._repair_json(broken)
        import json
        data = json.loads(repaired)
        assert data["selected"] == ["A"]

    def test_markdown_fences(self):
        from app.services.survey_analyzer import SurveyAnalyzer
        broken = '```json\n{"selected": ["A"]}\n```'
        repaired = SurveyAnalyzer._repair_json(broken)
        import json
        data = json.loads(repaired)
        assert data["selected"] == ["A"]
