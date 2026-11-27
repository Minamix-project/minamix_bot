"""A single, parameterless entry point to the private French reminder manager."""

import discord
from discord import app_commands

from src.utils.command_errors import ERROR_HANDLED_KEY
from src.utils.reminder_ui import send_view, ui_error
from src.utils.reminder_views import ReminderDashboard


async def register(bot):
    @bot.tree.command(name="reminder", description="Ouvrir tes rappels : créer, modifier, reporter, supprimer et consulter l'historique.")
    @app_commands.guild_only()
    async def reminder(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view = await ReminderDashboard.load(interaction.guild_id, interaction.user.id, guild=interaction.guild)
        await send_view(interaction, view)

    @reminder.error
    async def reminder_error(interaction, error):
        original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
        await ui_error(interaction, original)
        interaction.extras[ERROR_HANDLED_KEY] = True
