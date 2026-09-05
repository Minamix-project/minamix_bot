import discord
from discord import Interaction
from src.utils.db import get_db_connection
from src.utils.embed import set_bot_footer
from src.events.afk_handler import remove_afk


async def register(bot):
    @bot.tree.command(name="back", description="Annuler ton statut absent.")
    async def back(interaction: Interaction):
        db = await get_db_connection()
        cursor = await db.cursor()
        await cursor.execute(
            "SELECT original_nick FROM afk_users WHERE user_id = %s AND guild_id = %s",
            (interaction.user.id, interaction.guild.id)
        )
        row = (await cursor.fetchone())
        await cursor.close()
        db.close()

        if not row:
            embed = discord.Embed(
                title="❌ Tu n'es pas absent",
                description="Tu n'as pas de statut absent actif.",
                color=discord.Color.red()
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await remove_afk(interaction.user, interaction.guild)

        embed = discord.Embed(
            title="👋 Bienvenue de retour !",
            description="Ton statut absent a été annulé.",
            color=discord.Color.green()
        )
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed)
