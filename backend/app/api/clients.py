from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.clients import Client
from .auth import get_current_client, hash_api_key
from .schemas import ClientCreate, ClientCreateResponse, ClientResponse, ClientUpdate

router = APIRouter(prefix="/api/clients", tags=["clients"])


@router.post("", response_model=ClientCreateResponse, status_code=status.HTTP_201_CREATED)
def create_client(payload: ClientCreate, db: Session = Depends(get_db)):
    """Create a new client. Returns the API key in plaintext (only time it is shown)."""
    raw_key = secrets.token_urlsafe(32)
    hashed_key = hash_api_key(raw_key)

    client = Client(
        api_key=hashed_key,
        email=payload.email,
        polling_interval=payload.polling_interval,
    )
    db.add(client)
    db.commit()
    db.refresh(client)

    # Build response with plaintext key
    resp = ClientCreateResponse.model_validate(client)
    resp.api_key = raw_key
    return resp


@router.get("/me", response_model=ClientResponse)
def get_me(client: Client = Depends(get_current_client)):
    """Get current authenticated client info."""
    return client


@router.patch("/me", response_model=ClientResponse)
def update_me(
    payload: ClientUpdate,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Update current client's email or polling interval."""
    if payload.email is not None:
        client.email = payload.email
    if payload.polling_interval is not None:
        client.polling_interval = payload.polling_interval
    db.commit()
    db.refresh(client)
    return client
