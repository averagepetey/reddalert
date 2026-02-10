from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

load_dotenv()

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import (
    auth_router,
    clients_router,
    discord_router,
    keywords_router,
    matches_router,
    poll_router,
    stats_router,
    subreddits_router,
    webhooks_router,
)
from .database import DATABASE_URL, SessionLocal, engine
from .models.base import Base

# Import all models so Base.metadata knows about them
from .models import clients, content, keywords, matches, subreddits, webhooks  # noqa: F401

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()

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
app.include_router(discord_router)
app.include_router(keywords_router)
app.include_router(subreddits_router)
app.include_router(webhooks_router)
app.include_router(matches_router)
app.include_router(poll_router)
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


def _run_poll_cycle():
    """Background job: poll all active subreddits, match keywords, send alerts."""
    from .models.subreddits import MonitoredSubreddit
    from .services.alert_dispatcher import AlertDispatcher
    from .services.match_engine import MatchEngine
    from .services.poller import RedditPoller

    db = SessionLocal()
    try:
        poller = RedditPoller(db)
        engine_svc = MatchEngine(db)
        dispatcher = AlertDispatcher(db)

        active_names = (
            db.query(MonitoredSubreddit.name)
            .filter(MonitoredSubreddit.status == "active")
            .distinct()
            .all()
        )

        for (name,) in active_names:
            try:
                new_content = poller.poll_subreddit(name)
                if new_content:
                    engine_svc.process_batch(new_content)
            except Exception:
                logger.exception("Poll cycle: failed to poll r/%s", name)
                db.rollback()

        dispatcher.dispatch_pending()
        logger.info("Poll cycle complete: checked %d subreddit(s)", len(active_names))
    except Exception:
        logger.exception("Poll cycle failed")
    finally:
        db.close()


@app.on_event("startup")
async def on_startup():
    if DATABASE_URL.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
        logger.info("SQLite mode: tables created automatically")

    poll_minutes = int(os.getenv("POLL_INTERVAL_MINUTES", "5"))
    scheduler.add_job(_run_poll_cycle, "interval", minutes=poll_minutes, id="poll_cycle")
    scheduler.start()
    logger.info("Scheduler started: polling every %d minute(s)", poll_minutes)

    # Start Discord bot if token is configured
    import asyncio

    discord_bot_token = os.getenv("DISCORD_BOT_TOKEN", "")
    if discord_bot_token:
        from .bot.client import bot

        asyncio.create_task(bot.start(discord_bot_token))
        logger.info("Discord bot starting...")
    else:
        logger.warning("DISCORD_BOT_TOKEN not set — Discord bot will not start")


@app.on_event("shutdown")
async def on_shutdown():
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")

    discord_bot_token = os.getenv("DISCORD_BOT_TOKEN", "")
    if discord_bot_token:
        from .bot.client import bot

        if not bot.is_closed():
            await bot.close()
            logger.info("Discord bot stopped")


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}
