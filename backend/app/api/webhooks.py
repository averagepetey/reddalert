from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.clients import Client
from ..models.webhooks import WebhookConfig
from .auth import get_current_client
from .schemas import WebhookCreate, WebhookResponse, WebhookTestResponse, WebhookUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.get("", response_model=list[WebhookResponse])
def list_webhooks(
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """List all webhook configurations for the authenticated client."""
    return (
        db.query(WebhookConfig)
        .filter(WebhookConfig.client_id == client.id)
        .order_by(WebhookConfig.created_at.desc())
        .all()
    )


@router.post("", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
def create_webhook(
    payload: WebhookCreate,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Add a new Discord webhook."""
    webhook = WebhookConfig(
        client_id=client.id,
        url=payload.url,
        is_primary=payload.is_primary,
    )
    db.add(webhook)
    db.commit()
    db.refresh(webhook)
    return webhook


@router.post("/{webhook_id}/test", response_model=WebhookTestResponse)
def test_webhook(
    webhook_id: uuid.UUID,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Send a test message to a webhook to verify it works."""
    webhook = (
        db.query(WebhookConfig)
        .filter(
            WebhookConfig.id == webhook_id,
            WebhookConfig.client_id == client.id,
        )
        .first()
    )
    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found.",
        )

    # Actually POST a test embed to the Discord webhook
    test_payload = {
        "embeds": [
            {
                "title": "Reddalert Test",
                "description": "This is a test message from Reddalert to verify your webhook is working.",
                "color": 0xFF4500,
                "footer": {"text": "Reddalert"},
            }
        ]
    }

    try:
        with httpx.Client(timeout=10) as http_client:
            resp = http_client.post(webhook.url, json=test_payload)
    except httpx.HTTPError as exc:
        logger.warning("Webhook test failed for %s: %s", webhook_id, exc)
        return WebhookTestResponse(
            success=False,
            message=f"Webhook test failed: could not reach Discord ({exc})",
        )

    now = datetime.now(timezone.utc)
    webhook.last_tested_at = now
    db.commit()

    if resp.status_code in (200, 204):
        return WebhookTestResponse(
            success=True,
            message="Webhook test successful! Check your Discord channel.",
        )

    logger.warning(
        "Webhook test returned %d for %s", resp.status_code, webhook_id,
    )
    return WebhookTestResponse(
        success=False,
        message=f"Webhook test failed: Discord returned HTTP {resp.status_code}.",
    )


@router.patch("/{webhook_id}", response_model=WebhookResponse)
def update_webhook(
    webhook_id: uuid.UUID,
    payload: WebhookUpdate,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Update a webhook (e.g., set as primary, change URL)."""
    webhook = (
        db.query(WebhookConfig)
        .filter(
            WebhookConfig.id == webhook_id,
            WebhookConfig.client_id == client.id,
        )
        .first()
    )
    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found.",
        )
    if payload.url is not None:
        webhook.url = payload.url
    if payload.is_active is not None:
        webhook.is_active = payload.is_active
    if payload.is_primary is not None:
        if payload.is_primary:
            # Unset other primary webhooks for this client
            db.query(WebhookConfig).filter(
                WebhookConfig.client_id == client.id,
                WebhookConfig.id != webhook_id,
            ).update({"is_primary": False})
        webhook.is_primary = payload.is_primary
    db.commit()
    db.refresh(webhook)
    return webhook


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook(
    webhook_id: uuid.UUID,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    """Remove a webhook configuration."""
    webhook = (
        db.query(WebhookConfig)
        .filter(
            WebhookConfig.id == webhook_id,
            WebhookConfig.client_id == client.id,
        )
        .first()
    )
    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found.",
        )
    db.delete(webhook)
    db.commit()
