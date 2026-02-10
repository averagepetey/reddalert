import discord
from discord import app_commands

from ..checks import in_alert_channel


@app_commands.command(name="help", description="List all available Reddalert commands")
@in_alert_channel()
async def help_command(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="Reddalert Commands",
        description="Manage your Reddit monitoring directly from Discord.",
        color=discord.Color.blue(),
    )

    embed.add_field(
        name="/remove <keyword> [duration]",
        value=(
            "Silence a keyword permanently or temporarily.\n"
            "Examples:\n"
            "`/remove arb` — silence permanently\n"
            "`/remove arb 20m` — silence for 20 minutes\n"
            "Durations: `30s`, `20m`, `2h`, `1d` (max 30 days)"
        ),
        inline=False,
    )

    embed.add_field(
        name="/add keyword <phrases>",
        value=(
            "Add a new keyword to monitor.\n"
            "Example: `/add keyword arbitrage, arb opportunity`"
        ),
        inline=False,
    )

    embed.add_field(
        name="/add subreddit <name>",
        value=(
            "Add a subreddit to monitor.\n"
            "Example: `/add subreddit wallstreetbets`"
        ),
        inline=False,
    )

    embed.add_field(
        name="/help",
        value="Show this help message.",
        inline=False,
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)
