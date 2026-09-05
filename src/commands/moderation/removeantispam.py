from src.utils.permissions import admin_only
from discord import Interaction, TextChannel, app_commands
import discord
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer


async def register(bot):
    @bot.tree.command(name="removeantispam", description="Retirer un channel du mode anti-spam (Admin seulement)")
    @app_commands.describe(channel="Channel à retirer du mode anti-spam")
    @admin_only()
    async def removeantispam(interaction: Interaction, channel: TextChannel):
        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "DELETE FROM antispam_channels WHERE guild_id = %s AND channel_id = %s",
            (interaction.guild.id, channel.id)
        )
        affected = cursor.rowcount
        await db.commit()
        await cursor.close()
        db.close()

        if affected == 0:
            embed = discord.Embed(
                title="⚠️ Channel introuvable",
                description=f"{channel.mention} n'était pas en mode anti-spam.",
                color=discord.Color.orange()
            )
        else:
            embed = discord.Embed(
                title="✅ Channel retiré",
                description=f"{channel.mention} n'est plus en mode anti-spam.",
                color=discord.Color.green()
            )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
