from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, Response, status
from passlib.hash import pbkdf2_sha256
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.clients import Client


# ---------------------------------------------------------------------------
# In-memory rate limiter (per-API-key)
# ---------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> tuple[bool, int, int]:
        """Check if request is allowed.

        Returns (allowed, remaining, reset_seconds).
        """
        now = time.time()
        cutoff = now - self.window_seconds
        # Prune old entries
        self._requests[key] = [t for t in self._requests[key] if t > cutoff]
        remaining = self.max_requests - len(self._requests[key])

        if remaining <= 0:
            # Calculate when the oldest request in the window expires
            oldest = min(self._requests[key]) if self._requests[key] else now
            reset_seconds = int(oldest + self.window_seconds - now) + 1
            return False, 0, reset_seconds

        self._requests[key].append(now)
        remaining -= 1  # account for the request we just added
        return True, remaining, self.window_seconds

    def reset(self) -> None:
        self._requests.clear()


rate_limiter = RateLimiter()


# ---------------------------------------------------------------------------
# API key hashing (PBKDF2-SHA256 — timing-attack resistant)
# ---------------------------------------------------------------------------

def verify_api_key(api_key: str, hashed_key: str) -> bool:
    """Verify a plaintext API key against its PBKDF2-SHA256 hash (constant-time)."""
    return pbkdf2_sha256.verify(api_key, hashed_key)


def hash_api_key(api_key: str) -> str:
    """Hash an API key using PBKDF2-SHA256 for storage.

    Uses 29000 rounds by default with a random salt per hash.
    """
    return pbkdf2_sha256.hash(api_key)


# ---------------------------------------------------------------------------
# Authentication dependency
# ---------------------------------------------------------------------------

def get_current_client(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> Client:
    """FastAPI dependency that validates the API key and returns the client.

    Security features:
    - Uses PBKDF2-SHA256 for constant-time hash comparison (timing-attack resistant)
    - Rate limits per API key prefix
    - Generic error messages (never reveals whether a key exists)
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
        )

    # Rate limit by a prefix of the raw key to avoid storing full keys in memory
    rate_key = x_api_key[:16]
    allowed, remaining, reset = rate_limiter.check(rate_key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={
                "X-RateLimit-Limit": str(rate_limiter.max_requests),
                "X-RateLimit-Remaining": "0",
                "Retry-After": str(reset),
            },
        )

    # Check all clients — scan is acceptable for MVP scale
    clients = db.query(Client).all()
    for client in clients:
        if verify_api_key(x_api_key, client.api_key):
            return client

    # Generic message — do not reveal whether any key exists
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
    )
