from __future__ import annotations

"""Reddalert background worker entry point.

Runs as a standalone process (``python -m app.worker.main``) using APScheduler
to periodically execute the polling/matching/alerting pipeline and a daily
data-retention cleanup.
"""

import logging
import os
import signal
import sys
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler

from app.database import SessionLocal
from app.worker.pipeline import run_pipeline
from app.worker.retention import cleanup_old_data

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

POLL_INTERVAL_MINUTES: int = int(os.getenv("POLL_INTERVAL_MINUTES", "60"))
RETENTION_DAYS: int = int(os.getenv("RETENTION_DAYS", "90"))


# ---------------------------------------------------------------------------
# Scheduled job wrappers (each opens and closes its own DB session)
# ---------------------------------------------------------------------------


def pipeline_job() -> None:
    """Run the full poll/match/alert pipeline."""
    session = SessionLocal()
    try:
        summary = run_pipeline(session)
        logger.info("Pipeline job finished: %s", summary)
    except Exception:
        logger.exception("Pipeline job failed")
    finally:
        session.close()


def retention_job() -> None:
    """Run the daily data-retention cleanup."""
    session = SessionLocal()
    try:
        result = cleanup_old_data(session, retention_days=RETENTION_DAYS)
        logger.info("Retention job finished: %s", result)
    except Exception:
        logger.exception("Retention job failed")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Scheduler factory (testable)
# ---------------------------------------------------------------------------


def create_scheduler() -> BlockingScheduler:
    """Build and configure the APScheduler BlockingScheduler."""
    scheduler = BlockingScheduler()

    scheduler.add_job(
        pipeline_job,
        "interval",
        minutes=POLL_INTERVAL_MINUTES,
        id="pipeline",
        name="Poll/Match/Alert pipeline",
    )

    scheduler.add_job(
        retention_job,
        "cron",
        hour=3,
        minute=0,
        id="retention",
        name="Data retention cleanup",
    )

    return scheduler


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the background worker."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info(
        "Starting Reddalert worker — poll every %d min, retain %d days",
        POLL_INTERVAL_MINUTES,
        RETENTION_DAYS,
    )

    scheduler = create_scheduler()

    # Run the pipeline once immediately on startup
    logger.info("Running initial pipeline on startup...")
    pipeline_job()

    def _shutdown(signum: int, frame: Optional[object]) -> None:
        logger.info("Received signal %s — shutting down scheduler", signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    scheduler.start()


if __name__ == "__main__":
    main()
