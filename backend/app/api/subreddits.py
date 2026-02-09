from __future__ import annotations

import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.clients import Client
from ..models.subreddits import MonitoredSubreddit
from .auth import get_current_client
from .schemas import SubredditCreate, SubredditResponse, SubredditSuggestion, SubredditUpdate

router = APIRouter(prefix="/api/subreddits", tags=["subreddits"])


@router.get("/search", response_model=list[SubredditSuggestion])
async def search_subreddits(q: str = Query(min_length=2)):
    """Search Reddit for subreddit suggestions (no auth required)."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(
            "https://www.reddit.com/subreddits/search.json",
            params={"q": q, "limit": 8, "raw_json": 1},
            headers={"User-Agent": "Reddalert/0.1"},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
    children = data.get("data", {}).get("children", [])
    return [
        SubredditSuggestion(
            name=child["data"].get("display_name", ""),
            subscribers=child["data"].get("subscribers", 0) or 0,
            description=(child["data"].get("public_description", "") or "")[:200],
        )
        for child in children
        if child.get("data")
    ]


@router.get("", response_model=list[SubredditResponse])
def list_subreddits(
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """List all monitored subreddits for the authenticated client."""
    return (
        db.query(MonitoredSubreddit)
        .filter(MonitoredSubreddit.client_id == client.id)
        .order_by(MonitoredSubreddit.created_at.desc())
        .all()
    )


@router.post("", response_model=SubredditResponse, status_code=status.HTTP_201_CREATED)
def add_subreddit(
    payload: SubredditCreate,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Add a subreddit to monitor."""
    # Check for duplicates
    existing = (
        db.query(MonitoredSubreddit)
        .filter(
            MonitoredSubreddit.client_id == client.id,
            MonitoredSubreddit.name == payload.name,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Already monitoring r/{payload.name}.",
        )

    sub = MonitoredSubreddit(
        client_id=client.id,
        name=payload.name,
        include_media_posts=payload.include_media_posts,
        dedupe_crossposts=payload.dedupe_crossposts,
        filter_bots=payload.filter_bots,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.patch("/{subreddit_id}", response_model=SubredditResponse)
def update_subreddit(
    subreddit_id: uuid.UUID,
    payload: SubredditUpdate,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Update subreddit settings."""
    sub = (
        db.query(MonitoredSubreddit)
        .filter(
            MonitoredSubreddit.id == subreddit_id,
            MonitoredSubreddit.client_id == client.id,
        )
        .first()
    )
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subreddit not found.",
        )
    if payload.include_media_posts is not None:
        sub.include_media_posts = payload.include_media_posts
    if payload.dedupe_crossposts is not None:
        sub.dedupe_crossposts = payload.dedupe_crossposts
    if payload.filter_bots is not None:
        sub.filter_bots = payload.filter_bots
    db.commit()
    db.refresh(sub)
    return sub


@router.delete("/{subreddit_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_subreddit(
    subreddit_id: uuid.UUID,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Stop monitoring a subreddit."""
    sub = (
        db.query(MonitoredSubreddit)
        .filter(
            MonitoredSubreddit.id == subreddit_id,
            MonitoredSubreddit.client_id == client.id,
        )
        .first()
    )
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subreddit not found.",
        )
    db.delete(sub)
    db.commit()
