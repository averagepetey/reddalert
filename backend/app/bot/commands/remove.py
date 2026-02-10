import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands

from ...database import SessionLocal
from ...models.keywords import Keyword
from ..checks import in_alert_channel
from ..utils import get_client_for_guild, parse_duration

logger = logging.getLogger(__name__)


def _reactivate_keyword(keyword_id: str) -> None:
    """Scheduled callback to reactivate a temporarily silenced keyword."""
    db = SessionLocal()
    try:
        keyword = db.query(Keyword).filter(Keyword.id == keyword_id).first()
        if keyword and keyword.silenced_until is not None:
            keyword.is_active = True
            keyword.silenced_until = None
            db.commit()
            logger.info("Reactivated keyword %s after temporary silence", keyword_id)
    except Exception:
        logger.exception("Failed to reactivate keyword %s", keyword_id)
        db.rollback()
    finally:
        db.close()


def _restore_phrase(keyword_id: str, phrase: str) -> None:
    """Scheduled callback to restore a temporarily removed phrase."""
    db = SessionLocal()
    try:
        keyword = db.query(Keyword).filter(Keyword.id == keyword_id).first()
        if keyword is not None:
            current = list(keyword.phrases or [])
            if phrase.lower() not in [p.lower() for p in current]:
                current.append(phrase)
                keyword.phrases = current
                db.commit()
                logger.info("Restored phrase '%s' to keyword %s", phrase, keyword_id)
    except Exception:
        logger.exception("Failed to restore phrase '%s' to keyword %s", phrase, keyword_id)
        db.rollback()
    finally:
        db.close()


@app_commands.command(name="remove", description="Silence a keyword permanently or temporarily")
@app_commands.describe(
    keyword="The keyword phrase to silence",
    duration="Optional duration (e.g. 20m, 2h, 1d). Omit to silence permanently.",
)
@in_alert_channel()
async def remove_command(
    interaction: discord.Interaction,
    keyword: str,
    duration: Optional[str] = None,
) -> None:
    db = SessionLocal()
    try:
        client = get_client_for_guild(db, str(interaction.guild.id))
        if client is None:
            await interaction.response.send_message(
                "Reddalert is not configured for this server.", ephemeral=True
            )
            return

        # Find active keywords where the phrases array contains the search term
        all_keywords = (
            db.query(Keyword)
            .filter(Keyword.client_id == client.id, Keyword.is_active.is_(True))
            .all()
        )

        search = keyword.lower().strip()
        matches = [
            kw for kw in all_keywords
            if any(search == phrase.lower() for phrase in (kw.phrases or []))
        ]

        if len(matches) == 0:
            await interaction.response.send_message(
                f"No active keyword matching **{keyword}**.", ephemeral=True
            )
            return

        if len(matches) > 1:
            lines = []
            for i, kw in enumerate(matches, 1):
                phrases_str = ", ".join(kw.phrases or [])
                lines.append(f"{i}. {phrases_str}")
            listing = "\n".join(lines)
            await interaction.response.send_message(
                f"Multiple keywords match **{keyword}**. Please be more specific:\n{listing}",
                ephemeral=True,
            )
            return

        matched_kw = matches[0]
        all_phrases = matched_kw.phrases or []
        remaining_phrases = [p for p in all_phrases if p.lower() != search]
        is_last_phrase = len(remaining_phrases) == 0

        if duration:
            td = parse_duration(duration)
            if td is None:
                await interaction.response.send_message(
                    "Invalid duration. Use formats like `20m`, `2h`, `1d`, `30s` (max 30 days).",
                    ephemeral=True,
                )
                return

            reactivate_at = datetime.now(timezone.utc) + td

            if is_last_phrase:
                # Only phrase left — silence the whole keyword temporarily
                matched_kw.is_active = False
                matched_kw.silenced_until = reactivate_at
            else:
                # Remove just this phrase; store it so we can restore it later
                matched_kw.phrases = remaining_phrases
                if not matched_kw.exclusions:
                    matched_kw.exclusions = []

            db.commit()

            # Schedule reactivation via APScheduler
            from ...main import scheduler

            job_id = f"reactivate_{matched_kw.id}_{search}"
            if is_last_phrase:
                scheduler.add_job(
                    _reactivate_keyword,
                    "date",
                    run_date=reactivate_at,
                    args=[str(matched_kw.id)],
                    id=job_id,
                    replace_existing=True,
                )
            else:
                scheduler.add_job(
                    _restore_phrase,
                    "date",
                    run_date=reactivate_at,
                    args=[str(matched_kw.id), keyword.strip()],
                    id=job_id,
                    replace_existing=True,
                )

            embed = discord.Embed(
                title="Keyword silenced temporarily",
                description=f"**{keyword}** has been silenced.",
                color=discord.Color.orange(),
            )
            embed.add_field(
                name="Reactivates at",
                value=f"<t:{int(reactivate_at.timestamp())}:F>",
            )
            if remaining_phrases:
                embed.add_field(
                    name="Still active",
                    value=", ".join(remaining_phrases),
                    inline=False,
                )
            await interaction.response.send_message(embed=embed)
        else:
            if is_last_phrase:
                # Only phrase left — deactivate the whole keyword
                matched_kw.is_active = False
            else:
                # Remove just this phrase from the array
                matched_kw.phrases = remaining_phrases

            db.commit()

            embed = discord.Embed(
                title="Keyword removed",
                description=f"**{keyword}** has been permanently removed.",
                color=discord.Color.red(),
            )
            if remaining_phrases:
                embed.add_field(
                    name="Still active",
                    value=", ".join(remaining_phrases),
                    inline=False,
                )
            else:
                embed.add_field(
                    name="To reactivate",
                    value="Use `/add keyword` or re-enable via the web app.",
                )
            await interaction.response.send_message(embed=embed)
    except Exception:
        logger.exception("Error in /remove command")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "An error occurred. Please try again.", ephemeral=True
            )
    finally:
        db.close()
