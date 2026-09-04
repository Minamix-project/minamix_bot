import os

import discord
from discord import Interaction

from src.config import GUILD_IDS
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.utils.permissions import admin_only


async def register(bot):
    @bot.tree.command(name="health", description="Vérifier la santé du bot (Admin seulement)")
    @admin_only()
    async def health(interaction: Interaction):
        db_ok = False
        db_error = None
        try:
            db = get_db_connection()
            with db.cursor() as cursor:
                cursor.execute("SELECT 1")
                db_ok = cursor.fetchone()[0] == 1
            db.close()
        except Exception as exc:
            db_error = type(exc).__name__

        embed = discord.Embed(
            title="🩺 État du bot",
            color=discord.Color.green() if db_ok else discord.Color.red(),
        )
        embed.add_field(name="Discord", value=f"{round(bot.latency * 1000)} ms", inline=True)
        embed.add_field(name="Base MySQL", value="✅ Connectée" if db_ok else f"❌ Indisponible ({db_error})", inline=True)
        embed.add_field(name="Version", value=os.getenv("BOT_VERSION", "dev"), inline=True)
        embed.add_field(name="Serveurs autorisés", value=str(len(GUILD_IDS)), inline=True)
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
