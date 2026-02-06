from __future__ import annotations

"""Shared test configuration.

Registers a SQLite-compatible ARRAY type so tests can use SQLite
in-memory databases with models that use PostgreSQL ARRAY columns.
"""

import json

from sqlalchemy import String, TypeDecorator, event
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles


class _StringifiedARRAY(TypeDecorator):
    """Store PostgreSQL ARRAY columns as JSON strings in SQLite."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)
        return value


# Make ARRAY compile as TEXT on SQLite
@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(type_, compiler, **kw):
    return "TEXT"


# Patch ARRAY to use JSON serialization on SQLite.
# We override bind_processor and result_processor at the class level.
_orig_bind_processor = ARRAY.bind_processor
_orig_result_processor = ARRAY.result_processor


def _patched_bind_processor(self, dialect):
    if dialect.name == "sqlite":
        def process(value):
            if value is not None:
                return json.dumps(value)
            return value
        return process
    return _orig_bind_processor(self, dialect)


def _patched_result_processor(self, dialect, coltype):
    if dialect.name == "sqlite":
        def process(value):
            if value is not None:
                return json.loads(value)
            return value
        return process
    return _orig_result_processor(self, dialect, coltype)


ARRAY.bind_processor = _patched_bind_processor
ARRAY.result_processor = _patched_result_processor
