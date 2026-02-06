import json
import os
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/reddalert",
)

_is_sqlite = DATABASE_URL.startswith("sqlite")

_engine_kwargs: dict = {}
if _is_sqlite:
    _engine_kwargs.update(
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # --- SQLite ARRAY adapter (same as tests/conftest.py) ---
    @compiles(ARRAY, "sqlite")
    def _compile_array_sqlite(type_, compiler, **kw):
        return "TEXT"

    _orig_bind = ARRAY.bind_processor
    _orig_result = ARRAY.result_processor

    def _patched_bind(self, dialect):
        if dialect.name == "sqlite":
            return lambda v: json.dumps(v) if v is not None else v
        return _orig_bind(self, dialect)

    def _patched_result(self, dialect, coltype):
        if dialect.name == "sqlite":
            return lambda v: json.loads(v) if v is not None else v
        return _orig_result(self, dialect, coltype)

    ARRAY.bind_processor = _patched_bind
    ARRAY.result_processor = _patched_result
else:
    _engine_kwargs["pool_pre_ping"] = True

engine = create_engine(DATABASE_URL, **_engine_kwargs)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
