from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import (
    auth_router,
    clients_router,
    keywords_router,
    matches_router,
    stats_router,
    subreddits_router,
    webhooks_router,
)
from .database import DATABASE_URL, engine
from .models.base import Base

# Import all models so Base.metadata knows about them
from .models import clients, content, keywords, matches, subreddits, webhooks  # noqa: F401

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Reddalert",
    version="0.1.0",
    # Disable docs in production to reduce attack surface
    docs_url="/docs" if os.getenv("DEBUG", "false").lower() == "true" else None,
    redoc_url=None,
)

# ---------------------------------------------------------------------------
# CORS — restrict to frontend origin only
# ---------------------------------------------------------------------------

_ALLOWED_ORIGINS = os.getenv(
    "CORS_ORIGINS", "http://localhost:3000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth_router)
app.include_router(clients_router)
app.include_router(keywords_router)
app.include_router(subreddits_router)
app.include_router(webhooks_router)
app.include_router(matches_router)
app.include_router(stats_router)


# ---------------------------------------------------------------------------
# Global error handler — prevent stack trace leakage
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unhandled exceptions and return a generic error message.

    Never expose stack traces, internal paths, or sensitive details.
    """
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.on_event("startup")
def on_startup():
    if DATABASE_URL.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
        logger.info("SQLite mode: tables created automatically")


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}
