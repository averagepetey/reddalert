from __future__ import annotations

"""Pipeline orchestrator for Reddalert background worker.

Executes the full poll -> match -> alert cycle in a single call.
"""

import logging

from sqlalchemy.orm import Session

from app.services.alert_dispatcher import AlertDispatcher
from app.services.match_engine import MatchEngine
from app.services.poller import RedditPoller

logger = logging.getLogger(__name__)


def run_pipeline(db_session: Session) -> dict:
    """Execute the full ingestion/matching/alerting pipeline.

    Steps:
        1. Poll all active subreddits for new content.
        2. Run new content through the match engine.
        3. Dispatch Discord alerts for any new matches.

    Args:
        db_session: An active SQLAlchemy session.

    Returns:
        A summary dict with keys: subreddits_polled, new_content, matches_found,
        alerts_sent, alerts_failed.
    """
    summary = {
        "subreddits_polled": 0,
        "new_content": 0,
        "matches_found": 0,
        "alerts_sent": 0,
        "alerts_failed": 0,
    }

    # 1. Poll
    poller = RedditPoller(db_session)
    poll_results = poller.poll_all_active()
    summary["subreddits_polled"] = len(poll_results)

    all_new_content = []
    for sub_name, content_list in poll_results.items():
        all_new_content.extend(content_list)
    summary["new_content"] = len(all_new_content)

    logger.info(
        "Poll complete: %d subreddits, %d new content items",
        summary["subreddits_polled"],
        summary["new_content"],
    )

    # 2. Match
    if all_new_content:
        engine = MatchEngine(db_session)
        matches = engine.process_batch(all_new_content)
        summary["matches_found"] = len(matches)
        logger.info("Matching complete: %d matches found", summary["matches_found"])

    # 3. Alert
    dispatcher = AlertDispatcher(db_session)
    alert_result = dispatcher.dispatch_pending()
    summary["alerts_sent"] = alert_result["sent"]
    summary["alerts_failed"] = alert_result["failed"]

    logger.info(
        "Alerting complete: %d sent, %d failed",
        summary["alerts_sent"],
        summary["alerts_failed"],
    )

    logger.info("Pipeline run finished: %s", summary)
    return summary
