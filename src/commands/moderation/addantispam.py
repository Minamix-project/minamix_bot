from discord import Interaction, TextChannel, app_commands
import discord
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer


async def register(bot):
    @bot.tree.command(name="addantispam", description="Ajouter un channel anti-spam (ban instantané) (Admin seulement)")
    @app_commands.describe(channel="Channel à passer en mode anti-spam")
    async def addantispam(interaction: Interaction, channel: TextChannel):
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(title="❌ Permission refusée", color=discord.Color.red())
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "SELECT 1 FROM antispam_channels WHERE guild_id = %s AND channel_id = %s",
            (interaction.guild.id, channel.id)
        )
        already = (await cursor.fetchone())

        if already:
            await cursor.close()
            db.close()
            embed = discord.Embed(
                title="⚠️ Déjà en anti-spam",
                description=f"{channel.mention} est déjà en mode anti-spam.",
                color=discord.Color.orange()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await cursor.execute(
            "INSERT INTO antispam_channels (guild_id, channel_id) VALUES (%s, %s)",
            (interaction.guild.id, channel.id)
        )
        await db.commit()
        await cursor.close()
        db.close()

        embed = discord.Embed(
            title="🚫 Channel anti-spam ajouté",
            description=f"{channel.mention} est maintenant en mode anti-spam.\nTout message posté dedans entraînera un ban immédiat.",
            color=discord.Color.orange()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
