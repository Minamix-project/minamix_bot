from src.utils.permissions import admin_only
from discord import Interaction
import discord
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer


async def register(bot):
    @bot.tree.command(name="listecoignore", description="Lister les channels exclus des gains par message (Admin seulement)")
    @admin_only()
    async def listecoignore(interaction: Interaction):
        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "SELECT channel_id FROM guild_economy_ignored_channels WHERE guild_id = %s",
            (interaction.guild.id,)
        )
        rows = (await cursor.fetchall())
        await cursor.close()
        db.close()

        embed = discord.Embed(title="🚫 Channels exclus des gains", color=discord.Color.orange())
        embed.description = "\n".join(f"<#{row[0]}>" for row in rows) if rows else "Aucun channel exclu."
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
