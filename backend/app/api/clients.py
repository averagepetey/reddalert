from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.clients import Client
from .auth import create_access_token, get_current_client, hash_password, verify_password
from .schemas import ClientResponse, ClientUpdate, LoginRequest, RegisterRequest, TokenResponse

router = APIRouter(prefix="/api/clients", tags=["clients"])
auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


@auth_router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new client with email and password. Returns a JWT token."""
    existing = db.query(Client).filter(Client.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    client = Client(
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(client)
    db.commit()
    db.refresh(client)

    token = create_access_token(str(client.id))
    return TokenResponse(access_token=token)


@auth_router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate with email and password. Returns a JWT token."""
    client = db.query(Client).filter(Client.email == payload.email).first()
    if not client or not verify_password(payload.password, client.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(str(client.id))
    return TokenResponse(access_token=token)


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
