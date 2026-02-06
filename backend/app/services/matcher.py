"""Proximity matcher for Reddalert keyword detection.

Checks normalized content against keyword configurations, verifying that
phrase tokens appear within a configurable proximity window. Supports OR
groups, negations, ordering constraints, and optional stemming.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from .normalizer import NormalizedResult


@dataclass
class KeywordConfig:
    """Configuration for a keyword matching rule."""
    phrases: list[list[str]]  # OR groups: each phrase is a list of tokens
    exclusions: list[str] = field(default_factory=list)
    proximity_window: int = 15
    require_order: bool = False
    use_stemming: bool = False
    exclusion_scope: str = "anywhere"  # "anywhere" or "proximity"


@dataclass
class MatchResult:
    """A single match found in content."""
    matched_phrase: str
    span_start: int  # char index in normalized_text
    span_end: int
    snippet: str
    proximity_score: float
    also_matched: list[str] = field(default_factory=list)


# Simple suffix-stripping stemmer to avoid external dependencies.
# Handles the most common English suffixes.
_STEM_SUFFIXES = [
    "ational", "tional", "enci", "anci", "izer", "ation", "ness",
    "ment", "ful", "less", "ive", "ous", "ing", "ble", "ally",
    "ity", "ies", "ied", "ers", "est", "ely", "ess",
    "ly", "er", "ed", "al", "es", "en", "ty", "ss",
    "s",
]


def _simple_stem(word: str) -> str:
    """Apply simple suffix-stripping stemming.

    This is intentionally basic -- just enough to match common
    morphological variants (e.g. "betting" -> "bet", "runs" -> "run").
    """
    if len(word) <= 3:
        return word

    # Handle doubling: "betting" -> "bett" after removing "ing" -> "bet"
    for suffix in _STEM_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            stem = word[:-len(suffix)]
            # Remove doubled final consonant
            if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in 'aeiou':
                stem = stem[:-1]
            return stem
    return word


_TOKEN_PATTERN = re.compile(r"[a-z0-9'-]+")


def _build_token_index(tokens: list[str], text: str) -> list[int]:
    """Build a mapping from token index to character offset in text.

    Returns a list where index i is the character start position of tokens[i].
    """
    positions: list[int] = []
    search_start = 0
    for token in tokens:
        idx = text.find(token, search_start)
        if idx == -1:
            # Fallback: use the pattern matcher
            m = re.search(re.escape(token), text[search_start:])
            if m:
                idx = search_start + m.start()
            else:
                idx = search_start
        positions.append(idx)
        search_start = idx + len(token)
    return positions


def _generate_snippet(text: str, span_start: int, span_end: int, length: int = 200) -> str:
    """Generate a snippet of `length` chars centered on the match span."""
    if len(text) <= length:
        return text

    match_center = (span_start + span_end) // 2
    half = length // 2
    start = max(0, match_center - half)
    end = start + length

    if end > len(text):
        end = len(text)
        start = max(0, end - length)

    snippet = text[start:end]

    # Add ellipsis indicators
    if start > 0:
        snippet = "..." + snippet[3:]
    if end < len(text):
        snippet = snippet[:-3] + "..."

    return snippet


def _calculate_proximity_score(token_positions: list[int], total_tokens: int) -> float:
    """Calculate proximity score based on how close matched tokens are.

    Returns 1.0 for adjacent tokens, decreasing as distance increases.
    For single-token phrases, always returns 1.0.
    """
    if len(token_positions) <= 1:
        return 1.0

    sorted_positions = sorted(token_positions)
    span = sorted_positions[-1] - sorted_positions[0]
    # Minimum possible span is len(token_positions) - 1 (adjacent tokens)
    min_span = len(token_positions) - 1
    if span <= min_span:
        return 1.0

    # Score decreases as span grows relative to the window
    # Using a simple inverse relationship
    return max(0.1, min_span / span)


def find_matches(
    content: NormalizedResult,
    keyword: KeywordConfig,
) -> list[MatchResult]:
    """Find all keyword matches in normalized content.

    For each phrase in the keyword's OR groups:
    1. Find all token occurrences in the content
    2. Check proximity window constraints
    3. Check ordering constraints if required
    4. Apply exclusion filters
    5. Generate snippet and score

    Args:
        content: Normalized text result from the normalizer.
        keyword: Keyword configuration with phrases, exclusions, etc.

    Returns:
        List of MatchResult for each match found.
    """
    if not content.normalized_text or not content.tokens:
        return []

    tokens = content.tokens
    text = content.normalized_text
    token_offsets = _build_token_index(tokens, text)

    # Optionally stem content tokens
    if keyword.use_stemming:
        stemmed_tokens = [_simple_stem(t) for t in tokens]
    else:
        stemmed_tokens = tokens

    # Check "anywhere" exclusions up front
    if keyword.exclusions and keyword.exclusion_scope == "anywhere":
        if keyword.use_stemming:
            exclusion_stems = {_simple_stem(e.lower()) for e in keyword.exclusions}
            if any(st in exclusion_stems for st in stemmed_tokens):
                return []
        else:
            exclusion_set = {e.lower() for e in keyword.exclusions}
            if any(t in exclusion_set for t in tokens):
                return []

    results: list[MatchResult] = []

    for phrase_tokens in keyword.phrases:
        if not phrase_tokens:
            continue

        phrase_lower = [t.lower() for t in phrase_tokens]
        if keyword.use_stemming:
            phrase_stemmed = [_simple_stem(t) for t in phrase_lower]
        else:
            phrase_stemmed = phrase_lower

        phrase_matches = _find_phrase_matches(
            stemmed_tokens=stemmed_tokens,
            token_offsets=token_offsets,
            tokens=tokens,
            phrase_stemmed=phrase_stemmed,
            proximity_window=keyword.proximity_window,
            require_order=keyword.require_order,
        )

        for matched_token_indices in phrase_matches:
            # Check proximity-scoped exclusions
            if keyword.exclusions and keyword.exclusion_scope == "proximity":
                if _has_proximity_exclusion(
                    stemmed_tokens=stemmed_tokens,
                    tokens=tokens,
                    matched_indices=matched_token_indices,
                    exclusions=keyword.exclusions,
                    window=keyword.proximity_window,
                    use_stemming=keyword.use_stemming,
                ):
                    continue

            # Calculate span in the original text
            span_start = token_offsets[matched_token_indices[0]]
            last_idx = matched_token_indices[-1]
            span_end = token_offsets[last_idx] + len(tokens[last_idx])

            snippet = _generate_snippet(text, span_start, span_end)
            score = _calculate_proximity_score(matched_token_indices, len(tokens))

            phrase_str = " ".join(phrase_tokens)
            results.append(MatchResult(
                matched_phrase=phrase_str,
                span_start=span_start,
                span_end=span_end,
                snippet=snippet,
                proximity_score=score,
            ))

    return results


def _find_phrase_matches(
    stemmed_tokens: list[str],
    token_offsets: list[int],
    tokens: list[str],
    phrase_stemmed: list[str],
    proximity_window: int,
    require_order: bool,
) -> list[list[int]]:
    """Find all occurrences of a phrase within the token list.

    For single-token phrases, returns each position where the token appears.
    For multi-token phrases, finds combinations within the proximity window.

    Returns a list of lists, where each inner list contains the token indices
    that form a match.
    """
    if len(phrase_stemmed) == 1:
        # Single-token phrase: find all occurrences
        target = phrase_stemmed[0]
        return [[i] for i, t in enumerate(stemmed_tokens) if t == target]

    # Multi-token phrase: find positions of each phrase token
    token_positions: list[list[int]] = []
    for pt in phrase_stemmed:
        positions = [i for i, t in enumerate(stemmed_tokens) if t == pt]
        if not positions:
            return []  # A required token is missing entirely
        token_positions.append(positions)

    # Find valid combinations within proximity window
    # Use the first token's positions as anchors and search for combinations
    matches: list[list[int]] = []
    for anchor_pos in token_positions[0]:
        combo = _find_combination(
            token_positions=token_positions,
            anchor_pos=anchor_pos,
            proximity_window=proximity_window,
            require_order=require_order,
            current_combo=[anchor_pos],
            token_idx=1,
        )
        if combo is not None:
            matches.append(combo)

    return matches


def _find_combination(
    token_positions: list[list[int]],
    anchor_pos: int,
    proximity_window: int,
    require_order: bool,
    current_combo: list[int],
    token_idx: int,
) -> Optional[list[int]]:
    """Recursively find a valid token combination within the proximity window."""
    if token_idx >= len(token_positions):
        return current_combo

    for pos in token_positions[token_idx]:
        # Check proximity: all tokens must be within proximity_window of each other
        all_positions = current_combo + [pos]
        span = max(all_positions) - min(all_positions)
        if span >= proximity_window:
            continue

        # Check ordering if required
        if require_order and pos <= current_combo[-1]:
            continue

        # Avoid using the same position twice
        if pos in current_combo:
            continue

        result = _find_combination(
            token_positions=token_positions,
            anchor_pos=anchor_pos,
            proximity_window=proximity_window,
            require_order=require_order,
            current_combo=all_positions,
            token_idx=token_idx + 1,
        )
        if result is not None:
            return result

    return None


def _has_proximity_exclusion(
    stemmed_tokens: list[str],
    tokens: list[str],
    matched_indices: list[int],
    exclusions: list[str],
    window: int,
    use_stemming: bool,
) -> bool:
    """Check if any exclusion word appears within the proximity window of the match."""
    if use_stemming:
        exclusion_set = {_simple_stem(e.lower()) for e in exclusions}
        check_tokens = stemmed_tokens
    else:
        exclusion_set = {e.lower() for e in exclusions}
        check_tokens = tokens

    match_min = min(matched_indices)
    match_max = max(matched_indices)
    window_start = max(0, match_min - window)
    window_end = min(len(check_tokens), match_max + window + 1)

    for i in range(window_start, window_end):
        if check_tokens[i] in exclusion_set:
            return True
    return False
