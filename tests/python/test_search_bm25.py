"""Unit tests for BM25 search in brain_index.

Tests the BM25 class directly (no disk I/O needed).
"""
import pytest
import sys
from pathlib import Path

# Import BM25 and helpers directly from brain_index
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "runtime" / "lib"))
from brain_index import BM25, tokenize, snippet_for


class TestTokenize:
    """Tests for the tokenize() helper."""

    def test_simple_words(self):
        assert tokenize("hello world") == ["hello", "world"]

    def test_case_folding(self):
        assert tokenize("Hello World") == ["hello", "world"]

    def test_hyphenated_term(self):
        tokens = tokenize("brain-index")
        assert "brain-index" in tokens

    def test_empty_string(self):
        assert tokenize("") == []

    def test_punctuation_stripped(self):
        tokens = tokenize("hello, world!")
        assert tokens == ["hello", "world"]


class TestBM25:
    """Tests for BM25 scoring."""

    def _make_corpus(self, texts):
        return [tokenize(t) for t in texts]

    def test_relevant_doc_scores_higher(self):
        texts = [
            "apple fruit red sweet",
            "banana yellow fruit tropical",
            "car engine motor vehicle",
        ]
        corpus = self._make_corpus(texts)
        bm25 = BM25(corpus)
        query = tokenize("apple")
        scores = [bm25.score(query, doc) for doc in corpus]
        assert scores[0] > scores[1]
        assert scores[0] > scores[2]

    def test_irrelevant_doc_scores_zero(self):
        texts = ["fruit apple banana", "car engine motor"]
        corpus = self._make_corpus(texts)
        bm25 = BM25(corpus)
        query = tokenize("apple")
        scores = [bm25.score(query, doc) for doc in corpus]
        assert scores[0] > 0
        assert scores[1] == 0.0

    def test_empty_query_scores_zero(self):
        corpus = self._make_corpus(["hello world"])
        bm25 = BM25(corpus)
        assert bm25.score([], corpus[0]) == 0.0

    def test_empty_doc_scores_zero(self):
        corpus = self._make_corpus(["hello world"])
        bm25 = BM25(corpus)
        assert bm25.score(tokenize("hello"), []) == 0.0

    def test_empty_corpus_avgdl(self):
        """BM25 with empty corpus should not crash."""
        bm25 = BM25([])
        assert bm25.avgdl == 0.0
        assert bm25.score(["hello"], ["hello"]) == 0.0

    def test_idf_common_term_lower(self):
        """Terms appearing in many docs get lower IDF."""
        # "common" appears in all 3, "rare" in only 1
        corpus = self._make_corpus([
            "common rare",
            "common other",
            "common other",
        ])
        bm25 = BM25(corpus)
        assert bm25.idf("rare") > bm25.idf("common")

    def test_top_result_is_best_match(self):
        """Searching a list of docs returns the best match first."""
        docs_raw = [
            {"id": "x", "kind": "wiki", "page_type": "concept",
             "title": "Apple", "text": "fruit apple juicy", "path": "wiki/x.md", "mtime": 0.0},
            {"id": "y", "kind": "wiki", "page_type": "concept",
             "title": "Banana", "text": "fruit banana tropical", "path": "wiki/y.md", "mtime": 0.0},
            {"id": "z", "kind": "wiki", "page_type": "concept",
             "title": "Car", "text": "vehicle motor engine", "path": "wiki/z.md", "mtime": 0.0},
        ]
        # Use BM25 directly on tokenized texts
        corpus = [tokenize(d["text"]) for d in docs_raw]
        bm25 = BM25(corpus)
        query = tokenize("apple")
        scored = [(bm25.score(query, doc), d["id"]) for doc, d in zip(corpus, docs_raw)]
        scored.sort(key=lambda item: item[0], reverse=True)
        assert scored[0][1] == "x"


class TestSnippetFor:
    """Tests for snippet_for() helper."""

    def test_returns_string(self):
        result = snippet_for("hello world apple", ["apple"])
        assert isinstance(result, str)

    def test_contains_query_context(self):
        text = "prefix " * 20 + "apple is great " + "suffix " * 20
        result = snippet_for(text, ["apple"])
        assert "apple" in result

    def test_no_match_returns_start(self):
        """When query term not found, snippet starts from beginning."""
        result = snippet_for("hello world", ["nothere"])
        assert "hello" in result

    def test_empty_text(self):
        result = snippet_for("", ["apple"])
        assert result == ""
