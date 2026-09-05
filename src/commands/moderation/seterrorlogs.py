from discord import Interaction, TextChannel, app_commands
import discord
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer


async def register(bot):
    @bot.tree.command(name="seterrorlogs", description="Définir le channel des erreurs techniques (Admin seulement)")
    @app_commands.describe(channel="Channel privé où envoyer les erreurs techniques")
    async def seterrorlogs(interaction: Interaction, channel: TextChannel):
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(title="❌ Permission refusée", color=discord.Color.red())
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "INSERT INTO guild_config (guild_id, config_key, value) VALUES (%s, 'error_logs_channel', %s) "
            "ON DUPLICATE KEY UPDATE value = %s",
            (interaction.guild.id, str(channel.id), str(channel.id))
        )
        await db.commit()
        await cursor.close()
        db.close()

        embed = discord.Embed(
            title="✅ Channel d'erreurs défini",
            description=f"Les erreurs techniques (référence, commande, heure) seront envoyées dans {channel.mention}.",
            color=discord.Color.green()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
