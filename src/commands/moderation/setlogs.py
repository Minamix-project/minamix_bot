from src.utils.permissions import admin_only
from discord import Interaction, TextChannel, app_commands
import discord
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer


async def register(bot):
    @bot.tree.command(name="setlogs", description="Définir le salon des logs généraux et des messages (Admin seulement)")
    @app_commands.describe(channel="Salon des logs, dont les modifications et suppressions de messages")
    @admin_only()
    async def setlogs(interaction: Interaction, channel: TextChannel):
        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "INSERT INTO guild_config (guild_id, config_key, value) VALUES (%s, 'logs_channel', %s) "
            "ON DUPLICATE KEY UPDATE value = %s",
            (interaction.guild.id, str(channel.id), str(channel.id))
        )
        await db.commit()
        await cursor.close()
        db.close()

        embed = discord.Embed(
            title="✅ Salon des logs généraux défini",
            description=(
                f"Les logs seront envoyés dans {channel.mention}, y compris les modifications "
                "et suppressions de messages avec leur contenu disponible.\n"
                "Le bot doit pouvoir voir ce salon, y envoyer des messages, intégrer des liens "
                "et joindre des fichiers pour les contenus longs et les suppressions groupées."
            ),
            color=discord.Color.green()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
