"""Unit tests for SemanticCache (src/agent/cache.py). Uses the real local
embedder (fastembed, ONNX, no API key/network needed), not a mock of it --
similarity threshold behavior is exactly the kind of thing a fake
embedding vector can't meaningfully exercise.
"""

from __future__ import annotations

from src.agent.cache import SemanticCache


def test_a_fresh_cache_is_empty_and_misses_everything():
    cache: SemanticCache[str] = SemanticCache()
    assert len(cache) == 0
    assert cache.get("Which game has the most players?") is None


def test_put_then_get_the_exact_same_question_is_a_hit():
    cache: SemanticCache[str] = SemanticCache()
    cache.put("Which game has the highest peak concurrent player count?", "answer-1")
    hit = cache.get("Which game has the highest peak concurrent player count?")
    assert hit is not None
    value, matched_question = hit
    assert value == "answer-1"
    assert matched_question == "Which game has the highest peak concurrent player count?"


def test_a_genuinely_different_question_is_a_miss():
    cache: SemanticCache[str] = SemanticCache()
    cache.put("Which game has the highest peak concurrent player count?", "answer-1")
    hit = cache.get("Is the price difference between Action and Strategy games significant?")
    assert hit is None


def test_a_close_natural_paraphrase_can_hit_at_the_real_default_threshold():
    cache: SemanticCache[str] = SemanticCache()  # real default threshold, not loosened for the test
    cache.put("Which game has the highest peak concurrent player count?", "answer-1")
    hit = cache.get("Which game has the highest peak concurrent players?")
    assert hit is not None
    assert hit[0] == "answer-1"


def test_a_stricter_threshold_can_turn_a_near_paraphrase_into_a_miss():
    # Demonstrates the threshold is load-bearing, not decorative: the same
    # near-paraphrase that hits at the default threshold can legitimately
    # miss at a stricter one.
    cache: SemanticCache[str] = SemanticCache(similarity_threshold=0.999999)
    cache.put("Which game has the highest peak concurrent player count?", "answer-1")
    hit = cache.get("Which game has the highest peak concurrent players?")
    assert hit is None


def test_len_reflects_the_real_number_of_entries():
    cache: SemanticCache[str] = SemanticCache()
    cache.put("question one", "a1")
    cache.put("question two", "a2")
    assert len(cache) == 2


def test_max_entries_evicts_the_oldest_entry_first():
    cache: SemanticCache[str] = SemanticCache(max_entries=2)
    cache.put("first question, entirely unrelated to the others", "a1")
    cache.put("second question, also entirely unrelated", "a2")
    cache.put("third question, also entirely unrelated", "a3")
    assert len(cache) == 2
    # The oldest ("first question...") should have been evicted -- an
    # exact-text lookup for it must now miss.
    assert cache.get("first question, entirely unrelated to the others") is None
    assert cache.get("third question, also entirely unrelated") is not None
