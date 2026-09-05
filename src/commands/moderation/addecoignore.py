from src.utils.permissions import admin_only
from discord import Interaction, TextChannel, app_commands
import discord
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.events.message_coins import invalidate_ignored_channels_cache


async def register(bot):
    @bot.tree.command(name="addecoignore", description="Exclure un channel des gains d'argent par message (Admin seulement)")
    @app_commands.describe(channel="Channel à exclure des gains")
    @admin_only()
    async def addecoignore(interaction: Interaction, channel: TextChannel):
        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "SELECT 1 FROM guild_economy_ignored_channels WHERE guild_id = %s AND channel_id = %s",
            (interaction.guild.id, channel.id)
        )
        already = (await cursor.fetchone())

        if already:
            await cursor.close()
            db.close()
            embed = discord.Embed(
                title="⚠️ Déjà exclu",
                description=f"{channel.mention} est déjà exclu des gains d'argent.",
                color=discord.Color.orange()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await cursor.execute(
            "INSERT INTO guild_economy_ignored_channels (guild_id, channel_id) VALUES (%s, %s)",
            (interaction.guild.id, channel.id)
        )
        await db.commit()
        await cursor.close()
        db.close()
        invalidate_ignored_channels_cache(interaction.guild.id)

        embed = discord.Embed(
            title="🚫 Channel exclu",
            description=f"{channel.mention} ne rapportera plus d'argent par message.",
            color=discord.Color.orange()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
