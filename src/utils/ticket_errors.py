"""Shared French error responses for ticket commands and components."""

import discord
from discord import app_commands

from src.utils.error_reporting import report_error
from src.utils.tickets import TicketError


async def send_error(interaction, error):
    if isinstance(error, app_commands.CommandInvokeError):
        error = error.original
    if isinstance(error, TicketError):
        message = f"❌ {error}"
    elif isinstance(error, app_commands.CheckFailure):
        message = "❌ Cette action est réservée à l'administration du serveur."
    elif isinstance(error, discord.Forbidden):
        message = "❌ Discord refuse cette action. Vérifie les permissions du bot dans le salon et la catégorie."
    elif isinstance(error, discord.HTTPException):
        message = "❌ Discord n'a pas pu terminer cette action. Vérifie le ticket avant de réessayer."
    else:
        reference = await report_error(
            interaction.client, guild_ids=interaction.guild_id, source="ticket", error=error, user=interaction.user
        )
        message = f"❌ Une erreur est survenue. Référence : `{reference}`"
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    else:
        await interaction.response.send_message(
            message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )
