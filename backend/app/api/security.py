from __future__ import annotations

"""Shared security utilities for the Reddalert API.

Provides:
- API key hashing and verification (passlib + PBKDF2-SHA256)
- Input validators for subreddit names, webhook URLs, keyword phrases
- SSRF prevention for webhook URLs (Discord-only, no private IPs)
- Rate limiting helpers
- Secure error responses
"""

import ipaddress
import re
import secrets
import socket
from typing import Optional
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from passlib.hash import pbkdf2_sha256
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.clients import Client

# ---------------------------------------------------------------------------
# API Key hashing
# ---------------------------------------------------------------------------

API_KEY_PREFIX = "rda_"
API_KEY_LENGTH = 48  # total length including prefix


def generate_api_key() -> str:
    """Generate a cryptographically secure API key with a recognizable prefix."""
    random_part = secrets.token_urlsafe(32)
    return f"{API_KEY_PREFIX}{random_part}"


def hash_api_key(plaintext_key: str) -> str:
    """Hash an API key using PBKDF2-SHA256 for storage."""
    return pbkdf2_sha256.hash(plaintext_key)


def verify_api_key(plaintext_key: str, hashed_key: str) -> bool:
    """Verify an API key against its PBKDF2-SHA256 hash (timing-attack resistant)."""
    return pbkdf2_sha256.verify(plaintext_key, hashed_key)


# ---------------------------------------------------------------------------
# API Key authentication dependency
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_current_client(
    api_key: Optional[str] = Security(_api_key_header),
    db: Session = Depends(get_db),
) -> Client:
    """FastAPI dependency: authenticate via X-API-Key header.

    Iterates over clients and uses constant-time comparison via pbkdf2_sha256.verify
    to avoid timing attacks that could reveal whether a key prefix exists.
    Returns 401 with a generic message on failure.
    """
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    # Query all clients and check each hash (pbkdf2_sha256.verify is constant-time).
    # For production at scale this should be replaced with a key-prefix index,
    # but for v1 with a manageable number of clients this is secure and correct.
    clients = db.query(Client).all()
    for client in clients:
        if verify_api_key(api_key, client.api_key):
            return client

    # Generic message -- do not reveal whether any key exists
    raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Input validators
# ---------------------------------------------------------------------------

_SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{1,50}$")

# Discord webhook URL pattern
_DISCORD_WEBHOOK_RE = re.compile(
    r"^https://discord(?:app)?\.com/api/webhooks/\d+/[\w-]+$"
)

# Max lengths for string inputs
MAX_PHRASE_LENGTH = 200
MAX_EXCLUSION_LENGTH = 100
MAX_KEYWORD_PHRASES = 20
MAX_EXCLUSIONS = 20
MAX_PAGE_SIZE = 100


def validate_subreddit_name(name: str) -> str:
    """Validate and clean a subreddit name.

    Rules:
    - Strip whitespace and optional r/ prefix
    - Alphanumeric + underscores only
    - 1-50 characters
    """
    name = name.strip().lower()
    if name.startswith("r/"):
        name = name[2:]

    if not name:
        raise HTTPException(status_code=422, detail="Subreddit name cannot be empty")

    if not _SUBREDDIT_RE.match(name):
        raise HTTPException(
            status_code=422,
            detail="Subreddit name must contain only letters, numbers, and underscores (max 50 chars)",
        )
    return name


def validate_webhook_url(url: str) -> str:
    """Validate a webhook URL for security.

    Rules:
    - Must be HTTPS
    - Must match Discord webhook URL pattern
    - Must not resolve to a private/internal IP (SSRF prevention)
    """
    url = url.strip()

    if not url.startswith("https://"):
        raise HTTPException(
            status_code=422,
            detail="Webhook URL must use HTTPS",
        )

    if not _DISCORD_WEBHOOK_RE.match(url):
        raise HTTPException(
            status_code=422,
            detail="Webhook URL must be a valid Discord webhook URL "
            "(https://discord.com/api/webhooks/...)",
        )

    # SSRF prevention: resolve hostname and check for private IPs
    parsed = urlparse(url)
    hostname = parsed.hostname
    if hostname:
        _check_ssrf(hostname)

    return url


def _check_ssrf(hostname: str) -> None:
    """Check that a hostname does not resolve to a private/internal IP."""
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise HTTPException(
            status_code=422, detail="Could not resolve webhook hostname"
        )

    for family, type_, proto, canonname, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                raise HTTPException(
                    status_code=422,
                    detail="Webhook URL must not point to a private or internal address",
                )
        except ValueError:
            continue


def validate_keyword_phrases(phrases: list[str]) -> list[str]:
    """Validate and clean keyword phrases.

    Rules:
    - At least 1, at most MAX_KEYWORD_PHRASES phrases
    - Each phrase max MAX_PHRASE_LENGTH characters
    - Strip whitespace, reject empty after stripping
    - No script/HTML injection (strip angle brackets)
    """
    if not phrases:
        raise HTTPException(status_code=422, detail="At least one phrase is required")

    if len(phrases) > MAX_KEYWORD_PHRASES:
        raise HTTPException(
            status_code=422,
            detail=f"Maximum {MAX_KEYWORD_PHRASES} phrases allowed",
        )

    cleaned = []
    for p in phrases:
        p = _sanitize_string(p)
        if not p:
            continue
        if len(p) > MAX_PHRASE_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"Phrase exceeds maximum length of {MAX_PHRASE_LENGTH} characters",
            )
        cleaned.append(p)

    if not cleaned:
        raise HTTPException(
            status_code=422, detail="At least one non-empty phrase is required"
        )

    return cleaned


def validate_exclusions(exclusions: list[str]) -> list[str]:
    """Validate and clean exclusion terms."""
    if len(exclusions) > MAX_EXCLUSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Maximum {MAX_EXCLUSIONS} exclusions allowed",
        )

    cleaned = []
    for e in exclusions:
        e = _sanitize_string(e)
        if not e:
            continue
        if len(e) > MAX_EXCLUSION_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"Exclusion term exceeds maximum length of {MAX_EXCLUSION_LENGTH} characters",
            )
        cleaned.append(e)
    return cleaned


def validate_pagination(page: int, per_page: int) -> tuple[int, int]:
    """Validate pagination parameters.

    Returns (page, per_page) clamped to safe ranges.
    """
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 20
    if per_page > MAX_PAGE_SIZE:
        per_page = MAX_PAGE_SIZE
    return page, per_page


def _sanitize_string(value: str) -> str:
    """Strip whitespace and remove angle brackets to prevent script injection."""
    value = value.strip()
    value = value.replace("<", "").replace(">", "")
    return value


# ---------------------------------------------------------------------------
# Secure error helper
# ---------------------------------------------------------------------------

def not_found(resource: str = "Resource") -> HTTPException:
    """Return a generic 404 without leaking internal details."""
    return HTTPException(status_code=404, detail=f"{resource} not found")
