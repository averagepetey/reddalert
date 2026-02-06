"""Tests for the deduplication module."""

import hashlib
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.models.content import ContentType, RedditContent
from app.services.deduplicator import compute_content_hash, is_duplicate, mark_deleted


# ---------------------------------------------------------------------------
# compute_content_hash
# ---------------------------------------------------------------------------


class TestComputeContentHash:
    def test_returns_sha256_hex(self):
        text = "hello world"
        result = compute_content_hash(text)
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert result == expected

    def test_deterministic(self):
        text = "same input always same output"
        assert compute_content_hash(text) == compute_content_hash(text)

    def test_different_texts_produce_different_hashes(self):
        assert compute_content_hash("alpha") != compute_content_hash("beta")

    def test_empty_string(self):
        result = compute_content_hash("")
        expected = hashlib.sha256(b"").hexdigest()
        assert result == expected

    def test_unicode_text(self):
        text = "arbitrage betting discussion"
        result = compute_content_hash(text)
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex length


# ---------------------------------------------------------------------------
# is_duplicate
# ---------------------------------------------------------------------------


class TestIsDuplicate:
    def _make_session(self, query_returns_row: bool) -> MagicMock:
        """Create a mock SQLAlchemy session that fakes a query result."""
        session = MagicMock()
        query = session.query.return_value
        filtered = query.filter.return_value
        if query_returns_row:
            filtered.first.return_value = (uuid.uuid4(),)
        else:
            filtered.first.return_value = None
        return session

    def test_returns_true_when_hash_exists(self):
        session = self._make_session(query_returns_row=True)
        assert is_duplicate(session, "abc123") is True

    def test_returns_false_when_hash_missing(self):
        session = self._make_session(query_returns_row=False)
        assert is_duplicate(session, "abc123") is False


# ---------------------------------------------------------------------------
# mark_deleted
# ---------------------------------------------------------------------------


class TestMarkDeleted:
    def test_marks_existing_record_as_deleted(self):
        session = MagicMock()
        fake_record = MagicMock(is_deleted=False)
        session.query.return_value.filter.return_value.first.return_value = fake_record

        result = mark_deleted(session, "t3_abc")

        assert result is True
        assert fake_record.is_deleted is True
        session.commit.assert_called_once()

    def test_returns_false_when_not_found(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        result = mark_deleted(session, "t3_missing")

        assert result is False
        session.commit.assert_not_called()
