import re
import logging
import difflib
import unicodedata

logger = logging.getLogger(__name__)


class AnswerMatcher:
    """
    3-tier cascade for mapping LLM text answers back to original option indices.

    Tier 1 — Exact Normalized:
        Lowercase + strip option prefixes + remove punctuation + collapse whitespace.
        If the normalized LLM text equals a normalized option, it's a guaranteed match.

    Tier 2 — Token Overlap (Jaccard):
        Treats text as a bag of significant words (len >= 3, no stop words).
        Scores by |intersection| / |union|. Threshold: 0.55

    Tier 3 — Fuzzy Sequence (difflib.SequenceMatcher):
        Character-level similarity ratio on normalized strings. Threshold: 0.60

    Each tier is tried in order; the first match wins.
    """

    JACCARD_THRESHOLD = 0.55
    FUZZY_THRESHOLD = 0.60

    # Common Spanish stop words to exclude from token comparison
    STOP_WORDS = frozenset({
        "el", "la", "los", "las", "un", "una", "unos", "unas",
        "de", "del", "en", "con", "por", "para", "como", "que",
        "es", "son", "fue", "ser", "más", "muy", "sin", "sobre",
        "al", "se", "su", "sus", "nos", "les", "lo", "le",
        "no", "sí", "este", "esta", "esto", "ese", "esa", "eso",
        "and", "the", "is", "are", "was", "for", "from", "with",
        "not", "but", "has", "had", "can", "will", "its", "this",
        "that", "which", "who", "what", "how", "all", "each",
    })

    # ─── Public API ───────────────────────────────────────────────

    def match(self, llm_text: str, options: list[str]) -> int | None:
        """
        Map a single LLM text answer to the best matching option index.

        Returns the index into `options`, or None if no tier matched.
        """
        if not llm_text or not options:
            return None

        norm_llm = self._normalize(llm_text)
        norm_options = [self._normalize(opt) for opt in options]

        # Tier 1: Exact normalized match
        for i, norm_opt in enumerate(norm_options):
            if norm_llm == norm_opt:
                logger.info(f"AnswerMatcher: Tier 1 (exact) matched index {i}")
                return i

        # Tier 2: Token overlap (Jaccard)
        tokens_llm = self._tokenize(llm_text)
        if tokens_llm:
            best_jaccard = 0.0
            best_jaccard_idx = -1
            for i, opt in enumerate(options):
                tokens_opt = self._tokenize(opt)
                if not tokens_opt:
                    continue
                score = self._jaccard(tokens_llm, tokens_opt)
                if score > best_jaccard:
                    best_jaccard = score
                    best_jaccard_idx = i

            if best_jaccard >= self.JACCARD_THRESHOLD and best_jaccard_idx >= 0:
                logger.info(
                    f"AnswerMatcher: Tier 2 (jaccard={best_jaccard:.3f}) "
                    f"matched index {best_jaccard_idx}"
                )
                return best_jaccard_idx

        # Tier 3: Fuzzy sequence matching
        best_ratio = 0.0
        best_ratio_idx = -1
        for i, norm_opt in enumerate(norm_options):
            ratio = difflib.SequenceMatcher(None, norm_llm, norm_opt).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_ratio_idx = i

        if best_ratio >= self.FUZZY_THRESHOLD and best_ratio_idx >= 0:
            logger.info(
                f"AnswerMatcher: Tier 3 (fuzzy={best_ratio:.3f}) "
                f"matched index {best_ratio_idx}"
            )
            return best_ratio_idx

        logger.warning(
            f"AnswerMatcher: No tier matched for LLM text: "
            f"'{llm_text[:80]}...' (best fuzzy={best_ratio:.3f})"
        )
        return None

    def match_many(self, llm_texts: list[str], options: list[str]) -> list[int]:
        """
        Map multiple LLM text answers to option indices.
        Skips unresolvable ones (returns only successful matches).
        """
        results = []
        for text in llm_texts:
            idx = self.match(text, options)
            if idx is not None:
                results.append(idx)
        return results

    # ─── Normalization ────────────────────────────────────────────

    @staticmethod
    def _normalize(text: str) -> str:
        """
        Normalize text for comparison:
        1. Unicode NFKC normalization
        2. Lowercase
        3. Strip option prefixes (a. b) c: etc.)
        4. Remove all non-alphanumeric except spaces
        5. Collapse whitespace
        """
        if not text:
            return ""
        # Unicode normalization to collapse typographic variants
        text = unicodedata.normalize("NFKC", text)
        text = text.lower()
        # Strip option prefix: "a. ", "b) ", "1. ", etc.
        text = re.sub(r'^[a-z0-9][.):\-]\s*', '', text)
        # Remove punctuation but keep letters (including accented), digits, and spaces
        text = re.sub(r'[^\w\s]', '', text)
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """
        Extract significant words: length >= 3, lowercased, no stop words.
        """
        words = re.findall(r'\b\w{3,}\b', text.lower())
        return {w for w in words if w not in AnswerMatcher.STOP_WORDS}

    @staticmethod
    def _jaccard(set_a: set, set_b: set) -> float:
        """Jaccard similarity: |A ∩ B| / |A ∪ B|"""
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union)


# Singleton
answer_matcher = AnswerMatcher()
