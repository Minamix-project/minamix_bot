from src.utils.permissions import admin_only
import discord
from discord import Interaction, Member, app_commands
from src.utils.embed import set_bot_footer
from src.utils.warn import issue_warn


async def register(bot):
    @bot.tree.command(name="warn", description="Avertir un membre (Admin seulement)")
    @app_commands.describe(user="Membre à avertir", reason="Raison de l'avertissement")
    @admin_only()
    async def warn(interaction: Interaction, user: Member, reason: str):
        if user.bot:
            embed = discord.Embed(title="❌ Impossible d'avertir un bot.", color=discord.Color.red())
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        total = await issue_warn(bot, interaction.guild, user, interaction.user, reason)

        embed = discord.Embed(
            title="⚠️ Avertissement envoyé",
            description=f"{user.mention} a été averti(e).\n**Raison :** {reason}\n*Total : {total} warn(s)*",
            color=discord.Color.orange()
        )
        set_bot_footer(embed, interaction)
        await interaction.followup.send(embed=embed, ephemeral=True)
