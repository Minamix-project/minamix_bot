from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import Interaction
from src.utils.permissions import admin_only


async def register(bot):
    @bot.tree.command(name="backupstatus", description="Voir la dernière sauvegarde (Admin seulement)")
    @admin_only()
    async def backupstatus(interaction: Interaction):
        backups = list(Path("backups").glob("*.sql"))
        if not backups:
            await interaction.response.send_message("❌ Aucun dump SQL trouvé.", ephemeral=True)
            return
