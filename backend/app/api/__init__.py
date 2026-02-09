from .clients import auth_router, router as clients_router
from .discord import router as discord_router
from .keywords import router as keywords_router
from .matches import router as matches_router
from .poll import router as poll_router
from .stats import router as stats_router
from .subreddits import router as subreddits_router
from .webhooks import router as webhooks_router

__all__ = [
    "auth_router",
    "clients_router",
    "discord_router",
    "keywords_router",
    "matches_router",
    "poll_router",
    "stats_router",
    "subreddits_router",
    "webhooks_router",
]
