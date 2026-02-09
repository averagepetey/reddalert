from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.clients import Client
from ..services.alert_dispatcher import AlertDispatcher
from ..services.match_engine import MatchEngine
from ..services.poller import RedditPoller
from .auth import get_current_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["poll"])


@router.post("/poll-now", status_code=status.HTTP_200_OK)
def poll_now(
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Trigger one poll → match → alert cycle for the current client's subreddits."""
    poller = RedditPoller(db)
    engine = MatchEngine(db)
    dispatcher = AlertDispatcher(db)

    # Poll only this client's active subreddits
    from ..models.subreddits import MonitoredSubreddit

    subs = (
        db.query(MonitoredSubreddit)
        .filter(
            MonitoredSubreddit.client_id == client.id,
            MonitoredSubreddit.status == "active",
        )
        .all()
    )

    total_content = 0
    total_matches = 0

    for sub in subs:
        try:
            new_content = poller.poll_subreddit(sub.name)
            total_content += len(new_content)
            matches = engine.process_batch(new_content)
            total_matches += len(matches)
        except Exception:
            logger.exception("Failed to poll r/%s", sub.name)
            db.rollback()

    # Dispatch any pending alerts (including ones just created)
    dispatch_result = dispatcher.dispatch_pending()

    return {
        "subreddits_polled": len(subs),
        "new_content": total_content,
        "matches_found": total_matches,
        "alerts_sent": dispatch_result.get("sent", 0),
        "alerts_failed": dispatch_result.get("failed", 0),
    }
