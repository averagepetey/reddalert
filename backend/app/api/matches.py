from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.clients import Client
from ..models.matches import Match
from .auth import get_current_client
from .schemas import MatchResponse, PaginatedMatches

router = APIRouter(prefix="/api/matches", tags=["matches"])


@router.get("", response_model=PaginatedMatches)
def list_matches(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    subreddit: Optional[str] = Query(default=None),
    keyword_id: Optional[uuid.UUID] = Query(default=None),
    alert_status: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """List matches with pagination and optional filters."""
    query = db.query(Match).filter(Match.client_id == client.id)

    if subreddit:
        query = query.filter(Match.subreddit == subreddit.lower())
    if keyword_id:
        query = query.filter(Match.keyword_id == keyword_id)
    if alert_status:
        query = query.filter(Match.alert_status == alert_status)
    if start_date:
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        query = query.filter(Match.detected_at >= start_dt)
    if end_date:
        end_dt = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)
        query = query.filter(Match.detected_at <= end_dt)

    total = query.count()
    items = (
        query.order_by(Match.detected_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return PaginatedMatches(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{match_id}", response_model=MatchResponse)
def get_match(
    match_id: uuid.UUID,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Get a single match by ID."""
    match = (
        db.query(Match)
        .filter(Match.id == match_id, Match.client_id == client.id)
        .first()
    )
    if not match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Match not found.",
        )
    return match
