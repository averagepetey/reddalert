import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from ..database import SessionLocal
from ..models.keywords import Keyword
from ..models.webhooks import WebhookConfig
from .commands.add import add_group
from .commands.help import help_command
from .commands.remove import _reactivate_keyword, remove_command

logger = logging.getLogger(__name__)

intents = discord.Intents.default()

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready() -> None:
    logger.info("Discord bot ready as %s in %d guild(s)", bot.user, len(bot.guilds))

    # Backfill existing webhooks missing guild_id/channel_id
    await _backfill_webhooks()

    # Re-schedule pending keyword reactivations
    _reschedule_pending_reactivations()

    # Sync command tree
    try:
        synced = await bot.tree.sync()
        logger.info("Synced %d slash command(s)", len(synced))
    except Exception:
        logger.exception("Failed to sync command tree")


async def _backfill_webhooks() -> None:
    """Populate guild_id/channel_id for webhooks that are missing them."""
    db = SessionLocal()
    try:
        webhooks = (
            db.query(WebhookConfig)
            .filter(
                WebhookConfig.guild_id.is_(None),
                WebhookConfig.is_active.is_(True),
            )
            .all()
        )
        for wh in webhooks:
            try:
                # Extract webhook ID and token from URL
                # Format: https://discord.com/api/webhooks/{id}/{token}
                parts = wh.url.rstrip("/").split("/")
                if len(parts) < 2:
                    continue
                wh_token = parts[-1]
                wh_id = parts[-2]

                import httpx

                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        f"https://discord.com/api/v10/webhooks/{wh_id}/{wh_token}"
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        wh.guild_id = data.get("guild_id")
                        wh.channel_id = data.get("channel_id")
                        db.commit()
                        logger.info(
                            "Backfilled webhook %s: guild=%s channel=%s",
                            wh.id,
                            wh.guild_id,
                            wh.channel_id,
                        )
            except Exception:
                logger.warning("Failed to backfill webhook %s", wh.id)
    finally:
        db.close()


def _reschedule_pending_reactivations() -> None:
    """Re-schedule reactivation jobs for keywords silenced with an expiry."""
    from ..main import scheduler

    db = SessionLocal()
    try:
        silenced = (
            db.query(Keyword)
            .filter(
                Keyword.silenced_until.isnot(None),
                Keyword.is_active.is_(False),
            )
            .all()
        )
        now = datetime.now(timezone.utc)
        for kw in silenced:
            if kw.silenced_until <= now:
                # Already expired — reactivate immediately
                kw.is_active = True
                kw.silenced_until = None
                db.commit()
                logger.info("Reactivated expired keyword %s on startup", kw.id)
            else:
                job_id = f"reactivate_{kw.id}"
                scheduler.add_job(
                    _reactivate_keyword,
                    "date",
                    run_date=kw.silenced_until,
                    args=[str(kw.id)],
                    id=job_id,
                    replace_existing=True,
                )
                logger.info(
                    "Re-scheduled reactivation for keyword %s at %s",
                    kw.id,
                    kw.silenced_until,
                )
    finally:
        db.close()


async def setup_hook() -> None:
    bot.tree.add_command(remove_command)
    bot.tree.add_command(help_command)
    bot.tree.add_command(add_group)


bot.setup_hook = setup_hook
