import discord
from discord import app_commands

from ..database import SessionLocal
from ..models.webhooks import WebhookConfig


def in_alert_channel():
    """``app_commands.check`` that restricts commands to the configured alerts channel."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )
            return False

        db = SessionLocal()
        try:
            webhook = (
                db.query(WebhookConfig)
                .filter(
                    WebhookConfig.guild_id == str(interaction.guild.id),
                    WebhookConfig.is_active.is_(True),
                )
                .first()
            )
        finally:
            db.close()

        if webhook is None:
            await interaction.response.send_message(
                "Reddalert is not configured for this server.", ephemeral=True
            )
            return False

        if webhook.channel_id and str(interaction.channel_id) != webhook.channel_id:
            await interaction.response.send_message(
                f"This command only works in <#{webhook.channel_id}>.",
                ephemeral=True,
            )
            return False

        return True

    return app_commands.check(predicate)
