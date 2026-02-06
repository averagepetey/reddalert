from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.clients import Client
from ..models.keywords import Keyword
from ..models.matches import Match
from .auth import get_current_client
from .schemas import KeywordStat, StatsResponse, SubredditStat

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("", response_model=StatsResponse)
def get_stats(
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Return basic analytics for the authenticated client."""
    now = datetime.now(timezone.utc)

    total_matches = (
        db.query(func.count(Match.id))
        .filter(Match.client_id == client.id)
        .scalar()
    ) or 0

    matches_24h = (
        db.query(func.count(Match.id))
        .filter(
            Match.client_id == client.id,
            Match.detected_at >= now - timedelta(hours=24),
        )
        .scalar()
    ) or 0

    matches_7d = (
        db.query(func.count(Match.id))
        .filter(
            Match.client_id == client.id,
            Match.detected_at >= now - timedelta(days=7),
        )
        .scalar()
    ) or 0

    # Top keywords by match count
    top_kw_rows = (
        db.query(Match.keyword_id, func.count(Match.id).label("cnt"))
        .filter(Match.client_id == client.id)
        .group_by(Match.keyword_id)
        .order_by(func.count(Match.id).desc())
        .limit(10)
        .all()
    )
    top_keywords = []
    for kw_id, cnt in top_kw_rows:
        kw = db.query(Keyword).filter(Keyword.id == kw_id).first()
        if kw:
            top_keywords.append(
                KeywordStat(
                    keyword_id=kw.id,
                    phrases=kw.phrases,
                    match_count=cnt,
                )
            )

    # Top subreddits by match count
    top_sub_rows = (
        db.query(Match.subreddit, func.count(Match.id).label("cnt"))
        .filter(Match.client_id == client.id)
        .group_by(Match.subreddit)
        .order_by(func.count(Match.id).desc())
        .limit(10)
        .all()
    )
    top_subreddits = [
        SubredditStat(subreddit=name, match_count=cnt)
        for name, cnt in top_sub_rows
    ]

    return StatsResponse(
        total_matches=total_matches,
        matches_last_24h=matches_24h,
        matches_last_7d=matches_7d,
        top_keywords=top_keywords,
        top_subreddits=top_subreddits,
    )
