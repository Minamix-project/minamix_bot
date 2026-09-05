from discord import Interaction
import discord
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer


async def register(bot):
    @bot.tree.command(name="listantispam", description="Lister les channels anti-spam (Admin seulement)")
    async def listantispam(interaction: Interaction):
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(title="❌ Permission refusée", color=discord.Color.red())
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "SELECT channel_id FROM antispam_channels WHERE guild_id = %s",
            (interaction.guild.id,)
        )
        rows = (await cursor.fetchall())
        await cursor.close()
        db.close()

        if not rows:
            embed = discord.Embed(
                title="🚫 Channels anti-spam",
                description="Aucun channel anti-spam configuré.",
                color=discord.Color.orange()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        lines = "\n".join(f"<#{row[0]}>" for row in rows)
        embed = discord.Embed(
            title="🚫 Channels anti-spam",
            description=lines,
            color=discord.Color.orange()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
