"""Text normalizer for Reddalert content processing.

Cleans, tokenizes, and segments raw text from Reddit posts/comments
into a normalized form suitable for keyword matching.
"""

import re
from dataclasses import dataclass, field


@dataclass
class NormalizedResult:
    """Result of normalizing a piece of text."""
    normalized_text: str
    tokens: list[str] = field(default_factory=list)
    sentences: list[str] = field(default_factory=list)


# Regex patterns compiled once at module level
_URL_PATTERN = re.compile(r'https?://\S+')
_REDDIT_LINK_PATTERN = re.compile(r'\[([^\]]*)\]\([^)]*\)')
_BOLD_PATTERN = re.compile(r'\*\*(.+?)\*\*')
_ITALIC_PATTERN = re.compile(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)')
_STRIKETHROUGH_PATTERN = re.compile(r'~~(.+?)~~')
_INLINE_CODE_PATTERN = re.compile(r'`([^`]+)`')
_BLOCKQUOTE_PATTERN = re.compile(r'^>\s?', re.MULTILINE)
_HEADING_PATTERN = re.compile(r'^#{1,6}\s+', re.MULTILINE)
_HORIZONTAL_RULE_PATTERN = re.compile(r'^[-*_]{3,}\s*$', re.MULTILINE)
_SUPERSCRIPT_PATTERN = re.compile(r'\^(\S+)')
_WHITESPACE_PATTERN = re.compile(r'\s+')
_SENTENCE_SPLIT_PATTERN = re.compile(r'(?<=[.!?])\s+')
_TOKEN_PATTERN = re.compile(r"[a-z0-9'-]+")


def normalize_text(raw_text: str) -> NormalizedResult:
    """Normalize raw Reddit text into a clean, matchable form.

    Processing steps:
    1. Lowercase
    2. Strip URLs
    3. Strip Reddit markdown formatting
    4. Normalize whitespace
    5. Tokenize into words
    6. Segment into sentences

    Args:
        raw_text: Raw text from a Reddit post or comment.

    Returns:
        NormalizedResult with cleaned text, tokens, and sentences.
    """
    if not raw_text or not raw_text.strip():
        return NormalizedResult(normalized_text="", tokens=[], sentences=[])

    text = raw_text.lower()
    text = _strip_markdown(text)
    text = _strip_urls(text)
    text = _normalize_whitespace(text)

    tokens = _tokenize(text)
    sentences = _segment_sentences(text)

    return NormalizedResult(
        normalized_text=text,
        tokens=tokens,
        sentences=sentences,
    )


def _strip_urls(text: str) -> str:
    """Remove http/https URLs from text."""
    return _URL_PATTERN.sub('', text)


def _strip_markdown(text: str) -> str:
    """Remove Reddit markdown formatting, keeping the inner text."""
    # Links: [text](url) -> text
    text = _REDDIT_LINK_PATTERN.sub(r'\1', text)
    # Bold: **text** -> text
    text = _BOLD_PATTERN.sub(r'\1', text)
    # Italic: *text* -> text
    text = _ITALIC_PATTERN.sub(r'\1', text)
    # Strikethrough: ~~text~~ -> text
    text = _STRIKETHROUGH_PATTERN.sub(r'\1', text)
    # Inline code: `text` -> text
    text = _INLINE_CODE_PATTERN.sub(r'\1', text)
    # Blockquotes: > text -> text
    text = _BLOCKQUOTE_PATTERN.sub('', text)
    # Headings: ## text -> text
    text = _HEADING_PATTERN.sub('', text)
    # Horizontal rules
    text = _HORIZONTAL_RULE_PATTERN.sub('', text)
    # Superscript: ^word -> word
    text = _SUPERSCRIPT_PATTERN.sub(r'\1', text)
    return text


def _normalize_whitespace(text: str) -> str:
    """Collapse multiple whitespace characters into single spaces and strip."""
    return _WHITESPACE_PATTERN.sub(' ', text).strip()


def _tokenize(text: str) -> list[str]:
    """Split text into word tokens, stripping punctuation."""
    return _TOKEN_PATTERN.findall(text)


def _segment_sentences(text: str) -> list[str]:
    """Split text into sentences based on sentence-ending punctuation."""
    if not text:
        return []
    sentences = _SENTENCE_SPLIT_PATTERN.split(text)
    return [s.strip() for s in sentences if s.strip()]
