import discord
from discord import Interaction, app_commands
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer


async def register(bot):
    @bot.tree.command(name="setrpchannel", description="Définir le channel d'annonce des personnages RP (Admin)")
    @app_commands.describe(channel="Channel où les fiches RP seront postées")
    async def setrpchannel(interaction: Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(title="❌ Permission refusée", color=discord.Color.red())
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "INSERT INTO guild_config (guild_id, config_key, value) VALUES (%s, 'rp_channel', %s) "
            "ON DUPLICATE KEY UPDATE value = VALUES(value)",
            (interaction.guild.id, str(channel.id))
        )
        await db.commit()
        await cursor.close()
        db.close()

        embed = discord.Embed(
            title="✅ Channel RP défini",
            description=f"Les fiches de personnages seront postées dans {channel.mention}.",
            color=discord.Color.green()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
