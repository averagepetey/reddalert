from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.clients import Client
from ..models.keywords import Keyword
from .auth import get_current_client
from .schemas import KeywordCreate, KeywordResponse, KeywordUpdate

router = APIRouter(prefix="/api/keywords", tags=["keywords"])


def _get_keyword_or_404(
    keyword_id: uuid.UUID, client: Client, db: Session
) -> Keyword:
    keyword = (
        db.query(Keyword)
        .filter(Keyword.id == keyword_id, Keyword.client_id == client.id)
        .first()
    )
    if not keyword:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Keyword not found.",
        )
    return keyword


@router.get("", response_model=list[KeywordResponse])
def list_keywords(
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """List all keywords for the authenticated client."""
    return (
        db.query(Keyword)
        .filter(Keyword.client_id == client.id, Keyword.is_active == True)
        .order_by(Keyword.created_at.desc())
        .all()
    )


@router.post("", response_model=KeywordResponse, status_code=status.HTTP_201_CREATED)
def create_keyword(
    payload: KeywordCreate,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Create a new keyword configuration."""
    keyword = Keyword(
        client_id=client.id,
        phrases=payload.phrases,
        exclusions=payload.exclusions,
        proximity_window=payload.proximity_window,
        require_order=payload.require_order,
        use_stemming=payload.use_stemming,
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)
    return keyword


@router.get("/{keyword_id}", response_model=KeywordResponse)
def get_keyword(
    keyword_id: uuid.UUID,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Get a single keyword by ID."""
    return _get_keyword_or_404(keyword_id, client, db)


@router.patch("/{keyword_id}", response_model=KeywordResponse)
def update_keyword(
    keyword_id: uuid.UUID,
    payload: KeywordUpdate,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Update a keyword configuration."""
    keyword = _get_keyword_or_404(keyword_id, client, db)
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(keyword, field, value)
    db.commit()
    db.refresh(keyword)
    return keyword


@router.delete("/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_keyword(
    keyword_id: uuid.UUID,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Soft-delete a keyword (set is_active=False)."""
    keyword = _get_keyword_or_404(keyword_id, client, db)
    keyword.is_active = False
    db.commit()
