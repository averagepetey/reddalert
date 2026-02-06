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
# Discord bot configuration (read from environment)
# ---------------------------------------------------------------------------

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_REDIRECT_URI = os.getenv(
    "DISCORD_REDIRECT_URI", "http://localhost:3000/discord/callback"
)

DISCORD_OAUTH2_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_API_BASE = "https://discord.com/api/v10"

# MANAGE_CHANNELS (16) | MANAGE_WEBHOOKS (536870912)
BOT_PERMISSIONS = 536870928


# ---------------------------------------------------------------------------
# Helper functions for Discord REST API calls
# ---------------------------------------------------------------------------

def _create_private_channel(
    guild_id: str, headers: dict
) -> dict:
    """Create a private #reddalert-alerts channel in the guild.

    The channel denies VIEW_CHANNEL (1024) for @everyone (role id = guild_id).
    Only users with ADMINISTRATOR permission can see it.
    """
    payload = {
        "name": "reddalert-alerts",
        "type": 0,  # text channel
        "permission_overwrites": [
            {
                "id": guild_id,
                "type": 0,  # role
                "deny": "1024",  # VIEW_CHANNEL
            }
        ],
    }

    try:
        with httpx.Client(timeout=10) as http_client:
            resp = http_client.post(
                f"{DISCORD_API_BASE}/guilds/{guild_id}/channels",
                json=payload,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        logger.warning("Discord channel creation failed (network): %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach Discord to create channel.",
        )

    if resp.status_code == 403:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bot lacks permission to create channels in this server.",
        )

    if resp.status_code >= 400:
        logger.warning(
            "Discord channel creation returned %d: %s",
            resp.status_code,
            resp.text[:200],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Discord rejected the channel creation request.",
        )

    return resp.json()


def _create_webhook(
    channel_id: str, headers: dict
) -> dict:
    """Create a webhook named 'Reddalert' in the given channel."""
    payload = {"name": "Reddalert"}

    try:
        with httpx.Client(timeout=10) as http_client:
            resp = http_client.post(
                f"{DISCORD_API_BASE}/channels/{channel_id}/webhooks",
                json=payload,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        logger.warning("Discord webhook creation failed (network): %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach Discord to create webhook.",
        )

    if resp.status_code >= 400:
        logger.warning(
            "Discord webhook creation returned %d: %s",
            resp.status_code,
            resp.text[:200],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Discord rejected the webhook creation request.",
        )

    return resp.json()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/auth-url", response_model=DiscordAuthUrlResponse)
def get_auth_url(
    client: Client = Depends(get_current_client),
):
    """Return a Discord OAuth2 authorization URL with bot scope."""
    if not DISCORD_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discord OAuth is not configured. Set DISCORD_CLIENT_ID.",
        )

    state = secrets.token_urlsafe(32)

    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "scope": "bot",
        "permissions": str(BOT_PERMISSIONS),
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
    """Accept guild_id from bot authorization, create private channel + webhook."""
    if not DISCORD_BOT_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discord bot token is not configured. Set DISCORD_BOT_TOKEN.",
        )

    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }

    # Step 1: Create private #reddalert-alerts channel
    channel_data = _create_private_channel(payload.guild_id, headers)
    channel_id = channel_data["id"]

    # Step 2: Create webhook in the new channel
    webhook_data = _create_webhook(channel_id, headers)
    webhook_url = f"https://discord.com/api/webhooks/{webhook_data['id']}/{webhook_data['token']}"

    # Step 3: Save webhook to DB
    webhook = WebhookConfig(
        client_id=client.id,
        url=webhook_url,
        is_primary=True,
    )
    db.add(webhook)
    db.commit()
    db.refresh(webhook)
    return webhook
