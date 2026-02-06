from __future__ import annotations

import logging
import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.clients import Client
from ..models.webhooks import WebhookConfig
from .auth import get_current_client
from .schemas import DiscordAuthUrlResponse, DiscordCallbackRequest, WebhookResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/discord", tags=["discord"])

# ---------------------------------------------------------------------------
# Discord OAuth2 configuration (read from environment)
# ---------------------------------------------------------------------------

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.getenv(
    "DISCORD_REDIRECT_URI", "http://localhost:3000/discord/callback"
)

DISCORD_OAUTH2_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/v10/oauth2/token"


@router.get("/auth-url", response_model=DiscordAuthUrlResponse)
def get_auth_url(
    client: Client = Depends(get_current_client),
):
    """Return a Discord OAuth2 authorization URL with webhook.incoming scope."""
    if not DISCORD_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discord OAuth is not configured. Set DISCORD_CLIENT_ID.",
        )

    state = secrets.token_urlsafe(32)

    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "webhook.incoming",
        "state": state,
    }
    auth_url = f"{DISCORD_OAUTH2_AUTHORIZE_URL}?{urlencode(params)}"

    return DiscordAuthUrlResponse(auth_url=auth_url, state=state)


@router.post("/callback", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
def discord_callback(
    payload: DiscordCallbackRequest,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Exchange a Discord OAuth2 code for a webhook and save it."""
    # Exchange the authorization code for an access token + webhook
    token_data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": payload.code,
        "redirect_uri": DISCORD_REDIRECT_URI,
    }

    try:
        with httpx.Client(timeout=10) as http_client:
            resp = http_client.post(
                DISCORD_TOKEN_URL,
                data=token_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as exc:
        logger.warning("Discord token exchange failed (network): %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach Discord to exchange the authorization code.",
        )

    if resp.status_code != 200:
        logger.warning(
            "Discord token exchange returned %d: %s",
            resp.status_code,
            resp.text[:200],
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Discord rejected the authorization code (invalid or expired).",
        )

    data = resp.json()
    webhook_data = data.get("webhook")
    if not webhook_data or not webhook_data.get("url"):
        logger.warning("Discord response missing webhook object: %s", data)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Discord did not return a webhook. Please try again.",
        )

    # Save the webhook URL
    webhook = WebhookConfig(
        client_id=client.id,
        url=webhook_data["url"],
        is_primary=True,
    )
    db.add(webhook)
    db.commit()
    db.refresh(webhook)
    return webhook
