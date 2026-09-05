from src.utils.permissions import admin_only
import discord
from discord import Interaction, TextChannel, app_commands
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer


async def register(bot):
    @bot.tree.command(name="setwarnlogs", description="Définir le channel de logs des warns (Admin seulement)")
    @app_commands.describe(channel="Channel où envoyer les logs de warns")
    @admin_only()
    async def setwarnlogs(interaction: Interaction, channel: TextChannel):
        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "INSERT INTO guild_config (guild_id, config_key, value) VALUES (%s, 'warn_logs_channel', %s) "
            "ON DUPLICATE KEY UPDATE value = %s",
            (interaction.guild.id, str(channel.id), str(channel.id))
        )
        await db.commit()
        await cursor.close()
        db.close()

        embed = discord.Embed(
            title="✅ Channel de logs warns défini",
            description=f"Les avertissements seront loggés dans {channel.mention}.",
            color=discord.Color.green()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
