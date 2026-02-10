import logging
import re

import discord
from discord import app_commands

from ...database import SessionLocal
from ...models.keywords import Keyword
from ...models.subreddits import MonitoredSubreddit
from ..checks import in_alert_channel
from ..utils import get_client_for_guild

logger = logging.getLogger(__name__)

_SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{1,50}$")


class AddGroup(app_commands.Group):
    """Commands to add keywords or subreddits."""

    def __init__(self):
        super().__init__(name="add", description="Add a keyword or subreddit to monitor")

    @app_commands.command(name="keyword", description="Add a new keyword to monitor")
    @app_commands.describe(phrases="Comma-separated phrases to monitor (e.g. arbitrage, arb opportunity)")
    @in_alert_channel()
    async def add_keyword(self, interaction: discord.Interaction, phrases: str) -> None:
        db = SessionLocal()
        try:
            client = get_client_for_guild(db, str(interaction.guild.id))
            if client is None:
                await interaction.response.send_message(
                    "Reddalert is not configured for this server.", ephemeral=True
                )
                return

            phrase_list = [p.strip() for p in phrases.split(",") if p.strip()]
            if not phrase_list:
                await interaction.response.send_message(
                    "Please provide at least one phrase.", ephemeral=True
                )
                return

            # Check for duplicates — look for any keyword with the exact same phrase set
            existing = (
                db.query(Keyword)
                .filter(Keyword.client_id == client.id, Keyword.is_active.is_(True))
                .all()
            )
            for kw in existing:
                if set(p.lower() for p in (kw.phrases or [])) == set(
                    p.lower() for p in phrase_list
                ):
                    await interaction.response.send_message(
                        f"A keyword with these phrases already exists: **{', '.join(kw.phrases)}**",
                        ephemeral=True,
                    )
                    return

            kw = Keyword(
                client_id=client.id,
                phrases=phrase_list,
                exclusions=[],
            )
            db.add(kw)
            db.commit()

            embed = discord.Embed(
                title="Keyword added",
                description=f"Now monitoring: **{', '.join(phrase_list)}**",
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed)
        except Exception:
            logger.exception("Error in /add keyword command")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An error occurred. Please try again.", ephemeral=True
                )
        finally:
            db.close()

    @app_commands.command(name="subreddit", description="Add a subreddit to monitor")
    @app_commands.describe(name="Subreddit name (with or without r/ prefix)")
    @in_alert_channel()
    async def add_subreddit(self, interaction: discord.Interaction, name: str) -> None:
        db = SessionLocal()
        try:
            client = get_client_for_guild(db, str(interaction.guild.id))
            if client is None:
                await interaction.response.send_message(
                    "Reddalert is not configured for this server.", ephemeral=True
                )
                return

            sub_name = name.strip().lower()
            if sub_name.startswith("r/"):
                sub_name = sub_name[2:]

            if not sub_name or not _SUBREDDIT_RE.match(sub_name):
                await interaction.response.send_message(
                    "Invalid subreddit name. Use only letters, numbers, and underscores (max 50 chars).",
                    ephemeral=True,
                )
                return

            # Check for duplicates
            existing = (
                db.query(MonitoredSubreddit)
                .filter(
                    MonitoredSubreddit.client_id == client.id,
                    MonitoredSubreddit.name == sub_name,
                )
                .first()
            )
            if existing:
                await interaction.response.send_message(
                    f"Subreddit **r/{sub_name}** is already being monitored.",
                    ephemeral=True,
                )
                return

            sub = MonitoredSubreddit(
                client_id=client.id,
                name=sub_name,
            )
            db.add(sub)
            db.commit()

            embed = discord.Embed(
                title="Subreddit added",
                description=f"Now monitoring **r/{sub_name}**.",
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed)
        except Exception:
            logger.exception("Error in /add subreddit command")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An error occurred. Please try again.", ephemeral=True
                )
        finally:
            db.close()


add_group = AddGroup()
