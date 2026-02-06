"""Tests for the text normalizer module."""

import pytest

from app.services.normalizer import normalize_text, NormalizedResult


class TestBasicCleaning:
    """Test basic text cleaning and lowercasing."""

    def test_lowercase(self):
        result = normalize_text("Hello WORLD FooBar")
        assert result.normalized_text == "hello world foobar"

    def test_simple_text(self):
        result = normalize_text("this is a test")
        assert result.normalized_text == "this is a test"
        assert result.tokens == ["this", "is", "a", "test"]

    def test_preserves_numbers(self):
        result = normalize_text("I have 42 cats and 3 dogs")
        assert "42" in result.tokens
        assert "3" in result.tokens

    def test_preserves_hyphenated_words(self):
        result = normalize_text("well-known open-source project")
        assert "well-known" in result.tokens
        assert "open-source" in result.tokens

    def test_preserves_apostrophes(self):
        result = normalize_text("I can't believe it's working")
        assert "can't" in result.tokens
        assert "it's" in result.tokens


class TestURLStripping:
    """Test URL removal from text."""

    def test_http_url(self):
        result = normalize_text("check out http://example.com for more")
        assert "http" not in result.normalized_text
        assert "example.com" not in result.normalized_text
        assert "check out" in result.normalized_text
        assert "for more" in result.normalized_text

    def test_https_url(self):
        result = normalize_text("visit https://www.reddit.com/r/test please")
        assert "https" not in result.normalized_text
        assert "reddit.com" not in result.normalized_text

    def test_multiple_urls(self):
        result = normalize_text("see http://a.com and https://b.com here")
        assert "a.com" not in result.normalized_text
        assert "b.com" not in result.normalized_text
        assert "see" in result.normalized_text
        assert "here" in result.normalized_text

    def test_url_with_query_params(self):
        result = normalize_text("link: https://example.com/path?q=test&page=1 ok")
        assert "example.com" not in result.normalized_text
        assert "ok" in result.normalized_text


class TestMarkdownRemoval:
    """Test Reddit markdown formatting removal."""

    def test_bold(self):
        result = normalize_text("this is **bold text** here")
        assert result.normalized_text == "this is bold text here"

    def test_italic(self):
        result = normalize_text("this is *italic text* here")
        assert result.normalized_text == "this is italic text here"

    def test_strikethrough(self):
        result = normalize_text("this is ~~deleted~~ here")
        assert result.normalized_text == "this is deleted here"

    def test_inline_code(self):
        result = normalize_text("use `some_function()` here")
        assert "some_function()" in result.normalized_text
        assert "`" not in result.normalized_text

    def test_link_markdown(self):
        result = normalize_text("check [this link](https://example.com) out")
        assert result.normalized_text == "check this link out"

    def test_blockquote(self):
        result = normalize_text("> this is a quote\nnot a quote")
        assert "this is a quote" in result.normalized_text
        assert result.normalized_text.startswith("this")

    def test_heading(self):
        result = normalize_text("## Section Title\nSome content")
        assert "section title" in result.normalized_text
        assert "#" not in result.normalized_text

    def test_superscript(self):
        result = normalize_text("word^superscript more")
        assert "superscript" in result.normalized_text
        assert "^" not in result.normalized_text

    def test_combined_markdown(self):
        result = normalize_text("**bold** and *italic* with [link](http://x.com)")
        assert "bold" in result.tokens
        assert "italic" in result.tokens
        assert "link" in result.tokens
        assert "**" not in result.normalized_text
        assert "*" not in result.normalized_text


class TestWhitespaceNormalization:
    """Test whitespace handling."""

    def test_multiple_spaces(self):
        result = normalize_text("too   many    spaces")
        assert result.normalized_text == "too many spaces"

    def test_tabs_and_newlines(self):
        result = normalize_text("tabs\there\nand\nnewlines")
        assert result.normalized_text == "tabs here and newlines"

    def test_leading_trailing_whitespace(self):
        result = normalize_text("  leading and trailing  ")
        assert result.normalized_text == "leading and trailing"

    def test_mixed_whitespace(self):
        result = normalize_text("\t  hello  \n  world  \t")
        assert result.normalized_text == "hello world"


class TestEmptyInput:
    """Test handling of empty and null-like inputs."""

    def test_empty_string(self):
        result = normalize_text("")
        assert result.normalized_text == ""
        assert result.tokens == []
        assert result.sentences == []

    def test_whitespace_only(self):
        result = normalize_text("   \t\n  ")
        assert result.normalized_text == ""
        assert result.tokens == []
        assert result.sentences == []

    def test_none_input(self):
        result = normalize_text(None)
        assert result.normalized_text == ""
        assert result.tokens == []
        assert result.sentences == []


class TestTokenization:
    """Test word tokenization."""

    def test_basic_tokenization(self):
        result = normalize_text("hello world foo bar")
        assert result.tokens == ["hello", "world", "foo", "bar"]

    def test_punctuation_stripped(self):
        result = normalize_text("hello, world! how are you?")
        assert result.tokens == ["hello", "world", "how", "are", "you"]

    def test_mixed_content(self):
        result = normalize_text("I use Python3.9 and Node.js")
        # Tokens should split on dots
        assert "python3" in result.tokens or "python" in result.tokens
        assert "node" in result.tokens


class TestSentenceSegmentation:
    """Test sentence splitting."""

    def test_basic_sentences(self):
        result = normalize_text("First sentence. Second sentence. Third one.")
        assert len(result.sentences) == 3

    def test_question_and_exclamation(self):
        result = normalize_text("Is this a question? Yes it is! Great.")
        assert len(result.sentences) == 3

    def test_single_sentence(self):
        result = normalize_text("just one sentence")
        assert len(result.sentences) == 1
        assert result.sentences[0] == "just one sentence"

    def test_no_punctuation(self):
        result = normalize_text("no ending punctuation here")
        assert len(result.sentences) == 1


class TestNormalizedResultDataclass:
    """Test the NormalizedResult dataclass."""

    def test_fields_present(self):
        result = normalize_text("test input")
        assert hasattr(result, 'normalized_text')
        assert hasattr(result, 'tokens')
        assert hasattr(result, 'sentences')

    def test_is_dataclass_instance(self):
        result = normalize_text("test")
        assert isinstance(result, NormalizedResult)

    def test_default_factory(self):
        result = NormalizedResult(normalized_text="test")
        assert result.tokens == []
        assert result.sentences == []


class TestRealisticRedditContent:
    """Test with realistic Reddit post content."""

    def test_reddit_post(self):
        text = (
            "## Looking for arbitrage betting software\n\n"
            "I've been doing **sports betting** for a while and want to "
            "try arbitrage. Has anyone used [OddsJam](https://oddsjam.com) "
            "or similar tools? Looking for something that can scan multiple "
            "sportsbooks in real-time.\n\n"
            "> I heard BetBurger is good too\n\n"
            "Any recommendations? Budget is ~$50/month."
        )
        result = normalize_text(text)

        assert "arbitrage" in result.tokens
        assert "betting" in result.tokens
        assert "oddsjam" not in result.normalized_text or "oddsjam" in result.tokens
        assert "https" not in result.normalized_text
        assert "**" not in result.normalized_text
        assert "#" not in result.normalized_text
        assert len(result.sentences) >= 3

    def test_reddit_comment(self):
        text = (
            "I totally agree with this. *Arbitrage betting* is the way to go "
            "if you want consistent profits. Check out r/sportsbetting for "
            "more info. https://reddit.com/r/sportsbetting"
        )
        result = normalize_text(text)

        assert "arbitrage" in result.tokens
        assert "betting" in result.tokens
        assert "reddit.com" not in result.normalized_text
        assert "*" not in result.normalized_text
