from src.utils.permissions import admin_only
from discord import Interaction, TextChannel, app_commands
import discord
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.events.message_coins import invalidate_ignored_channels_cache


async def register(bot):
    @bot.tree.command(name="removeecoignore", description="Réautoriser les gains d'argent par message dans un channel (Admin seulement)")
    @app_commands.describe(channel="Channel à réautoriser")
    @admin_only()
    async def removeecoignore(interaction: Interaction, channel: TextChannel):
        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "DELETE FROM guild_economy_ignored_channels WHERE guild_id = %s AND channel_id = %s",
            (interaction.guild.id, channel.id)
        )
        deleted = cursor.rowcount
        await db.commit()
        await cursor.close()
        db.close()
        invalidate_ignored_channels_cache(interaction.guild.id)

        if not deleted:
            embed = discord.Embed(
                title="⚠️ Non exclu",
                description=f"{channel.mention} n'était pas exclu des gains.",
                color=discord.Color.orange()
            )
        else:
            embed = discord.Embed(
                title="✅ Channel réautorisé",
                description=f"{channel.mention} rapporte de nouveau de l'argent par message.",
                color=discord.Color.green()
            )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
