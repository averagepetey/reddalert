from __future__ import annotations

import ipaddress
import re
import secrets
import socket
import uuid
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Subreddit names: alphanumeric + underscores, 1-50 chars
_SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{1,50}$")

# Discord webhook URL pattern (SSRF prevention)
_DISCORD_WEBHOOK_RE = re.compile(
    r"^https://discord(?:app)?\.com/api/webhooks/\d+/[\w-]+$"
)

# Input limits
MAX_PHRASE_LENGTH = 200
MAX_EXCLUSION_LENGTH = 100
MAX_KEYWORD_PHRASES = 20
MAX_EXCLUSIONS = 20


def _sanitize(value: str) -> str:
    """Strip whitespace and angle brackets to prevent script injection."""
    return value.strip().replace("<", "").replace(">", "")


# ---------------------------------------------------------------------------
# API key generation (prefixed)
# ---------------------------------------------------------------------------

API_KEY_PREFIX = "rda_"


def generate_api_key() -> str:
    """Generate a cryptographically secure API key with a recognizable prefix."""
    random_part = secrets.token_urlsafe(32)
    return f"{API_KEY_PREFIX}{random_part}"


# ---------------------------------------------------------------------------
# SSRF prevention for webhook URLs
# ---------------------------------------------------------------------------

def _check_ssrf(hostname: str) -> None:
    """Check that a hostname does not resolve to a private/internal IP."""
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ValueError("Could not resolve webhook hostname")

    for family, type_, proto, canonname, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                raise ValueError(
                    "Webhook URL must not point to a private or internal address"
                )
        except ValueError as e:
            if "private" in str(e) or "resolve" in str(e):
                raise
            continue


# --- Client schemas ---

class ClientCreate(BaseModel):
    email: Optional[str] = None
    polling_interval: int = Field(default=60, ge=1, le=1440)


class ClientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: Optional[str]
    polling_interval: int
    created_at: datetime
    api_key_masked: str = "rda_••••••••••••"


class ClientCreateResponse(ClientResponse):
    api_key: str  # plaintext, only returned on creation


class ClientUpdate(BaseModel):
    email: Optional[str] = None
    polling_interval: Optional[int] = Field(default=None, ge=1, le=1440)


# --- Keyword schemas ---

class KeywordCreate(BaseModel):
    phrases: List[str] = Field(min_length=1, max_length=MAX_KEYWORD_PHRASES)
    exclusions: List[str] = Field(default_factory=list, max_length=MAX_EXCLUSIONS)
    proximity_window: int = Field(default=15, ge=1, le=100)
    require_order: bool = False
    use_stemming: bool = False

    @field_validator("phrases")
    @classmethod
    def phrases_not_empty(cls, v: List[str]) -> List[str]:
        cleaned = [_sanitize(p) for p in v if p.strip()]
        if not cleaned:
            raise ValueError("At least one non-empty phrase is required")
        for p in cleaned:
            if len(p) > MAX_PHRASE_LENGTH:
                raise ValueError(
                    f"Phrase exceeds maximum length of {MAX_PHRASE_LENGTH} characters"
                )
        return cleaned

    @field_validator("exclusions")
    @classmethod
    def clean_exclusions(cls, v: List[str]) -> List[str]:
        cleaned = [_sanitize(e) for e in v if e.strip()]
        for e in cleaned:
            if len(e) > MAX_EXCLUSION_LENGTH:
                raise ValueError(
                    f"Exclusion term exceeds maximum length of {MAX_EXCLUSION_LENGTH} characters"
                )
        return cleaned


class KeywordUpdate(BaseModel):
    phrases: Optional[List[str]] = Field(default=None, max_length=MAX_KEYWORD_PHRASES)
    exclusions: Optional[List[str]] = Field(default=None, max_length=MAX_EXCLUSIONS)
    proximity_window: Optional[int] = Field(default=None, ge=1, le=100)
    require_order: Optional[bool] = None
    use_stemming: Optional[bool] = None
    is_active: Optional[bool] = None

    @field_validator("phrases")
    @classmethod
    def phrases_not_empty(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            cleaned = [_sanitize(p) for p in v if p.strip()]
            if not cleaned:
                raise ValueError("At least one non-empty phrase is required")
            for p in cleaned:
                if len(p) > MAX_PHRASE_LENGTH:
                    raise ValueError(
                        f"Phrase exceeds maximum length of {MAX_PHRASE_LENGTH} characters"
                    )
            return cleaned
        return v

    @field_validator("exclusions")
    @classmethod
    def clean_exclusions(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            cleaned = [_sanitize(e) for e in v if e.strip()]
            for e in cleaned:
                if len(e) > MAX_EXCLUSION_LENGTH:
                    raise ValueError(
                        f"Exclusion term exceeds maximum length of {MAX_EXCLUSION_LENGTH} characters"
                    )
            return cleaned
        return v


class KeywordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    phrases: List[str]
    exclusions: List[str]
    proximity_window: int
    require_order: bool
    use_stemming: bool
    is_active: bool
    created_at: datetime


# --- Subreddit schemas ---

class SubredditCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    include_media_posts: bool = True
    dedupe_crossposts: bool = True
    filter_bots: bool = False

    @field_validator("name")
    @classmethod
    def clean_subreddit_name(cls, v: str) -> str:
        v = v.strip().lower()
        if v.startswith("r/"):
            v = v[2:]
        if not v:
            raise ValueError("Subreddit name cannot be empty")
        if not _SUBREDDIT_RE.match(v):
            raise ValueError(
                "Subreddit name must contain only letters, numbers, "
                "and underscores (max 50 chars)"
            )
        return v


class SubredditUpdate(BaseModel):
    include_media_posts: Optional[bool] = None
    dedupe_crossposts: Optional[bool] = None
    filter_bots: Optional[bool] = None


class SubredditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    name: str
    status: str
    include_media_posts: bool
    dedupe_crossposts: bool
    filter_bots: bool
    last_polled_at: Optional[datetime]
    created_at: datetime


# --- Webhook schemas ---

class WebhookCreate(BaseModel):
    url: str
    is_primary: bool = True

    @field_validator("url")
    @classmethod
    def validate_webhook_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("https://"):
            raise ValueError("Webhook URL must use HTTPS")
        if not _DISCORD_WEBHOOK_RE.match(v):
            raise ValueError(
                "Webhook URL must be a valid Discord webhook URL "
                "(https://discord.com/api/webhooks/...)"
            )
        # SSRF prevention: resolve hostname and check for private IPs
        parsed = urlparse(v)
        hostname = parsed.hostname
        if hostname:
            _check_ssrf(hostname)
        return v


class WebhookUpdate(BaseModel):
    url: Optional[str] = None
    is_primary: Optional[bool] = None
    is_active: Optional[bool] = None

    @field_validator("url")
    @classmethod
    def validate_webhook_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v.startswith("https://"):
                raise ValueError("Webhook URL must use HTTPS")
            if not _DISCORD_WEBHOOK_RE.match(v):
                raise ValueError(
                    "Webhook URL must be a valid Discord webhook URL "
                    "(https://discord.com/api/webhooks/...)"
                )
            parsed = urlparse(v)
            hostname = parsed.hostname
            if hostname:
                _check_ssrf(hostname)
        return v


class WebhookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    url: str
    is_primary: bool
    is_active: bool
    last_tested_at: Optional[datetime]
    created_at: datetime


class WebhookTestResponse(BaseModel):
    success: bool
    message: str


# --- Match schemas ---

class MatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    keyword_id: uuid.UUID
    content_type: str
    subreddit: str
    matched_phrase: str
    also_matched: List[str]
    snippet: str
    proximity_score: Optional[float]
    reddit_url: str
    reddit_author: str
    is_deleted: bool
    detected_at: datetime
    alert_sent_at: Optional[datetime]
    alert_status: str
    created_at: datetime


class PaginatedMatches(BaseModel):
    items: List[MatchResponse]
    total: int
    page: int
    per_page: int


# --- Stats schemas ---

class KeywordStat(BaseModel):
    keyword_id: uuid.UUID
    phrases: List[str]
    match_count: int


class SubredditStat(BaseModel):
    subreddit: str
    match_count: int


class StatsResponse(BaseModel):
    total_matches: int
    matches_last_24h: int
    matches_last_7d: int
    top_keywords: List[KeywordStat]
    top_subreddits: List[SubredditStat]
