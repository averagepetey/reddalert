"""Tests for the proximity matcher module."""

import pytest

from app.services.normalizer import normalize_text, NormalizedResult
from app.services.matcher import find_matches, KeywordConfig, MatchResult


def _make_content(text: str) -> NormalizedResult:
    """Helper to normalize text for matcher tests."""
    return normalize_text(text)


class TestSingleWordMatch:
    """Test matching single-word phrases."""

    def test_single_word_found(self):
        content = _make_content("I love arbitrage betting strategies")
        keyword = KeywordConfig(phrases=[["arbitrage"]])
        results = find_matches(content, keyword)
        assert len(results) == 1
        assert results[0].matched_phrase == "arbitrage"

    def test_single_word_not_found(self):
        content = _make_content("I love sports and games")
        keyword = KeywordConfig(phrases=[["arbitrage"]])
        results = find_matches(content, keyword)
        assert len(results) == 0

    def test_single_word_multiple_occurrences(self):
        content = _make_content("arbitrage is great and arbitrage is profitable")
        keyword = KeywordConfig(phrases=[["arbitrage"]])
        results = find_matches(content, keyword)
        assert len(results) == 2

    def test_case_insensitive(self):
        content = _make_content("ARBITRAGE is what I do")
        keyword = KeywordConfig(phrases=[["arbitrage"]])
        results = find_matches(content, keyword)
        assert len(results) == 1


class TestMultiWordProximity:
    """Test multi-word phrase matching with proximity window."""

    def test_adjacent_words_match(self):
        content = _make_content("I tried arbitrage betting last week")
        keyword = KeywordConfig(phrases=[["arbitrage", "betting"]])
        results = find_matches(content, keyword)
        assert len(results) == 1
        assert results[0].matched_phrase == "arbitrage betting"

    def test_words_within_window(self):
        content = _make_content(
            "arbitrage is a common strategy in sports betting"
        )
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"]],
            proximity_window=15,
        )
        results = find_matches(content, keyword)
        assert len(results) == 1

    def test_words_outside_window(self):
        # Build text where "arbitrage" and "betting" are far apart
        filler = " ".join(["word"] * 20)
        content = _make_content(f"arbitrage {filler} betting")
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"]],
            proximity_window=5,
        )
        results = find_matches(content, keyword)
        assert len(results) == 0

    def test_three_word_phrase(self):
        content = _make_content(
            "the sports arbitrage betting tool is excellent"
        )
        keyword = KeywordConfig(
            phrases=[["sports", "arbitrage", "betting"]],
            proximity_window=5,
        )
        results = find_matches(content, keyword)
        assert len(results) == 1

    def test_partial_phrase_no_match(self):
        content = _make_content("I love arbitrage and gaming")
        keyword = KeywordConfig(phrases=[["arbitrage", "betting"]])
        results = find_matches(content, keyword)
        assert len(results) == 0


class TestORGroups:
    """Test OR group matching (any phrase in group matches)."""

    def test_first_phrase_matches(self):
        content = _make_content("I use arbitrage betting tools")
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"], ["sports", "gambling"]]
        )
        results = find_matches(content, keyword)
        assert len(results) >= 1
        assert any(r.matched_phrase == "arbitrage betting" for r in results)

    def test_second_phrase_matches(self):
        content = _make_content("I enjoy sports gambling on weekends")
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"], ["sports", "gambling"]]
        )
        results = find_matches(content, keyword)
        assert len(results) >= 1
        assert any(r.matched_phrase == "sports gambling" for r in results)

    def test_both_phrases_match(self):
        content = _make_content(
            "I do arbitrage betting and also sports gambling"
        )
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"], ["sports", "gambling"]]
        )
        results = find_matches(content, keyword)
        assert len(results) >= 2

    def test_no_phrase_matches(self):
        content = _make_content("I enjoy reading books and cooking")
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"], ["sports", "gambling"]]
        )
        results = find_matches(content, keyword)
        assert len(results) == 0


class TestNegationFiltering:
    """Test exclusion word filtering."""

    def test_anywhere_exclusion_blocks_match(self):
        content = _make_content(
            "arbitrage betting is risky and a scam according to some"
        )
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"]],
            exclusions=["scam"],
            exclusion_scope="anywhere",
        )
        results = find_matches(content, keyword)
        assert len(results) == 0

    def test_anywhere_exclusion_no_exclusion_word(self):
        content = _make_content("arbitrage betting is profitable")
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"]],
            exclusions=["scam"],
            exclusion_scope="anywhere",
        )
        results = find_matches(content, keyword)
        assert len(results) == 1

    def test_proximity_exclusion_within_window(self):
        content = _make_content(
            "arbitrage betting is a total scam"
        )
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"]],
            exclusions=["scam"],
            exclusion_scope="proximity",
            proximity_window=15,
        )
        results = find_matches(content, keyword)
        assert len(results) == 0

    def test_proximity_exclusion_outside_window(self):
        filler = " ".join(["other"] * 20)
        content = _make_content(
            f"arbitrage betting is great {filler} but some say scam"
        )
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"]],
            exclusions=["scam"],
            exclusion_scope="proximity",
            proximity_window=5,
        )
        results = find_matches(content, keyword)
        assert len(results) == 1

    def test_multiple_exclusions(self):
        content = _make_content("arbitrage betting is spam and fraud")
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"]],
            exclusions=["scam", "spam", "fraud"],
            exclusion_scope="anywhere",
        )
        results = find_matches(content, keyword)
        assert len(results) == 0

    def test_exclusion_case_insensitive(self):
        content = _make_content("ARBITRAGE BETTING is a SCAM")
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"]],
            exclusions=["scam"],
            exclusion_scope="anywhere",
        )
        results = find_matches(content, keyword)
        assert len(results) == 0


class TestRequireOrder:
    """Test token ordering constraints."""

    def test_correct_order_matches(self):
        content = _make_content("I tried arbitrage betting last week")
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"]],
            require_order=True,
        )
        results = find_matches(content, keyword)
        assert len(results) == 1

    def test_reversed_order_no_match(self):
        content = _make_content("betting on arbitrage opportunities")
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"]],
            require_order=True,
        )
        results = find_matches(content, keyword)
        assert len(results) == 0

    def test_order_not_required_reversed_matches(self):
        content = _make_content("betting on arbitrage opportunities")
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"]],
            require_order=False,
        )
        results = find_matches(content, keyword)
        assert len(results) == 1


class TestStemming:
    """Test stemming functionality."""

    def test_stemming_matches_variants(self):
        content = _make_content("he was betting on arbitrage opportunities")
        keyword = KeywordConfig(
            phrases=[["bet", "arbitrage"]],
            use_stemming=True,
        )
        results = find_matches(content, keyword)
        assert len(results) == 1

    def test_without_stemming_no_match(self):
        content = _make_content("he was betting on games")
        keyword = KeywordConfig(
            phrases=[["bet"]],
            use_stemming=False,
        )
        results = find_matches(content, keyword)
        assert len(results) == 0

    def test_stemming_exclusion(self):
        content = _make_content("arbitrage betting is scamming people")
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"]],
            exclusions=["scam"],
            use_stemming=True,
            exclusion_scope="anywhere",
        )
        results = find_matches(content, keyword)
        assert len(results) == 0


class TestSnippetGeneration:
    """Test snippet generation around matches."""

    def test_short_text_full_snippet(self):
        content = _make_content("arbitrage betting is great")
        keyword = KeywordConfig(phrases=[["arbitrage"]])
        results = find_matches(content, keyword)
        assert len(results) == 1
        assert results[0].snippet == "arbitrage betting is great"

    def test_long_text_snippet_around_match(self):
        prefix = "word " * 50
        suffix = " more" * 50
        content = _make_content(f"{prefix}arbitrage betting{suffix}")
        keyword = KeywordConfig(phrases=[["arbitrage"]])
        results = find_matches(content, keyword)
        assert len(results) == 1
        assert len(results[0].snippet) <= 200
        assert "arbitrage" in results[0].snippet

    def test_snippet_has_ellipsis_when_truncated(self):
        prefix = "word " * 50
        suffix = " more" * 50
        content = _make_content(f"{prefix}arbitrage betting{suffix}")
        keyword = KeywordConfig(phrases=[["arbitrage"]])
        results = find_matches(content, keyword)
        assert len(results) == 1
        snippet = results[0].snippet
        assert snippet.startswith("...") or snippet.endswith("...")


class TestProximityScore:
    """Test proximity score calculation."""

    def test_adjacent_tokens_score_1(self):
        content = _make_content("arbitrage betting today")
        keyword = KeywordConfig(phrases=[["arbitrage", "betting"]])
        results = find_matches(content, keyword)
        assert len(results) == 1
        assert results[0].proximity_score == 1.0

    def test_distant_tokens_lower_score(self):
        content = _make_content(
            "arbitrage is a very common and popular form of betting"
        )
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"]],
            proximity_window=15,
        )
        results = find_matches(content, keyword)
        assert len(results) == 1
        assert results[0].proximity_score < 1.0

    def test_single_token_always_score_1(self):
        content = _make_content("I love arbitrage opportunities")
        keyword = KeywordConfig(phrases=[["arbitrage"]])
        results = find_matches(content, keyword)
        assert len(results) == 1
        assert results[0].proximity_score == 1.0


class TestSpanIndexes:
    """Test that span_start and span_end point to correct positions."""

    def test_span_covers_matched_text(self):
        text = "hello arbitrage world"
        content = _make_content(text)
        keyword = KeywordConfig(phrases=[["arbitrage"]])
        results = find_matches(content, keyword)
        assert len(results) == 1
        span_text = content.normalized_text[
            results[0].span_start:results[0].span_end
        ]
        assert span_text == "arbitrage"

    def test_multi_word_span(self):
        text = "hello arbitrage betting world"
        content = _make_content(text)
        keyword = KeywordConfig(phrases=[["arbitrage", "betting"]])
        results = find_matches(content, keyword)
        assert len(results) == 1
        span_text = content.normalized_text[
            results[0].span_start:results[0].span_end
        ]
        assert "arbitrage" in span_text
        assert "betting" in span_text


class TestEmptyInputs:
    """Test handling of empty or minimal inputs."""

    def test_empty_content(self):
        content = _make_content("")
        keyword = KeywordConfig(phrases=[["test"]])
        results = find_matches(content, keyword)
        assert results == []

    def test_empty_phrases(self):
        content = _make_content("hello world")
        keyword = KeywordConfig(phrases=[])
        results = find_matches(content, keyword)
        assert results == []

    def test_empty_phrase_tokens(self):
        content = _make_content("hello world")
        keyword = KeywordConfig(phrases=[[]])
        results = find_matches(content, keyword)
        assert results == []


class TestMatchResultDataclass:
    """Test the MatchResult dataclass."""

    def test_fields_present(self):
        content = _make_content("arbitrage betting")
        keyword = KeywordConfig(phrases=[["arbitrage"]])
        results = find_matches(content, keyword)
        assert len(results) == 1
        r = results[0]
        assert hasattr(r, 'matched_phrase')
        assert hasattr(r, 'span_start')
        assert hasattr(r, 'span_end')
        assert hasattr(r, 'snippet')
        assert hasattr(r, 'proximity_score')
        assert hasattr(r, 'also_matched')

    def test_also_matched_default_empty(self):
        content = _make_content("arbitrage betting")
        keyword = KeywordConfig(phrases=[["arbitrage"]])
        results = find_matches(content, keyword)
        assert results[0].also_matched == []


class TestKeywordConfigDataclass:
    """Test the KeywordConfig dataclass."""

    def test_defaults(self):
        kw = KeywordConfig(phrases=[["test"]])
        assert kw.exclusions == []
        assert kw.proximity_window == 15
        assert kw.require_order is False
        assert kw.use_stemming is False
        assert kw.exclusion_scope == "anywhere"


class TestRealisticScenarios:
    """Test with realistic Reddit-like content and keyword configs."""

    def test_sports_betting_lead(self):
        content = _make_content(
            "I've been looking into arbitrage betting for a while now. "
            "Does anyone know a good tool that works with DraftKings and "
            "FanDuel? Budget is around $50/month."
        )
        keyword = KeywordConfig(
            phrases=[["arbitrage", "betting"], ["arb", "tool"]],
            exclusions=["scam", "illegal"],
            proximity_window=15,
        )
        results = find_matches(content, keyword)
        assert len(results) >= 1
        assert any(r.matched_phrase == "arbitrage betting" for r in results)

    def test_crypto_monitoring(self):
        content = _make_content(
            "Just discovered this new DeFi protocol that offers yield farming "
            "with really high APY. Not sure if it's legit or a rug pull though."
        )
        keyword = KeywordConfig(
            phrases=[["yield", "farming"], ["defi", "protocol"]],
            exclusions=["rug pull"],
            exclusion_scope="anywhere",
        )
        # "rug" is in the text, "pull" is in the text => "rug" exclusion match
        # But exclusions are single words, so "rug pull" needs to be split
        # Let's use single-word exclusions
        keyword_with_single_exclusions = KeywordConfig(
            phrases=[["yield", "farming"], ["defi", "protocol"]],
            exclusions=["rug"],
            exclusion_scope="anywhere",
        )
        results = find_matches(content, keyword_with_single_exclusions)
        assert len(results) == 0  # blocked by "rug" exclusion

    def test_no_false_positive_on_partial(self):
        content = _make_content(
            "I was playing basketball and later went to the store"
        )
        keyword = KeywordConfig(phrases=[["arbitrage", "betting"]])
        results = find_matches(content, keyword)
        assert len(results) == 0
